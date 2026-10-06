"""programs.copied_from: which program a copy was made from

Revision ID: c0f1e2d3a4b5
Revises: 117059107855
Create Date: 2026-10-06 00:00:00.000000

Nullable and not a foreign key: every existing program is an original, and
deleting a source must leave its copies alone. See
docs/superpowers/specs/2026-10-06-run-comparison-design.md.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0f1e2d3a4b5"
down_revision: str | None = "117059107855"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("programs", sa.Column("copied_from", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("programs", "copied_from")
