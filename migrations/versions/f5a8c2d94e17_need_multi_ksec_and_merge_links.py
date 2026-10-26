"""needs: several KSEC tags per Need, and merge links

`needs.ksec_category` (one tag) becomes `needs.ksec_categories` (a JSONB list),
backfilled as a one-element array. A Need merged from same-purpose Needs of
different tags carries the union. Merge links ride on the same table: a merged
Need lists its originals in `merged_from`, each original points back through
`merged_into` and is hidden from active reads until a split clears it.
`top_skill_ids` keeps the merged Need's most-demanded members for display.

Revision ID: f5a8c2d94e17
Revises: d1e2f3a4b5c6
Create Date: 2026-10-26 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f5a8c2d94e17'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "needs",
        sa.Column("ksec_categories", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute("UPDATE needs SET ksec_categories = jsonb_build_array(ksec_category)")
    op.alter_column("needs", "ksec_categories", nullable=False)
    op.drop_column("needs", "ksec_category")
    for name in ("top_skill_ids", "merged_from"):
        op.add_column(
            "needs",
            sa.Column(
                name,
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            ),
        )
    op.add_column("needs", sa.Column("merged_into", sa.String(), nullable=True))
    op.add_column(
        "needs",
        sa.Column("merge_reason_th", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("needs", "merge_reason_th")
    op.drop_column("needs", "merged_into")
    op.drop_column("needs", "merged_from")
    op.drop_column("needs", "top_skill_ids")
    op.add_column("needs", sa.Column("ksec_category", sa.String(length=2), nullable=True))
    # A merged Need's extra tags are lost: the old schema holds one.
    op.execute("UPDATE needs SET ksec_category = ksec_categories->>0")
    op.alter_column("needs", "ksec_category", nullable=False)
    op.drop_column("needs", "ksec_categories")
