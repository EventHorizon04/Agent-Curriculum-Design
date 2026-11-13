"""plo_feedback_actions: trail of what the PLO review sent back; superseded_plos.cause

Revision ID: d7b3e5c1a420
Revises: c4e2a7f9d813
Create Date: 2026-11-03 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd7b3e5c1a420'
down_revision: Union[str, None] = 'c4e2a7f9d813'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("superseded_plos", sa.Column("cause", sa.String(), nullable=True))
    op.create_table(
        "plo_feedback_actions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("review_created_at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("plo_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("need_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("finding_reason_th", sa.Text(), nullable=False),
        sa.Column("instruction_th", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("outcome_reason_th", sa.Text(), nullable=False),
        sa.Column("result_plo_id", sa.String(), nullable=True),
        sa.Column("result_statement_th", sa.Text(), nullable=True),
        sa.Column("result_bloom_level", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.program_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_plo_feedback_actions_program_id", "plo_feedback_actions", ["program_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_plo_feedback_actions_program_id", table_name="plo_feedback_actions")
    op.drop_table("plo_feedback_actions")
    op.drop_column("superseded_plos", "cause")
