"""plo agentic fields

Revision ID: 9b0b455a0a3d
Revises: c29520094a26
Create Date: 2026-07-13 17:27:35.822660

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9b0b455a0a3d'
down_revision: Union[str, None] = 'c29520094a26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clusters", sa.Column("bloom_level", sa.String(20), nullable=True))
    op.add_column("clusters", sa.Column("krathwohl_level", sa.String(20), nullable=True))
    op.add_column("clusters", sa.Column("is_optional", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("clusters", sa.Column("classification_coverage", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("plos", sa.Column("smart_retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("plos", sa.Column("smart_escalated", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("plos", sa.Column("soft_flags", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.add_column("plos", sa.Column("is_optional", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_table("ylos")


def downgrade() -> None:
    op.create_table(
        "ylos",
        sa.Column("ylo_id", sa.String(), primary_key=True),
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.program_id")),
        sa.Column("parent_plo_id", sa.String(), sa.ForeignKey("plos.plo_id")),
        sa.Column("year", sa.Integer()),
        sa.Column("statement_th", sa.Text()),
        sa.Column("statement_en", sa.Text(), nullable=True),
        sa.Column("bloom_level", sa.String(20), nullable=True),
        sa.Column("krathwohl_level", sa.String(20), nullable=True),
        sa.Column("action_verb_th", sa.Text()),
        sa.Column("smart_check", postgresql.JSONB()),
        sa.Column("rationale_th", sa.Text()),
        sa.Column("version", sa.Integer(), server_default="1"),
    )
    for col in ("is_optional", "soft_flags", "smart_escalated", "smart_retry_count"):
        op.drop_column("plos", col)
    for col in ("classification_coverage", "is_optional", "krathwohl_level", "bloom_level"):
        op.drop_column("clusters", col)
