"""Frozen initial Phase 1 schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_sources",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False, unique=True),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("news_sources.id"), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("published_at", sa.DateTime),
        sa.Column("collected_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "article_mentions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "article_id", sa.Integer, sa.ForeignKey("news_articles.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("news_sources.id"), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.UniqueConstraint("article_id", "url"),
    )
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime),
        *[
            sa.Column(name, sa.Integer, nullable=False)
            for name in ("added", "duplicates", "succeeded", "failed")
        ],
    )
    op.create_table(
        "article_scores",
        sa.Column(
            "article_id", sa.Integer, sa.ForeignKey("news_articles.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("total", sa.Integer, nullable=False),
        sa.Column("assessed_max", sa.Integer, nullable=False),
        sa.Column("components", sa.JSON, nullable=False),
        sa.Column("scored_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("collection_runs.id")),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("news_sources.id")),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("event", sa.String(50), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("value", sa.String(200), nullable=False),
    )
    op.create_index("ix_articles_date", "news_articles", ["published_at"])
    op.create_index("ix_articles_category", "news_articles", ["category"])


def downgrade() -> None:
    for table in (
        "app_settings",
        "audit_logs",
        "article_scores",
        "collection_runs",
        "article_mentions",
        "news_articles",
        "news_sources",
    ):
        op.drop_table(table)
