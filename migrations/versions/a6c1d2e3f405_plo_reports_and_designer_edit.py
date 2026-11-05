"""plo_reports table and plos.designer_edited_at

Revision ID: a6c1d2e3f405
Revises: e5a9c2f7b318
Create Date: 2026-11-05 10:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a6c1d2e3f405'
down_revision: Union[str, None] = 'e5a9c2f7b318'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plos", sa.Column("designer_edited_at", sa.DateTime(), nullable=True))
    op.create_table(
        "plo_reports",
        sa.Column("program_id", sa.String(), nullable=False),
        sa.Column("plo_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["program_id"], ["programs.program_id"]),
        sa.PrimaryKeyConstraint("program_id"),
    )


def downgrade() -> None:
    op.drop_table("plo_reports")
    op.drop_column("plos", "designer_edited_at")
