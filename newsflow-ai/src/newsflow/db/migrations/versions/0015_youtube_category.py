"""Preserve legacy news category; allow per-draft YouTube category selection."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publish_drafts", sa.Column("youtube_category_id", sa.String(3), nullable=False,
                                            server_default="25"))


def downgrade() -> None:
    op.drop_column("publish_drafts", "youtube_category_id")
