"""A skill's importance_score and its Need's demand_score must agree.

Both are the same formula over the same evidence, and both are shown to the
designer — on the skill table and on the Need beside it. They were computed
against different corpora: skill_extraction divided by every evidence item, and
need_combination by the items that yielded at least one skill. One capability
therefore scored 0.23 as a skill and 0.35 as the Need it alone formed, with
nothing on either screen to say why.

The gap only opens when some evidence item yields no skills, which is why it
survived: every fixture in the suite extracted something from everything.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.stages import need_combination as nc
from curriculum_agent.stages import skill_extraction as se
from curriculum_agent.stages import skill_grouping as sg
from curriculum_agent.stages.demand import PRACTITIONER_WEIGHT
from tests.support.needs import RATIONALE_TH, run_need_pipeline_from_skills

_SPANS = {
    "E1": "สถานประกอบการต้องการผู้ที่ออกแบบฐานข้อมูลเชิงสัมพันธ์ได้",
    "E2": "ต้องการผู้ที่พัฒนาระบบเว็บแอปพลิเคชันด้วยเฟรมเวิร์กสมัยใหม่",
    # Yields nothing — the item that makes the two corpora differ.
    "E3": "อยากให้หลักสูตรมีกิจกรรมนอกหลักสูตรที่หลากหลายมากขึ้นกว่านี้",
}

_SKILL_BY_EVIDENCE = {
    "E1": "ออกแบบฐานข้อมูลเชิงสัมพันธ์",
    "E2": "พัฒนาระบบเว็บแอปพลิเคชัน",
}


def _evidence(evidence_id: str, stakeholder_type: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "program_id": "prog-1",
        "stakeholder_type": stakeholder_type,
        "source_name": f"src-{evidence_id}",
        "raw_text_th": _SPANS[evidence_id],
        "collected_at": "2026-01-01T00:00:00",
        "classification": "general",
        "metadata": {},
    }


async def _fake_extract(response_model, messages, **kw):  # noqa: ANN001, ANN003
    text = messages[-1]["content"]
    for evidence_id, span in _SPANS.items():
        if span in text and evidence_id in _SKILL_BY_EVIDENCE:
            return response_model(
                skills=[
                    {
                        "skill_name_th": _SKILL_BY_EVIDENCE[evidence_id],
                        "skill_name_en": "Skill",
                        "ksec_category": "S",
                        "bloom_level": "apply",
                        "evidence_span_th": span,
                        "confidence": 0.9,
                    }
                ]
            )
    return response_model(skills=[])


@pytest.fixture
async def extracted() -> list[dict]:
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    with (
        patch.object(se, "LLMCacheRepository", return_value=cache),
        patch.object(se, "complete_extraction", _fake_extract),
        patch.object(se.SkillRepository, "delete_by_program", AsyncMock()),
        patch.object(se.SkillRepository, "bulk_insert", AsyncMock()),
    ):
        state = await se.run(
            {
                "program_id": "prog-1",
                "classified_evidence": [
                    _evidence("E1", "employer"),
                    _evidence("E2", "employer"),
                    _evidence("E3", "student"),
                ],
            }
        )
    return state["extracted_skills"]


async def test_the_silent_evidence_item_is_out_of_both_corpora(extracted, monkeypatch):
    """E3 produced no skill, so it is not part of the demand either score divides
    by — one of two items named each capability, not one of three."""
    assert len(extracted) == 2

    async def fake_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [[i] for i in range(len(names))]

    monkeypatch.setattr(sg, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", _fake_summarize_stub)
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    state = await run_need_pipeline_from_skills(
        {"program_id": "prog-1", "extracted_skills": extracted}
    )
    needs = state["needs"]
    assert len(needs) == 2

    # No professional council in the corpus, so the mandate block is zero. Both
    # surviving items are employers, so the whole score is the practitioner block:
    # one of the two practitioner items that spoke.
    expected = round(PRACTITIONER_WEIGHT * (1 / 2), 4)
    assert {n["demand_score"] for n in needs} == {expected}
    assert {s["importance_score"] for s in extracted} == {expected}


async def test_a_single_skill_need_scores_exactly_what_its_skill_did(extracted, monkeypatch):
    """The designer sees both numbers side by side, so an identical capability
    must not carry two different demands."""

    async def fake_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        return [[i] for i in range(len(names))]

    monkeypatch.setattr(sg, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", _fake_summarize_stub)
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    state = await run_need_pipeline_from_skills(
        {"program_id": "prog-1", "extracted_skills": extracted}
    )

    importance_by_skill_id = {s["skill_id"]: s["importance_score"] for s in extracted}
    for need in state["needs"]:
        assert len(need["member_skill_ids"]) == 1
        assert need["demand_score"] == importance_by_skill_id[need["member_skill_ids"][0]]


async def _fake_summarize_stub(model, messages, **kw):  # noqa: ANN001, ANN003
    return nc._NeedStatement(
        statement_th="ตลาดแรงงานต้องการผู้ที่ออกแบบและดูแลระบบสารสนเทศขององค์กรให้ใช้งานได้จริง",
        statement_en="The market needs people who maintain corporate information systems",
        rationale_th=RATIONALE_TH,
    )
