"""Re-derive evidence.classification from stakeholder_type

Revision ID: a2f6b14c9e73
Revises: c7e2f81a4b93
Create Date: 2026-09-27 00:00:00.000000

`POST /evidence/` stored the `classification` the client sent, and the field
defaults to "general" on StakeholderEvidence, so every item saved through the
form landed as `general` whoever was speaking. `classify_evidence_type` says
PROFESSIONAL_COUNCIL and INSTITUTIONAL_DIRECTION are `requirement`; the route
now calls it, and these rows were written before it did.

This is not cosmetic. A programme with no `requirement` evidence produces no
skill classified `requirement`, which makes `is_optional_group`
(`want > requirement + need`) true of nearly every group; `MAX_CORE_PLOS` bounds
only the core series, so such a programme has no PLO ceiling at all. The stored
demo run: 13 of 14 Needs optional, 12 optional PLOs, zero core ones.

The rule is a pure function of a column on the same table, so the backfill is one
UPDATE and needs no join and no model import — and rewriting it here rather than
asking the designer to re-run GET /classify-stream is the point, since needing to
know about that step is what let the wrong value persist.

Downgrade sets the affected rows back to 'general' rather than to whatever they
held before, because what they held before is exactly what is being corrected and
was not recorded anywhere. That is lossless in practice: 'general' is the value
the buggy path wrote, and the classifier reproduces the right one on demand.

Skills and Needs are NOT touched. `classification` on a skill is decided by
`classify_skills` over the whole corpus at extraction time, so the way to carry
this correction downstream is to re-run extraction — an LLM cost this migration
has no business spending, and a decision for whoever runs it.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = 'a2f6b14c9e73'
down_revision: Union[str, None] = 'c7e2f81a4b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The two types are written out in the SQL rather than imported from
# models.REQUIREMENT_TYPES: a migration runs against whatever the code looked
# like at this revision, and importing the live frozenset would make an old
# database's upgrade depend on today's membership.


def upgrade() -> None:
    op.execute(
        """
        UPDATE evidence
        SET classification = 'requirement'
        WHERE stakeholder_type IN ('professional_council', 'institutional_direction')
          AND classification <> 'requirement'
        """
    )
    op.execute(
        """
        UPDATE evidence
        SET classification = 'general'
        WHERE stakeholder_type NOT IN ('professional_council', 'institutional_direction')
          AND classification <> 'general'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE evidence
        SET classification = 'general'
        WHERE stakeholder_type IN ('professional_council', 'institutional_direction')
        """
    )
