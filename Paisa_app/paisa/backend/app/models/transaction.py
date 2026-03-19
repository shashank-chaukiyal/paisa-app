"""
app/models/transaction.py

Fix #20: Added biometric_public_key column to User ORM model.
         Previously the column existed in the DB migration but was missing
         from the model, forcing the auth code to use raw SQL via
         __import__("sqlalchemy").text(...) as a workaround.
         Now auth.py can access user.biometric_public_key directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional, List

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def now_utc():
    return datetime.utcnow()


# ─── Enums ────────────────────────────────────────────────────────────

class TransactionType(str, PyEnum):
    DEBIT  = "debit"
    CREDIT = "credit"

class TransactionSource(str, PyEnum):
    SMS    = "sms"
    UPI    = "upi"
    MANUAL = "manual"
    IMPORT = "import"

class SyncStatus(str, PyEnum):
    PENDING  = "pending"
    SYNCED   = "synced"
    CONFLICT = "conflict"
    FAILED   = "failed"

class BudgetPeriod(str, PyEnum):
    WEEKLY  = "weekly"
    MONTHLY = "monthly"
    YEARLY  = "yearly"

class AlertType(str, PyEnum):
    BUDGET_EXCEEDED    = "budget_exceeded"
    BUDGET_80_PERCENT  = "budget_80_percent"
    LARGE_TRANSACTION  = "large_transaction"
    UNUSUAL_SPENDING   = "unusual_spending"


# ─── User ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id:           Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone:        Mapped[str]            = mapped_column(String(15), unique=True, nullable=False)
    email:        Mapped[Optional[str]]  = mapped_column(String(255), unique=True, nullable=True)
    display_name: Mapped[Optional[str]]  = mapped_column(String(100))
    pin_hash:     Mapped[Optional[str]]  = mapped_column(String(255))
    biometric_enabled: Mapped[bool]      = mapped_column(Boolean, default=False)

    # Fix #20: Column was missing from ORM model — it existed in the migration
    # but the auth code had to use raw SQL as a workaround.
    biometric_public_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    fcm_token:    Mapped[Optional[str]]  = mapped_column(String(512))
    currency:     Mapped[str]            = mapped_column(String(3), default="INR")
    timezone:     Mapped[str]            = mapped_column(String(50), default="Asia/Kolkata")
    is_active:    Mapped[bool]           = mapped_column(Boolean, default=True)
    created_at:   Mapped[datetime]       = mapped_column(DateTime, default=now_utc)
    updated_at:   Mapped[datetime]       = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
    deleted_at:   Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    transactions:   Mapped[List["Transaction"]]  = relationship(back_populates="user", lazy="raise")
    budgets:        Mapped[List["Budget"]]        = relationship(back_populates="user", lazy="raise")
    sms_logs:       Mapped[List["SmsLog"]]        = relationship(back_populates="user", lazy="raise")
    refresh_tokens: Mapped[List["RefreshToken"]]  = relationship(back_populates="user", lazy="raise")

    __table_args__ = (
        Index("ix_users_phone", "phone"),
        Index("ix_users_deleted_at", "deleted_at"),
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id:         Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:    Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str]            = mapped_column(String(64), unique=True)
    device_id:  Mapped[Optional[str]]  = mapped_column(String(255))
    issued_at:  Mapped[datetime]       = mapped_column(DateTime, default=now_utc)
    expires_at: Mapped[datetime]       = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_token_hash", "token_hash"),
    )


# ─── Category ─────────────────────────────────────────────────────────

class Category(Base):
    __tablename__ = "categories"

    id:         Mapped[int]                   = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:    Mapped[Optional[uuid.UUID]]   = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    name:       Mapped[str]                   = mapped_column(String(100), nullable=False)
    icon:       Mapped[Optional[str]]         = mapped_column(String(50))
    color:      Mapped[Optional[str]]         = mapped_column(String(7))
    is_income:  Mapped[bool]                  = mapped_column(Boolean, default=False)
    sort_order: Mapped[int]                   = mapped_column(Integer, default=0)
    created_at: Mapped[datetime]              = mapped_column(DateTime, default=now_utc)

    transactions: Mapped[List["Transaction"]] = relationship(back_populates="category", lazy="raise")

    __table_args__ = (
        Index("ix_categories_user_id", "user_id"),
        UniqueConstraint("user_id", "name", name="uq_category_user_name"),
    )


# ─── Transaction ──────────────────────────────────────────────────────

class Transaction(Base):
    __tablename__ = "transactions"

    id:              Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:         Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category_id:     Mapped[Optional[int]]    = mapped_column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    amount_paise:    Mapped[int]              = mapped_column(BigInteger, nullable=False)
    txn_type:        Mapped[TransactionType]  = mapped_column(Enum(TransactionType), nullable=False)
    source:          Mapped[TransactionSource] = mapped_column(Enum(TransactionSource), nullable=False, default=TransactionSource.MANUAL)
    description:     Mapped[str]              = mapped_column(String(500), nullable=False)
    merchant:        Mapped[Optional[str]]    = mapped_column(String(200))
    reference_id:    Mapped[Optional[str]]    = mapped_column(String(100))
    upi_vpa:         Mapped[Optional[str]]    = mapped_column(String(100))
    bank_name:       Mapped[Optional[str]]    = mapped_column(String(100))
    account_masked:  Mapped[Optional[str]]    = mapped_column(String(20))
    txn_date:        Mapped[datetime]         = mapped_column(DateTime, nullable=False, index=True)
    notes:           Mapped[Optional[str]]    = mapped_column(Text)
    tags:            Mapped[Optional[list]]   = mapped_column(JSONB, nullable=True)
    raw_sms_id:      Mapped[Optional[int]]    = mapped_column(Integer, ForeignKey("sms_logs.id", ondelete="SET NULL"), nullable=True)
    client_id:       Mapped[Optional[str]]    = mapped_column(String(36))
    sync_status:     Mapped[SyncStatus]       = mapped_column(Enum(SyncStatus), default=SyncStatus.SYNCED)
    is_deleted:      Mapped[bool]             = mapped_column(Boolean, default=False)
    created_at:      Mapped[datetime]         = mapped_column(DateTime, default=now_utc)
    updated_at:      Mapped[datetime]         = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
    deleted_at:      Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user:     Mapped["User"]              = relationship(back_populates="transactions")
    category: Mapped[Optional["Category"]] = relationship(back_populates="transactions")
    sms_log:  Mapped[Optional["SmsLog"]]  = relationship(back_populates="transaction", foreign_keys=[raw_sms_id])

    __table_args__ = (
        Index("ix_txn_user_date",    "user_id", "txn_date"),
        Index("ix_txn_user_type",    "user_id", "txn_type"),
        Index("ix_txn_client_id",    "user_id", "client_id"),
        Index("ix_txn_updated_at",   "user_id", "updated_at"),
        UniqueConstraint("user_id", "client_id", name="uq_txn_user_client"),
    )


# ─── SMS Log ──────────────────────────────────────────────────────────

class SmsLog(Base):
    __tablename__ = "sms_logs"

    id:            Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:       Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    device_id:     Mapped[str]          = mapped_column(String(255), nullable=False)
    sender:        Mapped[str]          = mapped_column(String(50), nullable=False)
    body:          Mapped[str]          = mapped_column(Text, nullable=False)
    message_hash:  Mapped[str]          = mapped_column(String(64), nullable=False)
    received_at:   Mapped[datetime]     = mapped_column(DateTime, nullable=False)
    processed_at:  Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    parse_success: Mapped[Optional[bool]]     = mapped_column(Boolean, nullable=True)
    parse_error:   Mapped[Optional[str]]      = mapped_column(String(500))
    bank_detected: Mapped[Optional[str]]      = mapped_column(String(100))
    retry_count:   Mapped[int]                = mapped_column(Integer, default=0)

    user:        Mapped["User"]                 = relationship(back_populates="sms_logs")
    transaction: Mapped[Optional["Transaction"]] = relationship(back_populates="sms_log", foreign_keys="Transaction.raw_sms_id")

    __table_args__ = (
        UniqueConstraint("user_id", "device_id", "message_hash", name="uq_sms_dedup"),
        Index("ix_sms_user_processed", "user_id", "processed_at"),
        Index("ix_sms_received_at", "received_at"),
    )


# ─── Budget ───────────────────────────────────────────────────────────

class Budget(Base):
    __tablename__ = "budgets"

    id:          Mapped[int]                  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:     Mapped[uuid.UUID]            = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    category_id: Mapped[Optional[int]]        = mapped_column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    name:        Mapped[str]                  = mapped_column(String(100), nullable=False)
    limit_paise: Mapped[int]                  = mapped_column(BigInteger, nullable=False)
    period:      Mapped[BudgetPeriod]         = mapped_column(Enum(BudgetPeriod), default=BudgetPeriod.MONTHLY)
    alert_at_80: Mapped[bool]                 = mapped_column(Boolean, default=True)
    is_active:   Mapped[bool]                 = mapped_column(Boolean, default=True)
    created_at:  Mapped[datetime]             = mapped_column(DateTime, default=now_utc)
    updated_at:  Mapped[datetime]             = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    user: Mapped["User"] = relationship(back_populates="budgets")

    __table_args__ = (
        Index("ix_budgets_user_id", "user_id"),
        UniqueConstraint("user_id", "category_id", "period", name="uq_budget_category_period"),
    )


# ─── Notification Log ─────────────────────────────────────────────────

class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id:             Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:        Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    alert_type:     Mapped[AlertType]    = mapped_column(Enum(AlertType), nullable=False)
    title:          Mapped[str]          = mapped_column(String(200))
    body:           Mapped[str]          = mapped_column(String(500))
    data:           Mapped[Optional[dict]] = mapped_column(JSONB)
    fcm_message_id: Mapped[Optional[str]] = mapped_column(String(255))
    delivered:      Mapped[bool]         = mapped_column(Boolean, default=False)
    created_at:     Mapped[datetime]     = mapped_column(DateTime, default=now_utc)

    __table_args__ = (
        Index("ix_notif_user_created", "user_id", "created_at"),
    )
