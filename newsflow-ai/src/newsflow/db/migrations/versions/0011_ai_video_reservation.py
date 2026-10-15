"""Phase 5D: pin each AI video reservation to its request resolution and to the approval it was made under.

Additive. A separate revision because 0010 was already published on the Phase 5D branch: data
folders stamped 0010 must still receive these columns.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("video_ai_usage", sa.Column("resolution", sa.String(10), nullable=False, server_default=""))
    op.add_column("video_ai_usage", sa.Column("approval", sa.String(40), nullable=False, server_default=""))


def downgrade() -> None:
    # Plain columns: dropped in place (SQLite 3.35+), as 0008-0010 do.
    op.drop_column("video_ai_usage", "approval")
    op.drop_column("video_ai_usage", "resolution")
