"""Add secret-free credential rotation journal; previous revisions stay unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_credential_rotations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("platform_accounts.id"), nullable=False),
        sa.Column("account_key", sa.String(40), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("expected_revision", sa.Integer, nullable=False),
        sa.Column("old_reference", sa.String(32)),
        sa.Column("new_reference", sa.String(32)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_oauth_credential_rotations_account_id", "oauth_credential_rotations", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_credential_rotations_account_id", table_name="oauth_credential_rotations")
    op.drop_table("oauth_credential_rotations")
