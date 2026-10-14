"""Add identity binding and preallocated ciphertext journal; keep revisions 1-6 immutable."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_identity_bindings",
        sa.Column("account_id", sa.Integer, sa.ForeignKey("platform_accounts.id"), primary_key=True),
        sa.Column("account_key", sa.String(40), nullable=False, unique=True),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("channel_binding_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("grant_fingerprint", sa.String(64)),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "oauth_lifecycle_operations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("platform_accounts.id"), nullable=False),
        sa.Column("account_key", sa.String(40), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("expected_revision", sa.Integer, nullable=False),
        sa.Column("old_reference", sa.String(32)),
        sa.Column("new_reference", sa.String(32), unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("claim_id", sa.String(32)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_oauth_lifecycle_operations_account_id", "oauth_lifecycle_operations", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_lifecycle_operations_account_id", table_name="oauth_lifecycle_operations")
    op.drop_table("oauth_lifecycle_operations")
    op.drop_table("oauth_identity_bindings")
