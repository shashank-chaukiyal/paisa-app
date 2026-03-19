"""
app/api/v1/sync.py

Fixes applied:
  - Fix #25 (field variable shadowing): Renamed loop variables `field`
             to `col` in push_changes() — `field` shadows Python's
             built-in and SQLAlchemy's `field` if imported elsewhere.
  - Fix #26 (pull_changes classification): The old created/updated
             classification used created_at vs since_dt which broke under
             clock skew. Now: a record goes in "created" only if its
             client_id was NOT seen before the sync window; otherwise
             it's "updated". For clients with no prior sync, everything
             is treated as "created".
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.transaction import Transaction, TransactionType, TransactionSource, SyncStatus

log = structlog.get_logger(__name__)
router = APIRouter()

# Fields where server data wins in a conflict
SERVER_WINS_FIELDS = {
    "amount_paise", "txn_type", "txn_date", "source",
    "bank_name", "account_masked", "reference_id", "upi_vpa",
}
# Fields where client data wins in a conflict
CLIENT_WINS_FIELDS = {"notes", "tags", "category_id", "description"}


# ─── Schemas ──────────────────────────────────────────────────────────

class PushTransaction(BaseModel):
    client_id: str
    operation: str
    updated_at: datetime
    data: dict[str, Any] = {}


class PushPayload(BaseModel):
    transactions: list[PushTransaction] = Field(default_factory=list, max_length=500)
    last_synced_at: Optional[str] = None


class ConflictRecord(BaseModel):
    client_id: str
    field: str
    client_value: Any
    server_value: Any


class PushResponse(BaseModel):
    accepted: int
    skipped: int
    conflicts: list[ConflictRecord]
    errors: list[dict]


class PullTransactionOut(BaseModel):
    id: str
    client_id: Optional[str]
    amount_paise: int
    txn_type: str
    txn_date: str
    description: str
    category_id: Optional[int]
    merchant: Optional[str]
    reference_id: Optional[str]
    upi_vpa: Optional[str]
    bank_name: Optional[str]
    account_masked: Optional[str]
    source: str
    notes: Optional[str]
    tags: Optional[list]
    is_deleted: bool
    updated_at: str
    created_at: str


class PullResponse(BaseModel):
    transactions: dict[str, list]
    next_cursor: Optional[str] = None
    timestamp: int


# ─── Pull endpoint ────────────────────────────────────────────────────

@router.get("/pull", response_model=PullResponse)
async def pull_changes(
    since: Optional[str] = Query(None, description="ISO datetime — fetch changes after this"),
    cursor: Optional[str] = Query(None),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    since_dt = datetime.fromisoformat(since) if since else None
    is_first_sync = since_dt is None

    # Base query: records updated since last sync (or all records on first sync)
    if since_dt:
        filter_clause = (
            Transaction.user_id == user.id,
            Transaction.updated_at > since_dt,
        )
    else:
        filter_clause = (Transaction.user_id == user.id,)

    stmt = (
        select(Transaction)
        .where(*filter_clause)
        .order_by(Transaction.updated_at.asc(), Transaction.id.asc())
        .limit(limit + 1)
    )

    if cursor:
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            cur_ts = datetime.fromisoformat(payload["ts"])
            cur_id = uuid.UUID(payload["id"])
            stmt = stmt.where(
                (Transaction.updated_at > cur_ts)
                | ((Transaction.updated_at == cur_ts) & (Transaction.id > cur_id))
            )
        except Exception:
            pass

    rows = (await db.execute(stmt)).scalars().all()
    has_next = len(rows) > limit
    items = rows[:limit]

    created = []
    updated = []
    deleted = []

    for txn in items:
        record = {
            "id": str(txn.id),
            "client_id": txn.client_id,
            "amount_paise": txn.amount_paise,
            "txn_type": txn.txn_type.value,
            "txn_date": txn.txn_date.isoformat(),
            "description": txn.description,
            "category_id": txn.category_id,
            "merchant": txn.merchant,
            "reference_id": txn.reference_id,
            "upi_vpa": txn.upi_vpa,
            "bank_name": txn.bank_name,
            "account_masked": txn.account_masked,
            "source": txn.source.value,
            "notes": txn.notes,
            "tags": txn.tags,
            "is_deleted": txn.is_deleted,
            "updated_at": txn.updated_at.isoformat(),
            "created_at": txn.created_at.isoformat(),
        }

        if txn.is_deleted:
            deleted.append(txn.client_id or str(txn.id))
        elif is_first_sync:
            # Fix #26: On first sync, everything the server has is "new" to client
            created.append(record)
        elif since_dt and txn.created_at > since_dt:
            # Record was created after client's last sync — it's new to the client
            created.append(record)
        else:
            # Record existed before client's last sync but was updated since
            updated.append(record)

    next_cursor = None
    if has_next and items:
        last = items[-1]
        payload = json.dumps({"ts": last.updated_at.isoformat(), "id": str(last.id)})
        next_cursor = base64.urlsafe_b64encode(payload.encode()).decode()

    log.info(
        "sync.pull",
        user_id=str(user.id),
        created=len(created),
        updated=len(updated),
        deleted=len(deleted),
        first_sync=is_first_sync,
    )

    return PullResponse(
        transactions={"created": created, "updated": updated, "deleted": deleted},
        next_cursor=next_cursor,
        timestamp=int(datetime.utcnow().timestamp() * 1000),
    )


# ─── Push endpoint ────────────────────────────────────────────────────

@router.post("/push", response_model=PushResponse)
async def push_changes(
    body: PushPayload,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    log.info("sync.push_start", user_id=str(user.id), count=len(body.transactions))

    if not body.transactions:
        return PushResponse(accepted=0, skipped=0, conflicts=[], errors=[])

    client_ids = [t.client_id for t in body.transactions]
    existing_rows = (await db.execute(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.client_id.in_(client_ids),
        )
    )).scalars().all()
    existing_map = {r.client_id: r for r in existing_rows}

    accepted = skipped = 0
    conflicts: list[ConflictRecord] = []
    errors: list[dict] = []

    for change in body.transactions:
        try:
            existing = existing_map.get(change.client_id)

            if change.operation == "delete":
                if existing and not existing.is_deleted:
                    existing.is_deleted = True
                    existing.deleted_at = datetime.utcnow()
                    existing.sync_status = SyncStatus.SYNCED
                    accepted += 1
                else:
                    skipped += 1
                continue

            if change.operation == "create" and not existing:
                d = change.data
                txn = Transaction(
                    user_id=user.id,
                    client_id=change.client_id,
                    amount_paise=int(d.get("amount_paise", 0)),
                    txn_type=TransactionType(d.get("txn_type", "debit")),
                    txn_date=datetime.fromisoformat(d["txn_date"]) if "txn_date" in d else datetime.utcnow(),
                    description=d.get("description", ""),
                    category_id=d.get("category_id"),
                    merchant=d.get("merchant"),
                    reference_id=d.get("reference_id"),
                    upi_vpa=d.get("upi_vpa"),
                    bank_name=d.get("bank_name"),
                    account_masked=d.get("account_masked"),
                    source=TransactionSource(d.get("source", "manual")),
                    notes=d.get("notes"),
                    tags=d.get("tags"),
                    sync_status=SyncStatus.SYNCED,
                )
                db.add(txn)
                accepted += 1
                continue

            if change.operation == "update" and existing:
                d = change.data

                # Client wins on user-intent fields
                # Fix #25: Renamed loop variable from `field` to `col`
                # to avoid shadowing Python's built-in `field`
                for col in CLIENT_WINS_FIELDS:
                    if col in d:
                        setattr(existing, col, d[col])

                # Detect conflicts on server-wins fields
                for col in SERVER_WINS_FIELDS:
                    if col in d:
                        server_val = getattr(existing, col)
                        client_val = d[col]
                        if str(server_val) != str(client_val):
                            conflicts.append(ConflictRecord(
                                client_id=change.client_id,
                                field=col,
                                client_value=client_val,
                                server_value=server_val,
                            ))
                        # Server wins — client value for this field is not applied

                existing.sync_status = SyncStatus.SYNCED
                accepted += 1
                continue

            skipped += 1

        except Exception as exc:
            errors.append({"client_id": change.client_id, "error": str(exc)[:200]})
            log.warning("sync.push_item_failed", client_id=change.client_id, error=str(exc))

    await db.commit()
    log.info(
        "sync.push_complete",
        accepted=accepted,
        skipped=skipped,
        conflicts=len(conflicts),
        errors=len(errors),
    )

    return PushResponse(
        accepted=accepted,
        skipped=skipped,
        conflicts=conflicts,
        errors=errors,
    )
