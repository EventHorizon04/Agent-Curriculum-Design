"""drop the institutional-direction metadata columns

The program's vision, mission, philosophy, and two identity statements now live in
the evidence table as stakeholder_type='institutional_direction' rows. Keeping a
second copy on the program row left two sources of truth with nothing reconciling
them, so the columns go.

No backfill: any program whose statements were previously converted already has the
evidence rows, and this migration does not touch them.

Revision ID: c8d5f2a71b43
Revises: b7c4e1a9f052
Create Date: 2026-08-03 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c8d5f2a71b43'
down_revision: Union[str, None] = 'b7c4e1a9f052'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DROPPED_COLUMNS = (
    "vision_th",
    "mission_th",
    "philosophy_th",
    "institutional_identity_th",
    "student_identity_th",
)


def upgrade() -> None:
    for column in DROPPED_COLUMNS:
        op.drop_column("programs", column)


def downgrade() -> None:
    # Restored nullable: the original NOT NULL content is gone once dropped, and a
    # server_default of "" would fabricate a vision statement rather than admit the
    # loss.
    op.add_column("programs", sa.Column("vision_th", sa.Text(), nullable=True))
    op.add_column("programs", sa.Column("mission_th", sa.Text(), nullable=True))
    op.add_column("programs", sa.Column("philosophy_th", sa.Text(), nullable=True))
    op.add_column(
        "programs", sa.Column("institutional_identity_th", sa.Text(), nullable=True)
    )
    op.add_column("programs", sa.Column("student_identity_th", sa.Text(), nullable=True))
