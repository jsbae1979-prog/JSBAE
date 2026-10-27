"""Keep collection visibility and reversible workspace removal independent of history."""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("news_list_states",
                    sa.Column("article_id", sa.Integer(), sa.ForeignKey("news_articles.id"), primary_key=True),
                    sa.Column("hidden", sa.Boolean(), nullable=False),
                    sa.Column("used", sa.Boolean(), nullable=False))
    op.create_table("workspace_removals",
                    sa.Column("key", sa.String(80), primary_key=True),
                    sa.Column("detail", sa.JSON(), nullable=False),
                    sa.Column("created_at", sa.DateTime(), nullable=False))


def downgrade() -> None:
    op.drop_table("workspace_removals")
    op.drop_table("news_list_states")
