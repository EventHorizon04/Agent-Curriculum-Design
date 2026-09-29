"""Need.is_optional: a group that is entirely unclassified is optional

Revision ID: c5a82f3e6b19
Revises: b7c3e91d5a84
Create Date: 2026-09-29 00:00:00.000000

The revision before this one moved `is_optional` off the member classifications
and onto the group's evidence count. It left one thing the old rule also got
wrong, which ticket 15 had measured separately and called free to fix: a group
whose members are *all* `unclassified` still takes a core slot.

`unclassified` means the extraction model judged the skill off-field, and the
docstring has always said it counts toward neither side. Under any rule of the
shape "optional unless X" that is not a neutral position — it is a core slot by
default. The old rule gave one because `0 > 0` is false; the new one gave one
whenever the group drew on two evidence items.

Leaving it is not free even though the scope guard drops every such Need before
synthesis, which is why it looks harmless in the PLO counts. Immutable rule 6
makes the 6-10 band a property of the **stored set** and `POST /plos/from-needs`
is checked against it, so the padding lands in the number a designer is judged
against and cannot reach: on the stored programme two of the eleven core Needs
were entirely unclassified and every one of them was guaranteed to be filtered.

Separate from b7c3e91d5a84 rather than folded into it because that revision has
been applied and its message describes the rule it wrote. Both directions
recompute from `classification_coverage` and `source_evidence_ids`, so the
downgrade lands on the behaviour of the code it is downgrading to.

No LLM cost. `is_optional` reaches no prompt and is in no cache key.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c5a82f3e6b19"
down_revision: Union[str, None] = "b7c3e91d5a84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors is_optional_group in stages/demand.py. The middle clause is the one
# this revision adds: a coverage map whose only key is 'unclassified'.
_NEW_RULE = """
    UPDATE needs
    SET is_optional = (
        COALESCE((classification_coverage ->> 'requirement')::int, 0) = 0
        AND (
            (SELECT array_agg(k ORDER BY k)
             FROM jsonb_object_keys(classification_coverage) AS k) = ARRAY['unclassified']
            OR jsonb_array_length(source_evidence_ids) <= 1
        )
    )
"""

_PREVIOUS_RULE = """
    UPDATE needs
    SET is_optional = (
        COALESCE((classification_coverage ->> 'requirement')::int, 0) = 0
        AND jsonb_array_length(source_evidence_ids) <= 1
    )
"""


def upgrade() -> None:
    op.execute(_NEW_RULE)


def downgrade() -> None:
    op.execute(_PREVIOUS_RULE)
