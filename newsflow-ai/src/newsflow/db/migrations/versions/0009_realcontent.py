"""Phase 5C: real-content Autopilot, RSS connection checks and AI usage accounting (additive)."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_drafts", sa.Column("review_notes", sa.JSON))
    op.add_column(
        "autopilot_jobs", sa.Column("content_mode", sa.String(16), nullable=False, server_default="trial")
    )
    op.add_column(
        "autopilot_jobs", sa.Column("ai_mode", sa.String(16), nullable=False, server_default="offline")
    )
    op.add_column("autopilot_jobs", sa.Column("voice", sa.String(200)))
    op.create_table(
        "news_source_checks",
        sa.Column(
            "source_id", sa.Integer, sa.ForeignKey("news_sources.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20)),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("article_count", sa.Integer, nullable=False),
        sa.Column("dated_count", sa.Integer, nullable=False),
        sa.Column("summarized_count", sa.Integer, nullable=False),
        sa.Column("checked_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("intelligence_runs.id")),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=False),
        sa.Column("completion_tokens", sa.Integer, nullable=False),
        sa.Column("total_tokens", sa.Integer, nullable=False),
        sa.Column("elapsed_ms", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_ai_usage_created_at", "ai_usage", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_created_at", table_name="ai_usage")
    op.drop_table("ai_usage")
    op.drop_table("news_source_checks")
    op.drop_column("autopilot_jobs", "voice")
    op.drop_column("autopilot_jobs", "ai_mode")
    op.drop_column("autopilot_jobs", "content_mode")
    op.drop_column("content_drafts", "review_notes")
