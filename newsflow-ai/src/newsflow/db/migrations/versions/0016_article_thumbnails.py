"""Add source-provided preview metadata without altering existing news or media."""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_thumbnails",
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("news_articles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("source_article_url", sa.String(2048), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("article_thumbnails")
