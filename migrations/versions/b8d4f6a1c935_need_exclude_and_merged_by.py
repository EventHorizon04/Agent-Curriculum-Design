"""needs: excluded_at and merged_by

`excluded_at` lets the designer take a Need out of the PLO pool without
deleting it; `merged_by` records whether Agent 2 or the designer wrote a merged
Need. Both nullable, so existing rows need no backfill.

Revision ID: b8d4f6a1c935
Revises: a7c3e91d5b24
Create Date: 2026-11-03 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b8d4f6a1c935'
down_revision: Union[str, None] = 'a7c3e91d5b24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("needs", sa.Column("excluded_at", sa.DateTime(), nullable=True))
    op.add_column("needs", sa.Column("merged_by", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("needs", "merged_by")
    op.drop_column("needs", "excluded_at")
