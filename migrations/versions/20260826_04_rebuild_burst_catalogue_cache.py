"""Rebuild the burst catalogue cache after bounding event_key.

`event_key` used to embed the full station list, so events seen by many
stations exceeded the 220-character column on PostgreSQL and aborted the whole
month's ingestion. The key now ends in a digest of the station list instead,
which changes the key of every stored event.

Both tables are derived caches rebuilt from the upstream monthly lists, so the
rows are cleared rather than rewritten: dropping the `catalog_months` markers
makes the next request re-ingest each month under the new key format. Without
this, rows written with the old keys would be re-inserted as duplicates.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260826_04"
down_revision = "20260728_03"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("DELETE FROM burst_events"))
    op.execute(sa.text("DELETE FROM catalog_months"))


def downgrade():
    # The previous key format is unbounded and cannot be restored from the
    # stored rows; clearing the cache again lets it re-ingest.
    op.execute(sa.text("DELETE FROM burst_events"))
    op.execute(sa.text("DELETE FROM catalog_months"))
