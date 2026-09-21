"""Need.rationale_th: why one skill group is one demand

Revision ID: c7e2f81a4b93
Revises: b41d7e2c8a90
Create Date: 2026-09-18 00:00:00.000000

No cache cost. The field is asked for by build_summarize_need_prompt, which goes
through complete_need_combination (named complete_light when this landed) and is
the one LLM call in this pipeline that never touches llm_cache — only skill_extraction and llm_clustering do. Adding a field
to _NeedStatement therefore invalidates nothing, which is why this could land on
its own rather than waiting for the bundled prompt change.

The column is NOT NULL, and pre-existing rows are backfilled rather than left
open. "No reason recorded" is then a sentence a designer reads on the card,
instead of a NULL every consumer has to branch on.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c7e2f81a4b93'
down_revision: Union[str, None] = 'b41d7e2c8a90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# What a Need written before this column says about itself.
#
# Derived from the row and nothing else — the member count and the KSEC tag are
# both already on `needs`, so the sentence is true of every row it lands on and
# needs no join. That is the whole design constraint: the honest thing to write
# under a heading that reads "why these skills are one demand" is that nobody
# recorded a reason, plus the facts the row does carry. Composing a plausible
# reason out of the member skill names would put an explanation no model ever
# gave underneath a Need, in the one field a reader will take as the
# justification for it — the same shape as a source_evidence_ids trail that
# passes its validator and lies.
#
# The [สร้างย้อนหลัง] marker is what makes it self-identifying, following
# _REVIEW_MARKER_TH in need_combination: a bracketed Thai marker at the head of
# the string is how this codebase already says "a human has to look at this".
#
# Module-level so tests import it rather than re-typing the SQL, as
# BACKFILL_NEED_COUNTS (a3f8d61e04c7) and STAKEHOLDER_TYPE_BACKFILL
# (b7c4e1a9f052) are. member_skill_ids has been JSONB since aa1e44fd1a46.
BACKFILL_NEED_RATIONALE = """
UPDATE needs
   SET rationale_th = '[สร้างย้อนหลัง] Need นี้รวมจากทักษะ '
                      || jsonb_array_length(member_skill_ids)
                      || ' รายการในหมวด ' || ksec_category
                      || ' — ระบบยังไม่ได้เก็บเหตุผลตอนที่สร้าง'
 WHERE rationale_th = ''
"""


def upgrade() -> None:
    # Added with the same empty server_default the model carries, so the column
    # exists and is NOT NULL from the first statement: an INSERT racing this
    # migration gets '' rather than an error, and the UPDATE below then replaces
    # every '' with the backfilled sentence.
    op.add_column(
        "needs",
        sa.Column("rationale_th", sa.Text(), nullable=False, server_default=""),
    )
    op.execute(BACKFILL_NEED_RATIONALE)


def downgrade() -> None:
    op.drop_column("needs", "rationale_th")
