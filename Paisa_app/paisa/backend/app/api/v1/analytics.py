"""
app/api/v1/analytics.py

Spending analytics — monthly trends, category breakdown, UPI stats.
All aggregations run server-side; mobile receives pre-computed summaries.
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.transaction import Transaction, TransactionType, Category

log = structlog.get_logger(__name__)
router = APIRouter()


class CategoryBreakdown(BaseModel):
    category_id: Optional[int]
    category_name: str
    total_paise: int
    total_rupees: float
    txn_count: int
    percentage: float


class MonthlyTrend(BaseModel):
    year: int
    month: int
    debit_paise: int
    credit_paise: int
    net_paise: int
    txn_count: int


class AnalyticsSummary(BaseModel):
    period_start: str
    period_end: str
    total_debit_paise: int
    total_credit_paise: int
    net_paise: int
    txn_count: int
    avg_txn_paise: int
    top_merchant: Optional[str]
    category_breakdown: list[CategoryBreakdown]
    monthly_trend: list[MonthlyTrend]


@router.get("/summary", response_model=AnalyticsSummary)
async def get_summary(
    from_date: date = Query(...),
    to_date: date = Query(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    from_dt = datetime.combine(from_date, datetime.min.time())
    to_dt = datetime.combine(to_date, datetime.max.time())

    base_filter = and_(
        Transaction.user_id == user.id,
        Transaction.txn_date >= from_dt,
        Transaction.txn_date <= to_dt,
        Transaction.is_deleted == False,
    )

    # ── Totals ──────────────────────────────────────────────────────
    totals = (await db.execute(
        select(
            func.sum(Transaction.amount_paise).filter(Transaction.txn_type == TransactionType.DEBIT).label("debit"),
            func.sum(Transaction.amount_paise).filter(Transaction.txn_type == TransactionType.CREDIT).label("credit"),
            func.count(Transaction.id).label("count"),
        ).where(base_filter)
    )).one()

    total_debit = totals.debit or 0
    total_credit = totals.credit or 0
    txn_count = totals.count or 0

    # ── Top merchant ────────────────────────────────────────────────
    top_merchant_row = (await db.execute(
        select(Transaction.merchant, func.sum(Transaction.amount_paise).label("total"))
        .where(base_filter, Transaction.txn_type == TransactionType.DEBIT, Transaction.merchant.isnot(None))
        .group_by(Transaction.merchant)
        .order_by(func.sum(Transaction.amount_paise).desc())
        .limit(1)
    )).first()
    top_merchant = top_merchant_row.merchant if top_merchant_row else None

    # ── Category breakdown ──────────────────────────────────────────
    cat_rows = (await db.execute(
        select(
            Transaction.category_id,
            Category.name.label("cat_name"),
            func.sum(Transaction.amount_paise).label("total"),
            func.count(Transaction.id).label("cnt"),
        )
        .outerjoin(Category, Transaction.category_id == Category.id)
        .where(base_filter, Transaction.txn_type == TransactionType.DEBIT)
        .group_by(Transaction.category_id, Category.name)
        .order_by(func.sum(Transaction.amount_paise).desc())
    )).all()

    breakdown = [
        CategoryBreakdown(
            category_id=r.category_id,
            category_name=r.cat_name or "Uncategorized",
            total_paise=r.total or 0,
            total_rupees=(r.total or 0) / 100,
            txn_count=r.cnt,
            percentage=round((r.total or 0) / total_debit * 100, 1) if total_debit else 0,
        )
        for r in cat_rows
    ]

    # ── Monthly trend ────────────────────────────────────────────────
    trend_rows = (await db.execute(
        select(
            func.extract("year", Transaction.txn_date).label("yr"),
            func.extract("month", Transaction.txn_date).label("mo"),
            func.sum(Transaction.amount_paise).filter(Transaction.txn_type == TransactionType.DEBIT).label("debit"),
            func.sum(Transaction.amount_paise).filter(Transaction.txn_type == TransactionType.CREDIT).label("credit"),
            func.count(Transaction.id).label("cnt"),
        )
        .where(base_filter)
        .group_by("yr", "mo")
        .order_by("yr", "mo")
    )).all()

    trend = [
        MonthlyTrend(
            year=int(r.yr),
            month=int(r.mo),
            debit_paise=r.debit or 0,
            credit_paise=r.credit or 0,
            net_paise=(r.credit or 0) - (r.debit or 0),
            txn_count=r.cnt,
        )
        for r in trend_rows
    ]

    return AnalyticsSummary(
        period_start=from_date.isoformat(),
        period_end=to_date.isoformat(),
        total_debit_paise=total_debit,
        total_credit_paise=total_credit,
        net_paise=total_credit - total_debit,
        txn_count=txn_count,
        avg_txn_paise=total_debit // txn_count if txn_count else 0,
        top_merchant=top_merchant,
        category_breakdown=breakdown,
        monthly_trend=trend,
    )
