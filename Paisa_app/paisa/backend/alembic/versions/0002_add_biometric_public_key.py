"""
alembic/versions/0002_add_biometric_public_key.py

Fix #20: The biometric_public_key column was being accessed via raw SQL
in auth.py because it was missing from the SQLAlchemy ORM User model.
This migration documents that the column already exists in the DB
(it was added in 0001) and serves as the anchor for the ORM fix.

If you are running a fresh database, this migration is a no-op
(the column already exists from 0001). If upgrading an existing DB
that was created before 0001 was corrected, this adds the column.
"""
from alembic import op
import sqlalchemy as sa

revision    = "0002"
down_revision = "0001"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # Add biometric_public_key column to users table if it doesn't already exist.
    # Using a try/except here because 0001 already creates this column —
    # this migration ensures any DB created without it gets it added.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("users")]

    if "biometric_public_key" not in columns:
        op.add_column(
            "users",
            sa.Column("biometric_public_key", sa.Text, nullable=True),
        )
        print("✅ Added biometric_public_key column to users")
    else:
        print("ℹ️  biometric_public_key already exists — skipping")


def downgrade() -> None:
    op.drop_column("users", "biometric_public_key")
