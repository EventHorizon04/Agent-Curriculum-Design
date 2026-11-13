"""skill_groups: clusters stored between the two agents

Agent 1 (skill extraction and clustering) persists its skill groups so agent 2
(Need writing) can start from them in a separate job. `ordinal` keeps the
stored order, since a group's position is the order the clustering returned.

Revision ID: a7c3e91d5b24
Revises: f5a8c2d94e17
Create Date: 2026-10-26 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a7c3e91d5b24'
down_revision: Union[str, None] = 'f5a8c2d94e17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "skill_groups",
        sa.Column("group_id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("ksec", sa.String(length=2), nullable=False),
        sa.Column("skill_ids", _jsonb(), nullable=False),
        sa.Column("evidence_ids", _jsonb(), nullable=False),
        sa.Column("skill_names", _jsonb(), nullable=False),
        sa.Column("skill_frequencies", _jsonb(), nullable=False),
        sa.Column("bloom_level", sa.String(length=20), nullable=False),
        sa.Column("demand_score", sa.Float(), nullable=False),
        sa.Column("is_optional", sa.Boolean(), nullable=False),
        sa.Column("is_graduate", sa.Boolean(), nullable=False),
        sa.Column("classification_coverage", _jsonb(), nullable=False),
        sa.Column("stakeholder_coverage", _jsonb(), nullable=False),
        sa.Column("stakeholder_types", _jsonb(), nullable=False),
        sa.Column("in_field_skill_count", sa.Integer(), nullable=False),
        sa.Column("graduate_capability_skill_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.program_id"]),
        sa.PrimaryKeyConstraint("group_id"),
    )
    op.create_index("ix_skill_groups_program_id", "skill_groups", ["program_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_groups_program_id", table_name="skill_groups")
    op.drop_table("skill_groups")
