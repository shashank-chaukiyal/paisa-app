"""app/api/v1/budgets.py — Budget CRUD with current spend calculation"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.transaction import Budget, BudgetPeriod, Transaction, TransactionType

log = structlog.get_logger(__name__)
router = APIRouter()


class BudgetIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    category_id: Optional[int] = None
    limit_paise: int = Field(..., gt=0)
    period: BudgetPeriod = BudgetPeriod.MONTHLY
    alert_at_80: bool = True


class BudgetOut(BaseModel):
    id: int
    name: str
    category_id: Optional[int]
    limit_paise: int
    limit_rupees: float
    period: BudgetPeriod
    alert_at_80: bool
    is_active: bool
    spent_paise: int = 0
    spent_rupees: float = 0
    remaining_paise: int = 0
    percent_used: float = 0

    model_config = {"from_attributes": True}


@router.get("", response_model=list[BudgetOut])
async def list_budgets(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    budgets_result = await db.execute(
        select(Budget).where(Budget.user_id == user.id, Budget.is_active == True)
    )
    budgets = budgets_result.scalars().all()

    # Compute current-period spend for each budget
    today = date.today()
    month_start = datetime.combine(today.replace(day=1), datetime.min.time())

    out = []
    for b in budgets:
        spent_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount_paise), 0)).where(
                Transaction.user_id == user.id,
                Transaction.category_id == b.category_id if b.category_id else True,
                Transaction.txn_type == TransactionType.DEBIT,
                Transaction.txn_date >= month_start,
                Transaction.is_deleted == False,
            )
        )
        spent = spent_result.scalar() or 0
        pct = round(spent / b.limit_paise * 100, 1) if b.limit_paise else 0

        out.append(BudgetOut(
            id=b.id,
            name=b.name,
            category_id=b.category_id,
            limit_paise=b.limit_paise,
            limit_rupees=b.limit_paise / 100,
            period=b.period,
            alert_at_80=b.alert_at_80,
            is_active=b.is_active,
            spent_paise=spent,
            spent_rupees=spent / 100,
            remaining_paise=max(0, b.limit_paise - spent),
            percent_used=pct,
        ))
    return out


@router.post("", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
async def create_budget(
    body: BudgetIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    budget = Budget(
        user_id=user.id,
        name=body.name,
        category_id=body.category_id,
        limit_paise=body.limit_paise,
        period=body.period,
        alert_at_80=body.alert_at_80,
    )
    db.add(budget)
    await db.commit()
    await db.refresh(budget)
    log.info("budget.created", budget_id=budget.id, limit_paise=budget.limit_paise)
    return BudgetOut(
        id=budget.id, name=budget.name, category_id=budget.category_id,
        limit_paise=budget.limit_paise, limit_rupees=budget.limit_paise / 100,
        period=budget.period, alert_at_80=budget.alert_at_80, is_active=True,
    )


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(
    budget_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(Budget).where(Budget.id == budget_id, Budget.user_id == user.id)
    )
    budget = result.scalar_one_or_none()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    budget.is_active = False
    await db.commit()
