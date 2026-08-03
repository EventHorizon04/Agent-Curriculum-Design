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


def _remap_stakeholder_coverage(coverage: dict[str, int]) -> dict[str, int]:
    """Collapse deleted stakeholder_type keys into their replacement.

    A row can legitimately already hold both a deleted key and its
    replacement (e.g. "accreditation_body" and "professional_council"); the
    counts must sum rather than one overwriting the other, since these are
    mention counts and losing one understates the Need's coverage.
    """
    remapped: dict[str, int] = {}
    for key, count in coverage.items():
        new_key = STAKEHOLDER_TYPE_BACKFILL.get(key, key)
        remapped[new_key] = remapped.get(new_key, 0) + count
    return remapped


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

    # needs.stakeholder_coverage is a pre-existing JSONB dict[str, int] written
    # verbatim by need_combination and never re-derived from evidence on read.
    # Need.stakeholder_coverage validates its keys as StakeholderType, so a row
    # whose dict still carries a deleted key raises ValidationError inside
    # NeedRepository.list_by_program — the same failure mode this migration
    # exists to prevent, one table over. Only rows containing a deleted key are
    # rewritten; the remap sums colliding counts rather than overwriting, since
    # a row may already hold both a deleted key and its replacement.
    connection = op.get_bind()
    deleted_keys = tuple(STAKEHOLDER_TYPE_BACKFILL)
    select_stmt = (
        sa.text(
            "SELECT need_id, stakeholder_coverage FROM needs n "
            "WHERE EXISTS ("
            "  SELECT 1 FROM jsonb_object_keys(n.stakeholder_coverage) k "
            "  WHERE k IN :deleted_keys"
            ")"
        )
        .bindparams(sa.bindparam("deleted_keys", expanding=True))
        .columns(need_id=sa.String(), stakeholder_coverage=JSONB())
    )
    rows = connection.execute(select_stmt, {"deleted_keys": deleted_keys}).fetchall()
    for need_id, coverage in rows:
        new_coverage = _remap_stakeholder_coverage(coverage)
        connection.execute(
            sa.text("UPDATE needs SET stakeholder_coverage = :cov WHERE need_id = :id")
            .bindparams(sa.bindparam("cov", type_=JSONB())),
            {"cov": new_coverage, "id": need_id},
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
    # that distinguished them is gone. Rows keep their new values. This also
    # covers needs.stakeholder_coverage: once colliding counts are summed under
    # the replacement key, which portion came from which deleted key is lost.
