"""superseded_plos.note_th

Revision ID: e1a5b6c7d849
Revises: d9f4a5b6c738
Create Date: 2026-11-17 10:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e1a5b6c7d849'
down_revision: Union[str, None] = 'd9f4a5b6c738'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("superseded_plos", sa.Column("note_th", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("superseded_plos", "note_th")
