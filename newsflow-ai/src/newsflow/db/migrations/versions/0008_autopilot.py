"""Add durable local automation and review-only video previews; preserve earlier revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("video_projects", sa.Column("preview_only", sa.Boolean, nullable=False, server_default="0"))
    op.add_column("publish_drafts", sa.Column("autopilot_task_id", sa.String(32)))
    op.create_index("ix_publish_drafts_autopilot_task_id", "publish_drafts", ["autopilot_task_id"], unique=True)
    op.create_table(
        "autopilot_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("active_slot", sa.Integer, unique=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("duration", sa.Integer, nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_stage", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("cancel_requested", sa.Boolean, nullable=False),
        sa.Column("article_id", sa.Integer, sa.ForeignKey("news_articles.id")),
        sa.Column("stage_results", sa.JSON, nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("error_code", sa.String(40)),
        sa.Column("retryable", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_table(
        "autopilot_attempts", sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("autopilot_jobs.id"), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False), sa.Column("number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("error_code", sa.String(40)),
        sa.Column("started_at", sa.DateTime, nullable=False), sa.Column("finished_at", sa.DateTime),
    )
    op.create_table(
        "autopilot_artifacts", sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("autopilot_jobs.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False), sa.Column("reference", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False), sa.UniqueConstraint("job_id", "kind", "reference"),
    )
    op.create_table(
        "autopilot_events", sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("autopilot_jobs.id"), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("message", sa.String(300), nullable=False), sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "autopilot_article_claims",
        sa.Column("article_id", sa.Integer, sa.ForeignKey("news_articles.id"), primary_key=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("autopilot_jobs.id"), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    for table in ("autopilot_attempts", "autopilot_artifacts", "autopilot_events"):
        op.create_index(f"ix_{table}_job_id", table, ["job_id"])


def downgrade() -> None:
    for table in ("autopilot_article_claims", "autopilot_events", "autopilot_artifacts", "autopilot_attempts", "autopilot_jobs"):
        op.drop_table(table)
    op.drop_index("ix_publish_drafts_autopilot_task_id", table_name="publish_drafts")
    op.drop_column("publish_drafts", "autopilot_task_id")
    op.drop_column("video_projects", "preview_only")
