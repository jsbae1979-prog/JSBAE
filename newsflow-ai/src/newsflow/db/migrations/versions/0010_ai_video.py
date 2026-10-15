"""Phase 5D: optional AI video provider plans, per-scene clips, model catalog and cost usage (additive)."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_ai_models",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("path", sa.String(160), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("price_per_second", sa.String(20), nullable=False),
        sa.Column("durations", sa.String(60), nullable=False),
        sa.Column("resolution", sa.String(10), nullable=False),
        sa.Column("confirmed_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("provider", "path"),
    )
    op.create_table(
        "ai_video_plans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("draft_id", sa.Integer, sa.ForeignKey("content_drafts.id"), nullable=False),
        sa.Column("draft_revision", sa.Integer, nullable=False),
        sa.Column("duration", sa.Integer, nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("confirmed_at", sa.DateTime),
        sa.Column("reviewed_at", sa.DateTime),
        sa.Column("approved_at", sa.DateTime),
        sa.Column("render_job_id", sa.Integer, sa.ForeignKey("render_jobs.id")),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "ai_video_scenes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plan_id", sa.Integer, sa.ForeignKey("ai_video_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("start_ms", sa.Integer, nullable=False),
        sa.Column("end_ms", sa.Integer, nullable=False),
        sa.Column("narration", sa.Text, nullable=False),
        sa.Column("caption", sa.Text, nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("material", sa.String(255), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text, nullable=False, server_default=""),
        sa.Column("model_path", sa.String(160), nullable=False, server_default=""),
        sa.Column("clip_seconds", sa.Integer, nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.String(20), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("request_id", sa.String(100)),
        sa.Column("submit_key", sa.String(64)),
        sa.Column("error_code", sa.String(40)),
        sa.Column("message", sa.String(300), nullable=False, server_default=""),
        sa.Column("clip_name", sa.String(100)),
        sa.Column("clip_meta", sa.JSON),
        sa.Column("reviewed", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("submitted_at", sa.DateTime),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("plan_id", "position"),
    )
    op.create_table(
        "video_ai_usage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plan_id", sa.Integer, sa.ForeignKey("ai_video_plans.id"), nullable=False),
        sa.Column("scene_id", sa.Integer, sa.ForeignKey("ai_video_scenes.id"), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("model_path", sa.String(160), nullable=False),
        sa.Column("seconds", sa.Integer, nullable=False),
        sa.Column("estimated_cost", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("request_id", sa.String(100)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("scene_id", "attempt"),
    )
    op.create_index("ix_video_ai_usage_created_at", "video_ai_usage", ["created_at"])
    op.add_column("video_projects", sa.Column("ai_plan_id", sa.Integer))
    op.add_column("video_scenes", sa.Column("clip_name", sa.String(100)))
    op.add_column(
        "video_scenes", sa.Column("ai_generated", sa.Boolean, nullable=False, server_default="0")
    )


def downgrade() -> None:
    # Plain columns (no index, key or constraint): SQLite 3.35+ drops them in place, as 0008/0009 do.
    # batch_alter_table would recreate the tables, which under PRAGMA foreign_keys=ON deletes the
    # rows that reference them (audio/subtitle tracks, render jobs) or fails outright.
    op.drop_column("video_scenes", "ai_generated")
    op.drop_column("video_scenes", "clip_name")
    op.drop_column("video_projects", "ai_plan_id")
    op.drop_index("ix_video_ai_usage_created_at", table_name="video_ai_usage")
    op.drop_table("video_ai_usage")
    op.drop_table("ai_video_scenes")
    op.drop_table("ai_video_plans")
    op.drop_table("video_ai_models")
