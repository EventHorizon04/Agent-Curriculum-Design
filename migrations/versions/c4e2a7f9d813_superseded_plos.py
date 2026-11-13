"""superseded_plos: history of PLOs a designer's merge replaced

The live `plos` table is keyed (program_id, plo_id) and a merge reuses the
lowest freed plo_id, so the replaced outcomes are kept here as JSON snapshots.

Revision ID: c4e2a7f9d813
Revises: b8d4f6a1c935
Create Date: 2026-11-03 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c4e2a7f9d813'
down_revision: Union[str, None] = 'b8d4f6a1c935'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "superseded_plos",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("plo_id", sa.String(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("superseded_by", sa.String(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.program_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_superseded_plos_program_id", "superseded_plos", ["program_id"])


def downgrade() -> None:
    op.drop_index("ix_superseded_plos_program_id", table_name="superseded_plos")
    op.drop_table("superseded_plos")
