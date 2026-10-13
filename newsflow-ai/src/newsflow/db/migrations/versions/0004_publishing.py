"""Additive Phase 4A publishing foundation (no token or publication success columns)."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("account_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("credential_ref", sa.String(100)),
        sa.Column("api_ready", sa.Boolean, nullable=False),
        sa.Column("connected_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "publish_drafts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("render_job_id", sa.Integer, sa.ForeignKey("render_jobs.id"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("hashtags", sa.JSON, nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("platform_accounts.id")),
        sa.Column("sources", sa.JSON, nullable=False),
        sa.Column("media_sha256", sa.String(64), nullable=False),
        *[
            sa.Column(n, sa.Boolean, nullable=False)
            for n in ("content_reviewed", "copyright_confirmed", "sources_confirmed")
        ],
        sa.Column("ai_disclosure", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "publish_validations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("draft_id", sa.Integer, sa.ForeignKey("publish_drafts.id"), nullable=False),
        sa.Column("draft_revision", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("results", sa.JSON, nullable=False),
        sa.Column("media_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "publish_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("draft_id", sa.Integer, sa.ForeignKey("publish_drafts.id"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
    )
    op.create_table(
        "publish_attempts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("publish_jobs.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "publish_evidence",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("draft_id", sa.Integer, sa.ForeignKey("publish_drafts.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    for table in (
        "publish_evidence",
        "publish_attempts",
        "publish_jobs",
        "publish_validations",
        "publish_drafts",
        "platform_accounts",
    ):
        op.drop_table(table)
