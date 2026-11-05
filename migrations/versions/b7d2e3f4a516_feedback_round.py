"""plo_feedback_actions.round: which send-back loop round wrote the row

Revision ID: b7d2e3f4a516
Revises: a6c1d2e3f405
Create Date: 2026-11-05 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7d2e3f4a516'
down_revision: Union[str, None] = 'a6c1d2e3f405'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plo_feedback_actions",
        sa.Column("round", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("plo_feedback_actions", "round")
