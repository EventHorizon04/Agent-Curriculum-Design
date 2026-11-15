"""plos.designer_sent_back_at and plos.designer_send_back_reason_th

Revision ID: d9f4a5b6c738
Revises: c8e3f4a5b627
Create Date: 2026-11-15 10:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd9f4a5b6c738'
down_revision: Union[str, None] = 'c8e3f4a5b627'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plos", sa.Column("designer_sent_back_at", sa.DateTime(), nullable=True))
    op.add_column("plos", sa.Column("designer_send_back_reason_th", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("plos", "designer_send_back_reason_th")
    op.drop_column("plos", "designer_sent_back_at")
