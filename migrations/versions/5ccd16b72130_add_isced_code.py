"""add isced code

Revision ID: 5ccd16b72130
Revises: a845ef6ab4f6
Create Date: 2026-07-16 20:21:00.688633

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5ccd16b72130'
down_revision: Union[str, None] = 'a845ef6ab4f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("programs", sa.Column("isced_code", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("programs", "isced_code")
