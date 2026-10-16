"""Opt-in local schedules and durable occurrences. Earlier revisions are unchanged."""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_schedules",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("local_time", sa.String(5), nullable=False),
        sa.Column("weekdays", sa.JSON, nullable=False),
        sa.Column("once_date", sa.String(10)),
        sa.Column("options", sa.JSON, nullable=False),
        sa.Column("fingerprint", sa.String(64), unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("next_run_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_production_schedules_next_run_at", "production_schedules", ["next_run_at"])
    op.create_table(
        "scheduled_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schedule_id", sa.String(32), sa.ForeignKey("production_schedules.id"), nullable=False),
        sa.Column("scheduled_for", sa.DateTime, nullable=False),
        sa.Column("job_id", sa.String(32), unique=True, nullable=False),
        sa.Column("options", sa.JSON, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("schedule_id", "scheduled_for"),
    )
    op.create_index("ix_scheduled_runs_schedule_id", "scheduled_runs", ["schedule_id"])


def downgrade() -> None:
    op.drop_table("scheduled_runs")
    op.drop_table("production_schedules")
