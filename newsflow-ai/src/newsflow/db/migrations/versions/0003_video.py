"""Additive Phase 3 video production schema."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("draft_id", sa.Integer, sa.ForeignKey("content_drafts.id"), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("duration", sa.Integer, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("sources", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "video_scenes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "project_id", sa.Integer, sa.ForeignKey("video_projects.id", ondelete="CASCADE"), nullable=False
        ),
        *[sa.Column(n, sa.Integer, nullable=False) for n in ("position", "start_ms", "end_ms")],
        sa.Column("narration", sa.Text, nullable=False),
        sa.Column("caption", sa.Text, nullable=False),
        sa.Column("material", sa.String(255), nullable=False),
        sa.UniqueConstraint("project_id", "position"),
    )
    op.create_table(
        "audio_tracks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("video_projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("voice", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
    )
    op.create_table(
        "subtitle_tracks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("video_projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("font_size", sa.Integer, nullable=False),
        sa.Column("position_y", sa.Integer, nullable=False),
        sa.Column("cues", sa.JSON, nullable=False),
    )
    op.create_table(
        "render_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("video_projects.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("progress", sa.Integer, nullable=False),
        sa.Column("output_name", sa.String(100), nullable=False, unique=True),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("metadata_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
    )


def downgrade() -> None:
    for name in ("render_jobs", "subtitle_tracks", "audio_tracks", "video_scenes", "video_projects"):
        op.drop_table(name)
