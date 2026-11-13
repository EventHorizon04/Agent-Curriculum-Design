"""Re-running a stage must replace its rows, not accumulate a second set.

`skill_id` and `need_id` are generated per run while both repositories upsert by
that id, so before this was fixed every re-run inserted a complete duplicate set
and `GET /needs/skills` returned each skill twice.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory
from curriculum_agent.stages import need_combination as nc
from curriculum_agent.stages import skill_extraction as se
from curriculum_agent.stages import skill_grouping as sg
from tests.support.needs import RATIONALE_TH, run_need_pipeline_from_skills

_SPAN = "สามารถวิเคราะห์ข้อมูลขนาดใหญ่"
_TEXT_A = "บริษัทต้องการผู้ที่สามารถวิเคราะห์ข้อมูลขนาดใหญ่และออกแบบระบบฐานข้อมูลได้"
_TEXT_B = "องค์กรมองหาคนที่สามารถวิเคราะห์ข้อมูลขนาดใหญ่เพื่อสนับสนุนการตัดสินใจ"


def _evidence(eid: str, text: str) -> dict[str, object]:
    return {
        "evidence_id": eid,
        "program_id": "prog-1",
        "stakeholder_type": "employer",
        "source_name": "JD",
        "raw_text_th": text,
        "collected_at": "2026-01-01T00:00:00",
        "classification": "general",
        "metadata": {},
    }


def _item(name: str, bloom: str) -> se._SkillItem:
    return se._SkillItem(
        skill_name_th=name,
        ksec_category="S",
        bloom_level=bloom,
        evidence_span_th=_SPAN,
        confidence=0.9,
    )


def _run_extraction(
    responses: list[se._ExtractedSkillsResponse], evidence: list[dict[str, object]]
):
    """Drive skill_extraction.run with canned LLM responses, one per evidence item.

    Returns (coroutine-result-awaitable, repo mock, call-order list). The cache
    always misses so every evidence item reaches the canned response.
    """
    order: list[str] = []
    repo = AsyncMock()
    repo.delete_by_program = AsyncMock(side_effect=lambda pid: order.append("delete"))
    repo.bulk_insert = AsyncMock(side_effect=lambda rows: order.append("insert"))

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()

    served = iter(responses)

    async def fake_complete_extraction(model, messages, **kw):  # noqa: ANN001, ANN003
        return next(served)

    async def _go():
        with (
            patch.object(se, "LLMCacheRepository", return_value=cache),
            patch.object(se, "complete_extraction", side_effect=fake_complete_extraction),
            patch.object(se, "SkillRepository", return_value=repo),
        ):
            return await se.run({"program_id": "prog-1", "classified_evidence": evidence})

    return _go(), repo, order


async def test_duplicate_name_within_one_evidence_collapses_keeping_max_bloom():
    """One evidence item naming the same skill twice is one capability, not two.

    Left un-deduped these rows inflate `Need.freq` (which counts member skills)
    and show the designer the same skill twice in the Stage 3 table.
    """
    resp = se._ExtractedSkillsResponse(
        skills=[
            _item("วิเคราะห์ข้อมูลขนาดใหญ่", "apply"),
            _item("วิเคราะห์ข้อมูลขนาดใหญ่", "evaluate"),
        ]
    )
    coro, _repo, _order = _run_extraction([resp], [_evidence("E1", _TEXT_A)])
    state = await coro

    rows = state["extracted_skills"]
    assert len(rows) == 1, f"expected one row, got {[r['skill_name_th'] for r in rows]}"
    # Highest level wins, matching merge_bloom: the lower level is implied by it.
    assert rows[0]["bloom_level"] == "evaluate"


async def test_duplicate_name_differing_only_by_case_and_spacing_collapses():
    resp = se._ExtractedSkillsResponse(
        skills=[_item("Python  Programming", "apply"), _item("python programming", "apply")]
    )
    coro, _repo, _order = _run_extraction([resp], [_evidence("E1", _TEXT_A)])
    state = await coro

    assert len(state["extracted_skills"]) == 1


async def test_same_skill_from_two_evidence_items_stays_two_rows():
    """Deduping across evidence would destroy the frequency signal.

    Two sources asking for the same capability is the evidence that it is in
    demand — `freq` and `demand_score` are built from exactly this.
    """
    resp_a = se._ExtractedSkillsResponse(skills=[_item("วิเคราะห์ข้อมูลขนาดใหญ่", "apply")])
    resp_b = se._ExtractedSkillsResponse(skills=[_item("วิเคราะห์ข้อมูลขนาดใหญ่", "apply")])
    coro, _repo, _order = _run_extraction(
        [resp_a, resp_b], [_evidence("E1", _TEXT_A), _evidence("E2", _TEXT_B)]
    )
    state = await coro

    rows = state["extracted_skills"]
    assert len(rows) == 2
    assert {r["source_evidence_id"] for r in rows} == {"E1", "E2"}


async def test_skill_extraction_clears_previous_rows_before_inserting():
    resp = se._ExtractedSkillsResponse(skills=[_item("วิเคราะห์ข้อมูลขนาดใหญ่", "apply")])
    coro, repo, order = _run_extraction([resp], [_evidence("E1", _TEXT_A)])
    await coro

    repo.delete_by_program.assert_awaited_once_with("prog-1")
    assert order == ["delete", "insert"], (
        "the program's existing skills must be cleared before the new set lands, "
        "or a re-run leaves both sets in the table"
    )


def _skill(name: str, ksec: KSECCategory, sid: str, eid: str) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="prog-1",
        skill_name_th=name,
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=_SPAN,
        source_evidence_id=eid,
        source_stakeholder_type="employer",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


async def test_need_combination_clears_previous_needs_before_inserting(
    monkeypatch: pytest.MonkeyPatch,
):
    """Same defect as skills: `need_id` is fresh per run and the repo upserts."""

    async def fake_cluster(
        names: list[str],
        target: int | None = None,
        program_context: str | None = None,
        ksec: object = None,
    ) -> list[list[int]]:
        return [[i] for i in range(len(names))]

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc._NeedStatement(
            statement_th="ตลาดต้องการความสามารถนี้",
            statement_en="Demand",
            rationale_th=RATIONALE_TH,
        )

    monkeypatch.setattr(sg, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", fake_summarize)

    # An AsyncMock set on the class is not a descriptor, so `self` is not passed —
    # these take only the real argument.
    order: list[str] = []
    monkeypatch.setattr(
        nc.NeedRepository,
        "delete_by_program",
        AsyncMock(side_effect=lambda pid: order.append("delete")),
    )
    monkeypatch.setattr(
        nc.NeedRepository,
        "bulk_insert",
        AsyncMock(side_effect=lambda rows: order.append("insert")),
    )

    skills = [_skill("เขียนโปรแกรมเว็บ", KSECCategory.S, "S1", "E1")]
    await run_need_pipeline_from_skills(
        {
            "program_id": "prog-1",
            "classified_evidence": [
                {"evidence_id": "E1", "classification": "general", "stakeholder_type": "employer"}
            ],
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    assert order == ["delete", "insert"]
