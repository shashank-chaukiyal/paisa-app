"""
app/api/v1/transactions.py

Fix #11 (Batch rollback corruption):
  BEFORE: A single item failure called db.rollback() which rolled back
          the ENTIRE session — all previously flushed items in that batch
          were lost, but created_count already counted them as successes.
          The API response was lying about how many records were created.

  AFTER:  Each item uses a nested transaction (savepoint) via
          db.begin_nested(). Only the failing item's savepoint is rolled
          back; previously successful items survive in the outer transaction.
          This gives true per-item isolation.
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import UUID4, BaseModel, Field, field_validator
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.transaction import Transaction, TransactionType, TransactionSource, SyncStatus
from app.redis_client import get_redis
from app.config import settings

log = structlog.get_logger(__name__)
router = APIRouter()

# ─── Request / Response schemas ───────────────────────────────────────

class TransactionIn(BaseModel):
    client_id: str = Field(..., description="Device-generated UUID — idempotency anchor")
    amount_paise: int = Field(..., gt=0, description="Amount in paise (100 paise = 1 INR)")
    txn_type: TransactionType
    txn_date: datetime
    description: str = Field(..., min_length=1, max_length=500)
    category_id: Optional[int] = None
    merchant: Optional[str] = Field(None, max_length=200)
    reference_id: Optional[str] = Field(None, max_length=100)
    upi_vpa: Optional[str] = Field(None, max_length=100)
    bank_name: Optional[str] = Field(None, max_length=100)
    account_masked: Optional[str] = Field(None, max_length=20)
    source: TransactionSource = TransactionSource.MANUAL
    notes: Optional[str] = None
    tags: Optional[list[str]] = None

    @field_validator("amount_paise")
    @classmethod
    def amount_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount_paise must be positive")
        return v


class TransactionOut(BaseModel):
    id: UUID4
    client_id: Optional[str]
    amount_paise: int
    amount_rupees: float
    txn_type: TransactionType
    txn_date: datetime
    description: str
    category_id: Optional[int]
    merchant: Optional[str]
    reference_id: Optional[str]
    upi_vpa: Optional[str]
    bank_name: Optional[str]
    account_masked: Optional[str]
    source: TransactionSource
    notes: Optional[str]
    tags: Optional[list]
    sync_status: SyncStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_ext(cls, txn: Transaction) -> "TransactionOut":
        data = {k: getattr(txn, k) for k in cls.model_fields if hasattr(txn, k)}
        data["amount_rupees"] = txn.amount_paise / 100
        return cls(**data)


class CursorPage(BaseModel):
    items: list[TransactionOut]
    next_cursor: Optional[str] = None
    total_hint: Optional[int] = None


class BatchCreateIn(BaseModel):
    transactions: list[TransactionIn] = Field(..., max_length=100)


class BatchItemResult(BaseModel):
    client_id: str
    status: str
    id: Optional[UUID4] = None
    error: Optional[str] = None


class BatchCreateOut(BaseModel):
    results: list[BatchItemResult]
    created_count: int
    duplicate_count: int
    error_count: int


# ─── Cursor helpers ───────────────────────────────────────────────────

def encode_cursor(updated_at: datetime, txn_id: uuid.UUID) -> str:
    payload = json.dumps({"ts": updated_at.isoformat(), "id": str(txn_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(payload["ts"]), uuid.UUID(payload["id"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid cursor: {exc}")


# ─── Idempotency ──────────────────────────────────────────────────────

async def idempotency_check(key: str, redis) -> Optional[dict]:
    lock_key   = f"idem:lock:{key}"
    result_key = f"idem:result:{key}"

    cached = await redis.get(result_key)
    if cached:
        return json.loads(cached)

    acquired = await redis.set(lock_key, "1", ex=60, nx=True)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Request with this idempotency key is already in progress",
        )
    return None


async def idempotency_store(key: str, result: dict, redis) -> None:
    result_key = f"idem:result:{key}"
    lock_key   = f"idem:lock:{key}"
    await redis.setex(result_key, settings.IDEMPOTENCY_TTL_SECONDS, json.dumps(result))
    await redis.delete(lock_key)


# ─── Routes ───────────────────────────────────────────────────────────

@router.get("", response_model=CursorPage)
async def list_transactions(
    cursor: Optional[str] = Query(None),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE),
    txn_type: Optional[TransactionType] = None,
    category_id: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    search: Optional[str] = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .where(Transaction.is_deleted == False)
        .order_by(desc(Transaction.updated_at), desc(Transaction.id))
        .limit(limit + 1)
    )

    if txn_type:
        stmt = stmt.where(Transaction.txn_type == txn_type)
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
    if from_date:
        stmt = stmt.where(Transaction.txn_date >= from_date)
    if to_date:
        stmt = stmt.where(Transaction.txn_date <= to_date)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            Transaction.description.ilike(pattern)
            | Transaction.merchant.ilike(pattern)
        )

    if cursor:
        cur_ts, cur_id = decode_cursor(cursor)
        stmt = stmt.where(
            (Transaction.updated_at < cur_ts)
            | ((Transaction.updated_at == cur_ts) & (Transaction.id < cur_id))
        )

    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_next = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_cursor(items[-1].updated_at, items[-1].id) if has_next and items else None

    return CursorPage(
        items=[TransactionOut.from_orm_ext(t) for t in items],
        next_cursor=next_cursor,
    )


@router.post("", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    body: TransactionIn,
    x_idempotency_key: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    user=Depends(get_current_user),
):
    log.info("transaction.create_start", user_id=str(user.id), client_id=body.client_id)

    if x_idempotency_key:
        idem_key = f"{user.id}:{x_idempotency_key}"
        cached = await idempotency_check(idem_key, redis)
        if cached:
            return TransactionOut(**cached)

    existing = await db.execute(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.client_id == body.client_id,
        )
    )
    existing_txn = existing.scalar_one_or_none()
    if existing_txn:
        out = TransactionOut.from_orm_ext(existing_txn)
        if x_idempotency_key:
            await idempotency_store(idem_key, out.model_dump(mode="json"), redis)
        return out

    txn = Transaction(
        user_id=user.id,
        client_id=body.client_id,
        amount_paise=body.amount_paise,
        txn_type=body.txn_type,
        txn_date=body.txn_date,
        description=body.description,
        category_id=body.category_id,
        merchant=body.merchant,
        reference_id=body.reference_id,
        upi_vpa=body.upi_vpa,
        bank_name=body.bank_name,
        account_masked=body.account_masked,
        source=body.source,
        notes=body.notes,
        tags=body.tags,
        sync_status=SyncStatus.SYNCED,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    out = TransactionOut.from_orm_ext(txn)
    if x_idempotency_key:
        await idempotency_store(idem_key, out.model_dump(mode="json"), redis)

    log.info("transaction.created", txn_id=str(txn.id), amount_paise=txn.amount_paise)
    return out


@router.post("/batch", response_model=BatchCreateOut, status_code=status.HTTP_207_MULTI_STATUS)
async def batch_create_transactions(
    body: BatchCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Fix #11: Per-item savepoint isolation.

    BEFORE: db.rollback() on item failure rolled back the ENTIRE session.
            Items 1-4 could succeed, item 5 fails, ALL 5 get rolled back,
            but created_count was already at 4 — response data was wrong.

    AFTER:  Each item runs inside db.begin_nested() (a DB SAVEPOINT).
            Only that item's savepoint is released/rolled back on
            success/failure. The outer transaction commits only the
            items that actually succeeded.
    """
    log.info("transaction.batch_start", user_id=str(user.id), count=len(body.transactions))

    results: list[BatchItemResult] = []
    created_count = duplicate_count = error_count = 0

    client_ids = [t.client_id for t in body.transactions]
    existing_rows = (await db.execute(
        select(Transaction.client_id, Transaction.id).where(
            Transaction.user_id == user.id,
            Transaction.client_id.in_(client_ids),
        )
    )).all()
    existing_map = {row.client_id: row.id for row in existing_rows}

    for item in body.transactions:
        if item.client_id in existing_map:
            duplicate_count += 1
            results.append(BatchItemResult(
                client_id=item.client_id,
                status="duplicate",
                id=existing_map[item.client_id],
            ))
            continue

        try:
            # Fix: use savepoint so only THIS item rolls back on failure,
            # not the entire batch session.
            async with db.begin_nested():
                txn = Transaction(
                    user_id=user.id,
                    client_id=item.client_id,
                    amount_paise=item.amount_paise,
                    txn_type=item.txn_type,
                    txn_date=item.txn_date,
                    description=item.description,
                    category_id=item.category_id,
                    merchant=item.merchant,
                    reference_id=item.reference_id,
                    upi_vpa=item.upi_vpa,
                    bank_name=item.bank_name,
                    account_masked=item.account_masked,
                    source=item.source,
                    notes=item.notes,
                    tags=item.tags,
                    sync_status=SyncStatus.SYNCED,
                )
                db.add(txn)
                await db.flush()
                # Savepoint committed here — safe to count as created
                created_count += 1
                results.append(BatchItemResult(
                    client_id=item.client_id,
                    status="created",
                    id=txn.id,
                ))

        except Exception as exc:
            # Only this item's savepoint was rolled back — others survive
            error_count += 1
            results.append(BatchItemResult(
                client_id=item.client_id,
                status="error",
                error=str(exc)[:200],
            ))
            log.warning(
                "transaction.batch_item_failed",
                client_id=item.client_id,
                error=str(exc),
            )

    await db.commit()
    log.info(
        "transaction.batch_complete",
        created=created_count,
        duplicates=duplicate_count,
        errors=error_count,
    )
    return BatchCreateOut(
        results=results,
        created_count=created_count,
        duplicate_count=duplicate_count,
        error_count=error_count,
    )


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    txn_id: UUID4,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await db.execute(
        select(Transaction).where(
            Transaction.id == txn_id,
            Transaction.user_id == user.id,
        )
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    txn.is_deleted = True
    txn.deleted_at = datetime.utcnow()
    await db.commit()
    log.info("transaction.soft_deleted", txn_id=str(txn_id))
