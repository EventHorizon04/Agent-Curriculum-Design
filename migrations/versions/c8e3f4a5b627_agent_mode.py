"""programs.agent_mode and needs.origin: which pipeline produced them

Revision ID: c8e3f4a5b627
Revises: b7d2e3f4a516
Create Date: 2026-11-14 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c8e3f4a5b627'
down_revision: Union[str, None] = 'b7d2e3f4a516'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "programs",
        sa.Column("agent_mode", sa.String(length=10), nullable=False, server_default="multi"),
    )
    op.add_column(
        "needs",
        sa.Column("origin", sa.String(length=10), nullable=False, server_default="multi"),
    )


def downgrade() -> None:
    op.drop_column("needs", "origin")
    op.drop_column("programs", "agent_mode")
