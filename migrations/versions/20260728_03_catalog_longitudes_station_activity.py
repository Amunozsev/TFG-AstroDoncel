"""Add heliographic longitudes and station activity timestamps."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_03"
down_revision = "20260723_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("burst_events", sa.Column("min_lon", sa.Float(), nullable=True))
    op.add_column("burst_events", sa.Column("mid_lon", sa.Float(), nullable=True))
    op.add_column("burst_events", sa.Column("max_lon", sa.Float(), nullable=True))
    op.add_column("stations", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("stations", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_stations_last_seen_at", "stations", ["last_seen_at"])


def downgrade():
    op.drop_index("ix_stations_last_seen_at", table_name="stations")
    op.drop_column("stations", "last_seen_at")
    op.drop_column("stations", "first_seen_at")
    op.drop_column("burst_events", "max_lon")
    op.drop_column("burst_events", "mid_lon")
    op.drop_column("burst_events", "min_lon")
