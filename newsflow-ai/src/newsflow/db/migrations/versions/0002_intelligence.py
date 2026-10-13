"""Additive Phase 2 evidence and drafts; preserves all Phase 1 data."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intelligence_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        *[sa.Column(n, sa.String(20), nullable=False) for n in ("kind", "status", "provider")],
        *[sa.Column(n, sa.JSON, nullable=False) for n in ("options", "evidence", "result")],
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_table(
        "content_drafts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("intelligence_runs.id"), nullable=False),
        sa.Column("duration", sa.Integer, nullable=False),
        sa.Column("content", sa.JSON, nullable=False),
        sa.Column("sources", sa.JSON, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("review_status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("content_drafts")
    op.drop_table("intelligence_runs")
