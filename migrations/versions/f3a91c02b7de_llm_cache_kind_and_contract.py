"""rename llm_extraction_cache to llm_cache, add kind and contract

Revision ID: f3a91c02b7de
Revises: e1a7c93b5d02
Create Date: 2026-08-30 14:20:00.000000

The table is a cache, so the upgrade empties it rather than backfilling. Both
new columns are NOT NULL and neither can be derived from an existing row: the
kind that wrote it is not recorded anywhere, and the contract fingerprint lives
only inside the primary key's hash. Guessing either would hand the sweep a
column it cannot trust.

Emptying costs a re-extraction and a re-clustering on the next run and loses
nothing else. In practice it costs less than that: the model name is part of
every key, so any row predating the current provider split is already
unreachable.

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3a91c02b7de'
down_revision: Union[str, None] = 'e1a7c93b5d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table('llm_extraction_cache', 'llm_cache')
    # Before the NOT NULL columns land, not after: an empty table takes them
    # without a server_default that would then have to be dropped again.
    op.execute('DELETE FROM llm_cache')
    op.add_column('llm_cache', sa.Column('kind', sa.String(length=32), nullable=False))
    op.add_column('llm_cache', sa.Column('contract', sa.String(length=64), nullable=False))


def downgrade() -> None:
    # Same reasoning in reverse: rows written after the upgrade carry a kind the
    # old schema has nowhere to put, and the old code would replay clustering
    # payloads through the extraction path on a hash collision.
    op.execute('DELETE FROM llm_cache')
    op.drop_column('llm_cache', 'contract')
    op.drop_column('llm_cache', 'kind')
    op.rename_table('llm_cache', 'llm_extraction_cache')
