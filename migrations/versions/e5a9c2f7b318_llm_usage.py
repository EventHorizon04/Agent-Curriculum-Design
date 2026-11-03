"""llm_usage: one row per provider response (tokens, latency, ok)

Revision ID: e5a9c2f7b318
Revises: d7b3e5c1a420
Create Date: 2026-11-03 15:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e5a9c2f7b318'
down_revision: Union[str, None] = 'd7b3e5c1a420'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("slot", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.program_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_program_id", "llm_usage", ["program_id"])
    op.create_index("ix_llm_usage_job_id", "llm_usage", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_job_id", table_name="llm_usage")
    op.drop_index("ix_llm_usage_program_id", table_name="llm_usage")
    op.drop_table("llm_usage")
