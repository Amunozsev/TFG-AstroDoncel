"""Initial persistent catalogue and task schema."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260712_01"
down_revision = None
branch_labels = None
depends_on = None


JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table(
        "stations",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("coord_source", sa.String(length=20), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "fits_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=180), nullable=False),
        sa.Column("station", sa.String(length=80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("focus_code", sa.String(length=20), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("fits_header", JSON_TYPE, nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fits_files_filename", "fits_files", ["filename"], unique=True)
    op.create_index("ix_fits_files_focus_code", "fits_files", ["focus_code"])
    op.create_index("ix_fits_files_observed_at", "fits_files", ["observed_at"])
    op.create_index("ix_fits_files_station", "fits_files", ["station"])
    op.create_table(
        "burst_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("event_key", sa.String(length=220), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("burst_type", sa.String(length=30), nullable=True),
        sa.Column("intensity", sa.Integer(), nullable=True),
        sa.Column("stations", JSON_TYPE, nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("metadata_json", JSON_TYPE, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "event_key", name="uq_burst_source_key"),
    )
    op.create_index("ix_burst_events_burst_type", "burst_events", ["burst_type"])
    op.create_index("ix_burst_events_ended_at", "burst_events", ["ended_at"])
    op.create_index("ix_burst_events_source", "burst_events", ["source"])
    op.create_index("ix_burst_events_started_at", "burst_events", ["started_at"])
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("payload", JSON_TYPE, nullable=False),
        sa.Column("result", JSON_TYPE, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_task_type", "tasks", ["task_type"])
    op.create_table(
        "goes_days",
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("payload", JSON_TYPE, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("date"),
    )


def downgrade():
    op.drop_table("goes_days")
    op.drop_index("ix_tasks_task_type", table_name="tasks")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_burst_events_started_at", table_name="burst_events")
    op.drop_index("ix_burst_events_source", table_name="burst_events")
    op.drop_index("ix_burst_events_ended_at", table_name="burst_events")
    op.drop_index("ix_burst_events_burst_type", table_name="burst_events")
    op.drop_table("burst_events")
    op.drop_index("ix_fits_files_station", table_name="fits_files")
    op.drop_index("ix_fits_files_observed_at", table_name="fits_files")
    op.drop_index("ix_fits_files_focus_code", table_name="fits_files")
    op.drop_index("ix_fits_files_filename", table_name="fits_files")
    op.drop_table("fits_files")
    op.drop_table("stations")
