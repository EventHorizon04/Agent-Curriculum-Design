"""plo_reviews: the advisory PLO set review, one row per program

Revision ID: 117059107855
Revises: e4b6d19a3f72
Create Date: 2026-10-05 00:00:00.000000

A new table, so nothing to backfill: a program with no row simply has not been
reviewed yet. See docs/superpowers/specs/2026-10-04-plo-set-review-design.md.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "117059107855"
down_revision: Union[str, None] = "e4b6d19a3f72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plo_reviews",
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.program_id"), nullable=False),
        sa.Column("plo_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("review", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("program_id", name="plo_reviews_pkey"),
    )


def downgrade() -> None:
    op.drop_table("plo_reviews")
