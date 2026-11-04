"""Owner-scoped Meta connections and per-target publication journal."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meta_accounts",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("owner", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("app_id", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("page_id", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("label", sa.String(length=200), primary_key=False, nullable=False),
        sa.Column("instagram_id", sa.String(length=40), primary_key=False, nullable=True),
        sa.Column("instagram_name", sa.String(length=100), primary_key=False, nullable=True),
        sa.Column("scopes", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("tasks", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("state", sa.String(length=30), primary_key=False, nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("user_expires_at", sa.DateTime(), primary_key=False, nullable=False),
        sa.Column("page_expires_at", sa.DateTime(), primary_key=False, nullable=True),
        sa.Column("data_expires_at", sa.DateTime(), primary_key=False, nullable=False),
        sa.Column("user_ref", sa.String(length=32), primary_key=False, nullable=True),
        sa.Column("page_ref", sa.String(length=32), primary_key=False, nullable=True),
        sa.Column("identity", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(), primary_key=False, nullable=False),
        sa.UniqueConstraint("owner", "app_id", "page_id"),
    )
    op.create_index("ix_meta_accounts_owner", "meta_accounts", ["owner"])
    op.create_table(
        "meta_publications",
        sa.Column("id", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("owner", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("connection_id", sa.String(length=32), primary_key=False, nullable=False),
        sa.Column("connection_revision", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("target_id", sa.String(length=40), primary_key=False, nullable=False),
        sa.Column("platform", sa.String(length=20), primary_key=False, nullable=False),
        sa.Column("content_id", sa.String(length=100), primary_key=False, nullable=False),
        sa.Column("media_sha256", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("media_kind", sa.String(length=10), primary_key=False, nullable=False),
        sa.Column("caption", sa.Text(), primary_key=False, nullable=False),
        sa.Column("fingerprint", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("state", sa.String(length=30), primary_key=False, nullable=False),
        sa.Column("remote_id", sa.String(length=100), primary_key=False, nullable=True),
        sa.Column("container_id", sa.String(length=100), primary_key=False, nullable=True),
        sa.Column("error_code", sa.String(length=30), primary_key=False, nullable=True),
        sa.Column("created_at", sa.DateTime(), primary_key=False, nullable=False),
        sa.Column("updated_at", sa.DateTime(), primary_key=False, nullable=False),
        sa.Column("published_at", sa.DateTime(), primary_key=False, nullable=True),
        sa.UniqueConstraint("owner", "connection_id", "platform", "fingerprint"),
    )
    op.create_index("ix_meta_publications_owner", "meta_publications", ["owner"])


def downgrade():
    op.drop_table("meta_publications")
    op.drop_table("meta_accounts")
