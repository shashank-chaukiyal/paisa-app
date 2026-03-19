"""
alembic/versions/0001_initial_schema.py
Initial schema migration — creates all tables, indexes, and constraints.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(15), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("pin_hash", sa.String(255), nullable=True),
        sa.Column("biometric_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("biometric_public_key", sa.Text, nullable=True),
        sa.Column("fcm_token", sa.String(512), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Asia/Kolkata"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_users_phone", "users", ["phone"])

    # ── refresh_tokens ────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("device_id", sa.String(255), nullable=True),
        sa.Column("issued_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])

    # ── categories ────────────────────────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("is_income", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_category_user_name"),
    )
    op.create_index("ix_categories_user_id", "categories", ["user_id"])

    # Seed default categories
    op.execute("""
        INSERT INTO categories (user_id, name, icon, color, is_income, sort_order) VALUES
        (NULL, 'Food & Dining', 'utensils', '#F59E0B', false, 1),
        (NULL, 'Transportation', 'car', '#3B82F6', false, 2),
        (NULL, 'Shopping', 'shopping-bag', '#8B5CF6', false, 3),
        (NULL, 'Entertainment', 'film', '#EC4899', false, 4),
        (NULL, 'Bills & Utilities', 'zap', '#EF4444', false, 5),
        (NULL, 'Health & Medical', 'heart', '#10B981', false, 6),
        (NULL, 'Travel', 'plane', '#06B6D4', false, 7),
        (NULL, 'Education', 'book', '#F97316', false, 8),
        (NULL, 'Salary', 'briefcase', '#059669', true, 1),
        (NULL, 'Freelance', 'monitor', '#0EA5E9', true, 2),
        (NULL, 'Investment Returns', 'trending-up', '#7C3AED', true, 3),
        (NULL, 'Other Income', 'plus-circle', '#64748B', true, 4)
    """)

    # ── transactions ──────────────────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount_paise", sa.BigInteger, nullable=False),
        sa.Column("txn_type", sa.String(10), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("merchant", sa.String(200), nullable=True),
        sa.Column("reference_id", sa.String(100), nullable=True),
        sa.Column("upi_vpa", sa.String(100), nullable=True),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("account_masked", sa.String(20), nullable=True),
        sa.Column("txn_date", sa.DateTime, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("tags", postgresql.JSONB, nullable=True),
        sa.Column("raw_sms_id", sa.Integer, nullable=True),
        sa.Column("client_id", sa.String(36), nullable=True),
        sa.Column("sync_status", sa.String(20), nullable=False, server_default="synced"),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("user_id", "client_id", name="uq_txn_user_client"),
    )
    op.create_index("ix_txn_user_date", "transactions", ["user_id", "txn_date"])
    op.create_index("ix_txn_user_type", "transactions", ["user_id", "txn_type"])
    op.create_index("ix_txn_client_id", "transactions", ["user_id", "client_id"])
    op.create_index("ix_txn_updated_at", "transactions", ["user_id", "updated_at"])

    # Trigger: auto-update updated_at on row change
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_transactions_updated_at
        BEFORE UPDATE ON transactions
        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    """)

    # ── sms_logs ──────────────────────────────────────────────────────
    op.create_table(
        "sms_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(255), nullable=False),
        sa.Column("sender", sa.String(50), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("message_hash", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime, nullable=False),
        sa.Column("processed_at", sa.DateTime, nullable=True),
        sa.Column("parse_success", sa.Boolean, nullable=True),
        sa.Column("parse_error", sa.String(500), nullable=True),
        sa.Column("bank_detected", sa.String(100), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "device_id", "message_hash", name="uq_sms_dedup"),
    )
    op.create_index("ix_sms_user_processed", "sms_logs", ["user_id", "processed_at"])
    op.create_index("ix_sms_received_at", "sms_logs", ["received_at"])

    # ── FK: transactions.raw_sms_id → sms_logs.id (added after both tables exist)
    op.create_foreign_key(
        "fk_txn_raw_sms", "transactions", "sms_logs",
        ["raw_sms_id"], ["id"], ondelete="SET NULL"
    )

    # ── budgets ───────────────────────────────────────────────────────
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("limit_paise", sa.BigInteger, nullable=False),
        sa.Column("period", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("alert_at_80", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "category_id", "period", name="uq_budget_category_period"),
    )
    op.create_index("ix_budgets_user_id", "budgets", ["user_id"])

    # ── notification_logs ─────────────────────────────────────────────
    op.create_table(
        "notification_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.String(500), nullable=False),
        sa.Column("data", postgresql.JSONB, nullable=True),
        sa.Column("fcm_message_id", sa.String(255), nullable=True),
        sa.Column("delivered", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notif_user_created", "notification_logs", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("notification_logs")
    op.drop_table("budgets")
    op.drop_table("sms_logs")
    op.drop_table("transactions")
    op.drop_table("categories")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at CASCADE;")
