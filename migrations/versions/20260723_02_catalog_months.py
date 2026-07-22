"""Persist official catalogue refresh metadata."""

import sqlalchemy as sa
from alembic import op

revision = "20260723_02"
down_revision = "20260712_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "catalog_months",
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("year_month", sa.String(length=7), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_catalog_months_source", "catalog_months", ["source"])
    op.create_index("ix_catalog_months_year_month", "catalog_months", ["year_month"])


def downgrade():
    op.drop_index("ix_catalog_months_year_month", table_name="catalog_months")
    op.drop_index("ix_catalog_months_source", table_name="catalog_months")
    op.drop_table("catalog_months")
