"""add_plo_classification

Revision ID: c29520094a26
Revises: 331ce5b16619
Create Date: 2026-06-15 14:27:50.449457

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c29520094a26'
down_revision: Union[str, None] = '331ce5b16619'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('plos', sa.Column('classification', sa.String(length=20), nullable=True))
    op.add_column('plos', sa.Column('classification_method', sa.String(length=20), nullable=True))
    op.add_column('plos', sa.Column('classification_rationale_th', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('plos', 'classification_rationale_th')
    op.drop_column('plos', 'classification_method')
    op.drop_column('plos', 'classification')
