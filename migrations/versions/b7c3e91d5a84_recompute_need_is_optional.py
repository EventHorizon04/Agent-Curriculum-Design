"""Need.is_optional: recompute from evidence count instead of member classes

Revision ID: b7c3e91d5a84
Revises: a2f6b14c9e73
Create Date: 2026-09-29 00:00:00.000000

`is_optional_group` used to read `want > requirement + need` over a group's member
classifications. A member is `need` only when its own skill *name* was extracted
from more than one evidence item, and on the stored run all 91 normalised names
came from exactly one each — so `need` was zero, the only way to be core was to
carry a `requirement`, and for a programme with no professional council that comes
from INSTITUTIONAL_DIRECTION alone, which the scope guard then drops for not being
a graduate capability. Core finished at 1 against a floor of 6.

Stored rows are recomputed rather than left alone, which is the opposite of what
the scope-counter migration did, and for the opposite reason. There, an absent
counter meant nobody had asked and the row had to read exactly as it read before
the guard existed. Here the stored value is an answer to the old question, the
columns that answer the new one are both already on the row, and immutable rule 6
makes the 6-10 band a property of the **stored set** — `POST /plos/from-needs`
checks against it. A program whose Needs were written last week would otherwise be
judged against a core count the current code would never produce, and the only way
back would be re-running need_combination and paying for every sentence again.

Reversible without loss in either direction: both rules are computed from
`classification_coverage` and `source_evidence_ids`, and this migration touches
neither. Downgrade restores the old rule rather than a saved copy of the old
values, which is the same thing here and does not need a column to hold them.

No LLM cost. `is_optional` reaches no prompt and is in no cache key.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "b7c3e91d5a84"
down_revision: Union[str, None] = "a2f6b14c9e73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors is_optional_group in stages/demand.py. A mandate wins outright; without
# one, a group asked for by a single evidence item is supplementary.
_NEW_RULE = """
    UPDATE needs
    SET is_optional = (
        COALESCE((classification_coverage ->> 'requirement')::int, 0) = 0
        AND jsonb_array_length(source_evidence_ids) <= 1
    )
"""

# The rule this replaced, so a downgrade lands on the behaviour of the code it is
# downgrading to rather than on whatever this migration happened to write.
_OLD_RULE = """
    UPDATE needs
    SET is_optional = (
        COALESCE((classification_coverage ->> 'want')::int, 0)
        > COALESCE((classification_coverage ->> 'requirement')::int, 0)
          + COALESCE((classification_coverage ->> 'need')::int, 0)
    )
"""


def upgrade() -> None:
    op.execute(_NEW_RULE)


def downgrade() -> None:
    op.execute(_OLD_RULE)
