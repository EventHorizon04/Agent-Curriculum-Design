"""jobs: background stage runs, one row per run

Revision ID: d1e2f3a4b5c6
Revises: c0f1e2d3a4b5
Create Date: 2026-10-08 00:00:00.000000

A new table, nothing to backfill. See
docs/superpowers/specs/2026-10-08-background-jobs-design.md.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c0f1e2d3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("program_id", sa.String(), sa.ForeignKey("programs.program_id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_th", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("job_id", name="jobs_pkey"),
    )
    op.create_index("ix_jobs_program_status", "jobs", ["program_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_program_status", table_name="jobs")
    op.drop_table("jobs")
