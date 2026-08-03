"""stakeholder classification redesign: skill-level classes, new taxonomy, KSEC collapse

Revision ID: b7c4e1a9f052
Revises: 8b207d0426c3
Create Date: 2026-08-02 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'b7c4e1a9f052'
down_revision: Union[str, None] = '8b207d0426c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Deleted stakeholder types, mapped to their nearest surviving equivalent.
# Not cosmetic: Need.stakeholder_coverage validates its keys against the enum,
# so one surviving row breaks GET /evidence/ for the entire program.
STAKEHOLDER_TYPE_BACKFILL = {
    "accreditation_body": "professional_council",
    "university": "institutional_direction",
    "subject_benchmark": "expert",
    "peer_program": "partner_institution",
}

KSEC_BACKFILL = {"SS": "S", "GS": "S"}


def upgrade() -> None:
    op.add_column("skills", sa.Column("source_stakeholder_type", sa.String(50),
                                      nullable=False, server_default="employer"))
    op.add_column("skills", sa.Column("classification", sa.String(20),
                                      nullable=False, server_default="unclassified"))
    op.add_column("skills", sa.Column("is_field_relevant", sa.Boolean(),
                                      nullable=False, server_default=sa.true()))
    op.add_column("needs", sa.Column("source_stakeholder_types", JSONB(),
                                     nullable=False, server_default="[]"))

    op.drop_column("plos", "is_subject_specific")
    op.drop_column("plos", "classification")
    op.drop_column("plos", "classification_method")
    op.drop_column("plos", "classification_rationale_th")

    for old, new in STAKEHOLDER_TYPE_BACKFILL.items():
        op.execute(
            sa.text("UPDATE evidence SET stakeholder_type = :new WHERE stakeholder_type = :old")
            .bindparams(new=new, old=old)
        )

    # Evidence classes collapse to requirement/general. `requirement` rows keep
    # their value; everything else — including the old want/need/unclassified —
    # becomes general, and the skill-level pass re-derives the rest.
    op.execute("UPDATE evidence SET classification = 'general' WHERE classification <> 'requirement'")

    for old, new in KSEC_BACKFILL.items():
        for table in ("skills", "needs"):
            op.execute(
                sa.text(f"UPDATE {table} SET ksec_category = :new WHERE ksec_category = :old")
                .bindparams(new=new, old=old)
            )

    # Existing skills predate source_stakeholder_type; fill it from their evidence
    # rather than leaving every row on the 'employer' server default.
    op.execute(
        "UPDATE skills SET source_stakeholder_type = evidence.stakeholder_type "
        "FROM evidence WHERE skills.source_evidence_id = evidence.evidence_id"
    )


def downgrade() -> None:
    op.add_column("plos", sa.Column("classification_rationale_th", sa.Text(), nullable=True))
    op.add_column("plos", sa.Column("classification_method", sa.String(20), nullable=True))
    op.add_column("plos", sa.Column("classification", sa.String(20), nullable=True))
    op.add_column("plos", sa.Column("is_subject_specific", sa.Boolean(),
                                    nullable=False, server_default=sa.true()))
    op.drop_column("needs", "source_stakeholder_types")
    op.drop_column("skills", "is_field_relevant")
    op.drop_column("skills", "classification")
    op.drop_column("skills", "source_stakeholder_type")
    # The old taxonomy and the SS/GS split are not restorable — the information
    # that distinguished them is gone. Rows keep their new values.
