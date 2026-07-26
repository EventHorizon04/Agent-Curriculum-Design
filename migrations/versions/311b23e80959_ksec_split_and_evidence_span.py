"""ksec K/GS/SS/C/E split, evidence_span_th, required bloom_level

Revision ID: 311b23e80959
Revises: 4f083b3c2d95
Create Date: 2026-07-26 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '311b23e80959'
down_revision: Union[str, None] = '4f083b3c2d95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Destructive by design: pre-existing skills have no evidence_span_th and
    # carry the old 4-value tag, so any program past Stage 2 must re-run skill
    # extraction. Recorded in the design spec; the project has no production data.
    op.execute("DELETE FROM skills")
    op.drop_column("skills", "skill_type")
    op.drop_column("skills", "is_subject_specific")
    op.add_column("skills", sa.Column("evidence_span_th", sa.Text(), nullable=False,
                                      server_default=""))
    op.alter_column("skills", "ksec_category", type_=sa.String(2), existing_type=sa.String(1),
                    nullable=False)
    op.alter_column("skills", "bloom_level", type_=sa.String(20), existing_type=sa.String(20),
                    nullable=False)


def downgrade() -> None:
    op.alter_column("skills", "bloom_level", type_=sa.String(20), existing_type=sa.String(20),
                    nullable=True)
    op.alter_column("skills", "ksec_category", type_=sa.String(1), existing_type=sa.String(2),
                    nullable=False)
    op.drop_column("skills", "evidence_span_th")
    op.add_column("skills", sa.Column("is_subject_specific", sa.Boolean(), nullable=False,
                                      server_default=sa.true()))
    op.add_column("skills", sa.Column("skill_type", sa.String(20), nullable=False,
                                      server_default="knowledge"))
