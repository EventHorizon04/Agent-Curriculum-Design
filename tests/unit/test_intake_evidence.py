from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import ProgramMetadata, StakeholderType
from curriculum_agent.stages import intake


def test_every_populated_field_becomes_requirement_evidence(
    program_metadata: ProgramMetadata,
):
    items = intake.build_institutional_evidence(program_metadata)

    assert all(e.stakeholder_type is StakeholderType.INSTITUTIONAL_DIRECTION for e in items)
    assert all(e.classification == "requirement" for e in items)
    assert all(e.raw_text_th.strip() for e in items)


def test_absent_optional_identity_fields_produce_no_row(program_metadata: ProgramMetadata):
    without = program_metadata.model_copy(
        update={"institutional_identity_th": None, "student_identity_th": None}
    )
    suffixes = {
        e.evidence_id.rsplit("-", 1)[-1] for e in intake.build_institutional_evidence(without)
    }

    assert "identity" not in suffixes
    assert "studentidentity" not in suffixes
    assert {"vision", "mission", "philosophy"} <= suffixes


def test_ids_are_deterministic_so_a_re_run_replaces_rather_than_accumulates(
    program_metadata: ProgramMetadata,
):
    """The repository upserts by primary key: an id derived from the program and
    the field name is what stops a second intake run from doubling the rows."""
    edited = program_metadata.model_copy(update={"vision_th": "วิสัยทัศน์ฉบับแก้ไข"})

    first = {e.evidence_id for e in intake.build_institutional_evidence(program_metadata)}
    second = {e.evidence_id for e in intake.build_institutional_evidence(edited)}

    assert first == second


def test_a_whitespace_only_field_produces_no_row(program_metadata: ProgramMetadata):
    blanked = program_metadata.model_copy(update={"institutional_identity_th": "   "})
    texts = [e.raw_text_th for e in intake.build_institutional_evidence(blanked)]

    assert "   " not in texts


async def test_run_persists_the_institutional_evidence(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(intake.ProgramRepository, "upsert", AsyncMock())
    insert = AsyncMock()
    monkeypatch.setattr(intake.EvidenceRepository, "bulk_insert", insert)
    monkeypatch.setattr(intake.EvidenceRepository, "list_by_program", AsyncMock(return_value=[]))

    await intake.run({"metadata": program_metadata.model_dump(mode="json")})

    insert.assert_awaited_once()
    written = insert.await_args.args[0]
    assert all(e.classification == "requirement" for e in written)
