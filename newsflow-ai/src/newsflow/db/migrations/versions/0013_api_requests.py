"""Atomic API request reservations; existing revisions and data are preserved."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_request_reservations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reserved_usd", sa.String(32), nullable=False),
        sa.Column("estimated_usd", sa.String(32)),
        sa.Column("bounds", sa.JSON, nullable=False),
        sa.Column("prices", sa.JSON, nullable=False),
        sa.Column("usage", sa.JSON, nullable=False),
        sa.Column("test_only", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_index("ix_api_request_reservations_provider", "api_request_reservations", ["provider"])


def downgrade() -> None:
    op.drop_table("api_request_reservations")
