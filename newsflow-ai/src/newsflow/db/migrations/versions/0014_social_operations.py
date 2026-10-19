"""Additive publishing calendar and provenance-bearing analytics. No old data rewrite."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publish_schedules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cohort_id", sa.Integer, sa.ForeignKey("publish_evidence.id"), nullable=False, unique=True),
        sa.Column("due_at", sa.DateTime, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("approval", sa.JSON, nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "social_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("publish_jobs.id"), nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("platform_accounts.id"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("remote_id", sa.String(160), nullable=False),
        sa.Column("metric", sa.String(80), nullable=False),
        sa.Column("value", sa.String(60), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("period_start", sa.String(10), nullable=False),
        sa.Column("period_end", sa.String(10), nullable=False),
        sa.Column("period_basis", sa.String(40), nullable=False),
        sa.Column("published_at", sa.DateTime),
        sa.Column("synthetic", sa.Boolean, nullable=False),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("job_id", "metric", "period_start", "period_end", "synthetic"),
    )
    op.create_table(
        "social_metric_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("publish_jobs.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("synthetic", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("social_metric_runs")
    op.drop_table("social_metrics")
    op.drop_table("publish_schedules")
