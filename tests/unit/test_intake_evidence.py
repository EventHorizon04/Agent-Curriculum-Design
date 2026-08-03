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


def test_all_five_fields_produce_the_exact_suffix_and_source_name_pinned(
    program_metadata: ProgramMetadata,
):
    """Pins every entry of INSTITUTIONAL_FIELDS, including the two optional identity
    fields the `program_metadata` fixture otherwise leaves unpopulated. Without this,
    a typo in either identity tuple's suffix or Thai source_name fails no test."""
    populated = program_metadata.model_copy(
        update={
            "institutional_identity_th": "อัตลักษณ์สถาบันของมหาวิทยาลัยทดสอบ",
            "student_identity_th": "อัตลักษณ์บัณฑิตของมหาวิทยาลัยทดสอบ",
        }
    )

    pairs = {
        (e.evidence_id.rsplit("-", 1)[-1], e.source_name)
        for e in intake.build_institutional_evidence(populated)
    }

    assert pairs == {
        ("vision", "วิสัยทัศน์"),
        ("mission", "พันธกิจ"),
        ("philosophy", "ปรัชญาหลักสูตร"),
        ("identity", "อัตลักษณ์สถาบัน"),
        ("studentidentity", "อัตลักษณ์บัณฑิต"),
    }


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


async def test_written_rows_reach_state_so_the_load_must_run_after_the_write(
    program_metadata: ProgramMetadata, monkeypatch: pytest.MonkeyPatch
):
    """The brief calls the write-before-load ordering load-bearing: if `run()` ever
    loaded evidence before writing the institutional rows, the vision/mission/philosophy
    rows this test just wrote would be missing from state for the next stage to see.

    `list_by_program`'s side_effect returns whatever `bulk_insert` was last called
    with, so this only produces the vision row in `raw_evidence` if the write already
    happened by the time the load runs — an order-sensitive stand-in for a real
    database read, unlike a constant `return_value=[]`.
    """
    monkeypatch.setattr(intake.ProgramRepository, "upsert", AsyncMock())
    written_holder: list[object] = []

    async def fake_bulk_insert(_self: object, items: object) -> None:
        written_holder.append(items)

    async def fake_list_by_program(_self: object, _program_id: str) -> object:
        return written_holder[-1] if written_holder else []

    monkeypatch.setattr(intake.EvidenceRepository, "bulk_insert", fake_bulk_insert)
    monkeypatch.setattr(intake.EvidenceRepository, "list_by_program", fake_list_by_program)

    state = await intake.run({"metadata": program_metadata.model_dump(mode="json")})

    suffixes = {e["evidence_id"].rsplit("-", 1)[-1] for e in state["raw_evidence"]}
    assert "vision" in suffixes
