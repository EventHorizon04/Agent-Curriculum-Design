"""add bloom_level, ksec_category, importance_score to skills

Revision ID: 4f083b3c2d95
Revises: 5ccd16b72130
Create Date: 2026-07-25 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f083b3c2d95'
down_revision: Union[str, None] = '5ccd16b72130'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("bloom_level", sa.String(20), nullable=True))
    op.add_column(
        "skills",
        sa.Column("ksec_category", sa.String(1), nullable=False, server_default="K"),
    )
    op.add_column(
        "skills",
        sa.Column("importance_score", sa.Float, nullable=False, server_default="0.0"),
    )


def downgrade() -> None:
    op.drop_column("skills", "importance_score")
    op.drop_column("skills", "ksec_category")
    op.drop_column("skills", "bloom_level")
