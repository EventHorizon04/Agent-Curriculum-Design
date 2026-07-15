"""intake mko2 fields

Revision ID: a845ef6ab4f6
Revises: d41f7a92c3b8
Create Date: 2026-07-15 21:56:26.896786

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a845ef6ab4f6'
down_revision: Union[str, None] = 'd41f7a92c3b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("programs", sa.Column("mission_th", sa.Text(), nullable=False, server_default=""))
    op.add_column("programs", sa.Column("philosophy_th", sa.Text(), nullable=False, server_default=""))
    op.add_column("programs", sa.Column("program_goals_th", JSONB(), nullable=False, server_default="[]"))
    op.add_column("programs", sa.Column("institutional_identity_th", sa.Text(), nullable=True))
    # drop temporary server defaults — application always provides these values
    op.alter_column("programs", "mission_th", server_default=None)
    op.alter_column("programs", "philosophy_th", server_default=None)
    op.alter_column("programs", "program_goals_th", server_default=None)


def downgrade() -> None:
    op.drop_column("programs", "institutional_identity_th")
    op.drop_column("programs", "program_goals_th")
    op.drop_column("programs", "philosophy_th")
    op.drop_column("programs", "mission_th")
