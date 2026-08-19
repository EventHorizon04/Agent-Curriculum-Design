"""drop needs.sample_quotes_th

need_combination no longer reads evidence. A Need's sentence is written from its
member skills alone, so there is no evidence text in the stage to sample and this
column had nothing left to write to it. The evidence trail is unaffected:
needs.source_evidence_ids still carries it, inherited from the member skills, and
the full text stays in the evidence table for drill-down.

Revision ID: e1a7c93b5d02
Revises: c8d5f2a71b43
Create Date: 2026-08-18 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e1a7c93b5d02'
down_revision: Union[str, None] = 'c8d5f2a71b43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("needs", "sample_quotes_th")


def downgrade() -> None:
    # server_default '[]' rather than a backfill: the quotes are gone with the
    # column, and every stored Need is replaced wholesale on the next run of the
    # stage anyway (need_combination deletes by program before inserting).
    op.add_column(
        "needs",
        sa.Column(
            "sample_quotes_th",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
