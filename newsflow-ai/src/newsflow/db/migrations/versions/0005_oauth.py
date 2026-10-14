"""Add offline OAuth preparation metadata; existing 0001~0004 remain unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_connections",
        sa.Column("account_id", sa.Integer, sa.ForeignKey("platform_accounts.id"), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.DateTime),
        sa.Column("error_code", sa.String(32)),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oauth_connections")
