"""PLO becomes cognitive-only and traces to Needs

Revision ID: 8b207d0426c3
Revises: 56a36c42123a
Create Date: 2026-07-26 00:00:02.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '8b207d0426c3'
down_revision: Union[str, None] = '56a36c42123a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing PLOs point at cluster ids that no longer exist after <rev2>, so
    # they cannot be carried over. Programmes re-run synthesis from their Needs.
    op.execute("DELETE FROM plos")
    op.alter_column("plos", "source_cluster_ids", new_column_name="source_need_ids")
    op.drop_column("plos", "domain")
    op.drop_column("plos", "psychomotor_level")
    op.drop_column("plos", "krathwohl_level")
    op.alter_column("plos", "bloom_level", existing_type=sa.String(20), nullable=False,
                    server_default="apply")


def downgrade() -> None:
    op.execute("DELETE FROM plos")
    op.alter_column("plos", "bloom_level", existing_type=sa.String(20), nullable=True,
                    server_default=None)
    op.add_column("plos", sa.Column("krathwohl_level", sa.String(20), nullable=True))
    op.add_column("plos", sa.Column("psychomotor_level", sa.String(20), nullable=True))
    op.add_column("plos", sa.Column("domain", sa.String(20), nullable=False,
                                    server_default="cognitive"))
    op.alter_column("plos", "source_need_ids", new_column_name="source_cluster_ids")
