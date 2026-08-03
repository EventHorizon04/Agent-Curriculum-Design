"""The designer note reaches the two prompts that author prose, and nothing else."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    ProgramMetadata,
)
from curriculum_agent.prompts.designer_note import (
    NOTE_HEADER_TH,
    NOTE_POLICY_TH,
    append_note,
)
from curriculum_agent.prompts.stage_3_plo import build_plo_from_need_prompt
from curriculum_agent.prompts.summarize_need import build_summarize_need_prompt
from curriculum_agent.stages import need_combination as nc
from curriculum_agent.stages import plo_synthesis as ps

NOTE = "เน้นทักษะด้าน AI และการวิเคราะห์ข้อมูลขนาดใหญ่"


def _need() -> Need:
    return Need(
        need_id="N1",
        program_id="p1",
        statement_th="ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=2,
        demand_score=0.8,
    )


def _meta() -> ProgramMetadata:
    return ProgramMetadata(
        program_id="p1",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
        vision_th="มุ่งผลิตบัณฑิตที่มีความเชี่ยวชาญด้านเทคโนโลยี",
        mission_th="พันธกิจของหลักสูตร",
        philosophy_th="ปรัชญาของหลักสูตร",
        program_goals_th=["เป้าหมายที่ 1"],
        program_objectives_th=["วัตถุประสงค์ที่ 1"],
    )


# --- append_note ---


def test_append_note_returns_the_message_unchanged_when_there_is_no_note():
    assert append_note("เนื้อหา", None) == "เนื้อหา"
    assert append_note("เนื้อหา", "") == "เนื้อหา"


def test_append_note_adds_a_headed_block_after_the_original_content():
    out = append_note("เนื้อหา", NOTE)
    assert out.startswith("เนื้อหา")
    assert NOTE_HEADER_TH in out
    assert NOTE in out


# --- build_summarize_need_prompt ---


def test_need_prompt_puts_the_note_in_the_user_message_only():
    messages = build_summarize_need_prompt(["วิเคราะห์ข้อมูล"], ["ตัวอย่าง evidence"], "S", note_th=NOTE)
    assert NOTE in messages[1]["content"]
    assert NOTE_HEADER_TH in messages[1]["content"]
    # The note is data the model is given, not policy it is bound by.
    assert NOTE not in messages[0]["content"]


def test_need_prompt_without_a_note_has_no_guidance_block():
    messages = build_summarize_need_prompt(["วิเคราะห์ข้อมูล"], ["ตัวอย่าง evidence"], "S")
    assert NOTE_HEADER_TH not in messages[1]["content"]


def test_need_prompt_system_text_is_identical_with_and_without_a_note():
    """The policy line is unconditional, so system text never varies per request.

    Prompt text elsewhere in this project is hashed into LLM cache keys
    (skill_extraction._extraction_contract_fingerprint,
    llm_clustering._clustering_contract_fingerprint). A system message that
    changed with the input would make such a fingerprint meaningless.
    """
    with_note = build_summarize_need_prompt(["x"], [], "S", note_th=NOTE)
    without = build_summarize_need_prompt(["x"], [], "S")
    assert NOTE_POLICY_TH in without[0]["content"]
    assert with_note[0]["content"] == without[0]["content"]


# --- build_plo_from_need_prompt ---


def test_plo_prompt_puts_the_note_in_the_user_message_only():
    messages = build_plo_from_need_prompt(_meta(), [_need()], note_th=NOTE)
    assert NOTE in messages[1]["content"]
    assert NOTE_HEADER_TH in messages[1]["content"]
    assert NOTE not in messages[0]["content"]


def test_plo_prompt_without_a_note_has_no_guidance_block():
    messages = build_plo_from_need_prompt(_meta(), [_need()])
    assert NOTE_HEADER_TH not in messages[1]["content"]


def test_plo_prompt_system_text_is_identical_with_and_without_a_note():
    with_note = build_plo_from_need_prompt(_meta(), [_need()], note_th=NOTE)
    without = build_plo_from_need_prompt(_meta(), [_need()])
    assert NOTE_POLICY_TH in without[0]["content"]
    assert with_note[0]["content"] == without[0]["content"]


def test_plo_prompt_still_carries_the_need_id_and_statement():
    """Guards against the appended note displacing the Need block it follows."""
    messages = build_plo_from_need_prompt(_meta(), [_need()], note_th=NOTE)
    assert "N1" in messages[1]["content"]
    assert "ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้" in messages[1]["content"]


# --- stages forward the note to their prompt ---
#
# These assert on the real prompt text rather than on a mocked builder, so they
# pin the whole path from the state key to the message a model would receive.


async def test_need_combination_forwards_the_note_to_the_summarize_prompt(
    monkeypatch: pytest.MonkeyPatch,
):
    seen: list[list[dict[str, str]]] = []

    async def fake_cluster(names: list[str]) -> list[list[int]]:
        return [[i] for i in range(len(names))]

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        seen.append(messages)
        return nc._NeedStatement(statement_th="ตลาดต้องการความสามารถนี้", statement_en="Demand")

    monkeypatch.setattr(nc, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_light", fake_summarize)
    # Stub every persistence call the stage makes, not only bulk_insert.
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    skill = ExtractedSkill(
        skill_id="S1",
        program_id="p1",
        skill_name_th="วิเคราะห์ข้อมูลขนาดใหญ่",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        evidence_span_th="ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้",
        source_evidence_id="E1",
        source_stakeholder_type="employer",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )
    await nc.run(
        {
            "program_id": "p1",
            "designer_note": NOTE,
            "classified_evidence": [
                {"evidence_id": "E1", "classification": "general", "stakeholder_type": "employer"}
            ],
            "extracted_skills": [skill.model_dump(mode="json")],
        }
    )

    assert seen, "the summarize call never happened"
    assert NOTE in seen[0][1]["content"]
    assert NOTE_HEADER_TH in seen[0][1]["content"]


async def test_plo_synthesis_forwards_the_note_to_the_draft_prompt(
    monkeypatch: pytest.MonkeyPatch,
):
    seen: list[list[dict[str, str]]] = []

    async def fake_heavy(model, messages, **kw):  # noqa: ANN001, ANN003
        seen.append(messages)
        return ps._SingleDraftResponse(
            plo=ps._PLODraft(
                statement_th="วิเคราะห์ข้อมูลขนาดใหญ่เพื่อสนับสนุนการตัดสินใจได้",
                bloom_level="analyze",
                action_verb_th="วิเคราะห์",
                source_need_ids=["N1"],
                rationale_th="เหตุผล",
            )
        )

    monkeypatch.setattr(ps, "complete_heavy", fake_heavy)
    monkeypatch.setattr(
        ps,
        "complete_light",
        AsyncMock(
            return_value=ps._SmartSoftJudge(
                specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
            )
        ),
    )
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())

    await ps.run(
        {
            "program_id": "p1",
            "designer_note": NOTE,
            "metadata": _meta().model_dump(mode="json"),
            "needs": [_need().model_dump(mode="json")],
        }
    )

    assert seen, "the draft call never happened"
    assert NOTE in seen[0][1]["content"]
