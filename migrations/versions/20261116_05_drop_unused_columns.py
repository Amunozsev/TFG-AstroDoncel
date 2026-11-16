"""Drop storage that the application never reads.

`fits_files` was written on every FITS open but never queried, `burst_events.score`
was always null and `stations.coord_source` became redundant once every stored
coordinate comes from a FITS header.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261116_05"
down_revision = "20260826_04"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.drop_index("ix_fits_files_station", table_name="fits_files")
    op.drop_index("ix_fits_files_observed_at", table_name="fits_files")
    op.drop_index("ix_fits_files_focus_code", table_name="fits_files")
    op.drop_index("ix_fits_files_filename", table_name="fits_files")
    op.drop_table("fits_files")
    with op.batch_alter_table("burst_events") as batch:
        batch.drop_column("score")
    with op.batch_alter_table("stations") as batch:
        batch.drop_column("coord_source")


def downgrade():
    with op.batch_alter_table("stations") as batch:
        batch.add_column(sa.Column("coord_source", sa.String(length=20), nullable=True))
    with op.batch_alter_table("burst_events") as batch:
        batch.add_column(sa.Column("score", sa.Float(), nullable=True))
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
