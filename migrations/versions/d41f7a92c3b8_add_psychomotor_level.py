"""add psychomotor_level to clusters and plos

Revision ID: d41f7a92c3b8
Revises: 9b0b455a0a3d
Create Date: 2026-07-14 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd41f7a92c3b8'
down_revision: Union[str, None] = '9b0b455a0a3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clusters", sa.Column("psychomotor_level", sa.String(20), nullable=True))
    op.add_column("plos", sa.Column("psychomotor_level", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("plos", "psychomotor_level")
    op.drop_column("clusters", "psychomotor_level")
