"""plos primary key becomes (program_id, plo_id)

Revision ID: e4b6d19a3f72
Revises: c5a82f3e6b19
Create Date: 2026-10-04 00:00:00.000000

`plo_id` (PLO1..PLOn, OPT1..OPTn) repeats across every program — it was only
ever unique within one program's own synthesis run, never across the table.
With plo_id alone as the primary key, PLORepository.bulk_insert and .replace
upserted via `session.get(PLOTable, plo.plo_id)` and then `setattr`'d every
column including program_id: when a second program's synthesis run produced
its own PLO1, `session.get` found the *first* program's PLO1 row — plo_id was
the only thing it looked at — relabelled it with the second program's
program_id, and overwrote its content. The first program lost that outcome
with no error raised anywhere.

This migration does not and cannot restore what was overwritten. Those rows
were overwritten in place, not deleted, and nothing versions them — a program
that lost PLOs this way has to re-run PLO synthesis.

upgrade: `program_id` IS NOT NULL on `plos` since the initial schema
(aa1e44fd1a46) and nothing since has relaxed it, so the ALTER below is
expected to be a no-op against every deployed database. The guard that
precedes it is belt-and-suspenders against a row this migration has not
seen: it fails with a clear, specific message rather than letting Postgres's
own NOT NULL violation (if one somehow fired) name only a column and a row
count with no context. The single-column PK — `plos_pkey`, Postgres's default
constraint name, since aa1e44fd1a46 gave the `PrimaryKeyConstraint` no
explicit one — is then dropped and replaced by a composite PK on
(program_id, plo_id), kept under the same constraint name.

downgrade: refuses, rather than silently merging or dropping rows, if two
programs now share a plo_id. Collapsing straight back onto a single-column PK
in that state would otherwise fail Postgres's own constraint partway through
the ALTER (leaving the migration half-applied) or require deleting one of the
two colliding rows — this migration deletes nothing. Finding out before the
ALTER starts is the only way to fail cleanly; the fix is to resolve the
collision by hand (rename or remove one program's rows) before downgrading.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4b6d19a3f72"
down_revision: Union[str, None] = "c5a82f3e6b19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Module-level so a test can assert on the guard without running it against a
# database — same approach as BACKFILL_NEED_COUNTS in a3f8d61e04c7.
REFUSE_NULL_PROGRAM_ID = """
DO $$
DECLARE
    bad_count integer;
BEGIN
    SELECT count(*) INTO bad_count FROM plos WHERE program_id IS NULL;
    IF bad_count > 0 THEN
        RAISE EXCEPTION
            'plos: % row(s) have a NULL program_id and cannot take the new '
            '(program_id, plo_id) primary key. This migration will not delete '
            'or guess at rows — fix them by hand, then upgrade again.', bad_count;
    END IF;
END $$;
"""

REFUSE_SHARED_PLO_ID = """
DO $$
DECLARE
    dupe_count integer;
BEGIN
    SELECT count(*) INTO dupe_count FROM (
        SELECT plo_id FROM plos GROUP BY plo_id HAVING count(DISTINCT program_id) > 1
    ) AS dupes;
    IF dupe_count > 0 THEN
        RAISE EXCEPTION
            'plos: % plo_id value(s) are shared by more than one program and '
            'cannot take a single-column primary key on plo_id alone. This '
            'downgrade will not merge or drop rows to make room — resolve the '
            'collision by hand, then downgrade again.', dupe_count;
    END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(REFUSE_NULL_PROGRAM_ID)
    op.alter_column("plos", "program_id", existing_type=sa.String(), nullable=False)
    op.drop_constraint("plos_pkey", "plos", type_="primary")
    op.create_primary_key("plos_pkey", "plos", ["program_id", "plo_id"])


def downgrade() -> None:
    op.execute(REFUSE_SHARED_PLO_ID)
    op.drop_constraint("plos_pkey", "plos", type_="primary")
    op.create_primary_key("plos_pkey", "plos", ["plo_id"])
