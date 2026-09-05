"""PLO scope guard: program scope statement, graduate-capability flag, Need counters

Revision ID: a3f8d61e04c7
Revises: f3a91c02b7de
Create Date: 2026-09-05 00:00:00.000000

Three tables in one revision on purpose. The new response-schema field moves
_EXTRACTION_CONTRACT, so every llm_cache row for kind="extraction" becomes
unreachable the moment this ships and the corpus is re-extracted once. Splitting
this into several deploys would pay that cost twice for no reduction in risk.

Do NOT run `prune_cache --delete` before deploying this. The stale rows are
invisible, not harmful, and they are the only way back if this has to be rolled
back. Sweep them once the new extraction has been accepted.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a3f8d61e04c7'
down_revision: Union[str, None] = 'f3a91c02b7de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COUNT_COLUMNS = ("in_field_skill_count", "graduate_capability_skill_count")

# Every pre-existing Need is treated as though all of its members passed both
# axes. That is not a claim about those skills — nobody ever judged them — it is
# what keeps behaviour identical for programs that predate the guard.
#
# A server_default of 0 would mean the opposite: every stored Need would read as
# "not one member is in-field", and the any rule in Need.is_field_relevant would
# filter every program's whole Need set out of PLO synthesis on the first run
# after deploy, with nobody having asked for it.
#
# Module-level constant so tests can import and assert on it rather than
# re-typing the SQL — same as STAKEHOLDER_TYPE_BACKFILL in b7c4e1a9f052.
# member_skill_ids has been JSONB since aa1e44fd1a46, so one UPDATE does it.
BACKFILL_NEED_COUNTS = """
UPDATE needs
   SET in_field_skill_count = jsonb_array_length(member_skill_ids),
       graduate_capability_skill_count = jsonb_array_length(member_skill_ids)
"""


def upgrade() -> None:
    # Naturally empty for programs created before the intake field existed, and
    # for every program whose designer leaves it blank — nullable, following
    # isced_code (5ccd16b72130).
    op.add_column("programs", sa.Column("scope_th", sa.Text(), nullable=True))

    # server_default true, matching is_field_relevant in b7c4e1a9f052: a skill
    # extracted before the flag existed was never judged against it, and the
    # pipeline has to read it the way it read it yesterday.
    op.add_column(
        "skills",
        sa.Column(
            "is_graduate_capability",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # Nullable first so the backfill has somewhere to write, then NOT NULL. The
    # server_default arrives with the NOT NULL rather than with the column: it is
    # for rows written by code that predates this schema, never for the rows
    # already here, which the UPDATE above is responsible for.
    for column in _COUNT_COLUMNS:
        op.add_column("needs", sa.Column(column, sa.Integer(), nullable=True))
    op.execute(BACKFILL_NEED_COUNTS)
    for column in _COUNT_COLUMNS:
        op.alter_column(
            "needs",
            column,
            existing_type=sa.Integer(),
            nullable=False,
            server_default="0",
        )


def downgrade() -> None:
    for column in _COUNT_COLUMNS:
        op.drop_column("needs", column)
    op.drop_column("skills", "is_graduate_capability")
    op.drop_column("programs", "scope_th")
