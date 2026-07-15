from __future__ import annotations

from unittest.mock import AsyncMock, patch

from curriculum_agent.models import ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps

META = ProgramMetadata(
    program_id="p1",
    name_th="วท.บ.",
    name_en="BSc",
    field="CS",
    degree_level="bachelor",
    duration_years=4,
    faculty="วิทยาศาสตร์",
    university="ม.ทดสอบ",
    vision_th="ผลิตบัณฑิตคุณภาพ",
    mission_th="พันธกิจของหลักสูตร",
    philosophy_th="ปรัชญาของหลักสูตร",
    program_goals_th=["เป้าหมายหลักสูตรที่ 1"],
    program_objectives_th=["obj"],
)

_SOFT_OK = ps._SmartSoftJudge(
    specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
)


def _draft(
    statement: str, verb: str = "วิเคราะห์", clusters: list[str] | None = None
) -> ps._PLODraft:
    return ps._PLODraft(
        plo_id="PLO1",
        statement_th=statement,
        domain="cognitive",
        bloom_level="analyze",
        action_verb_th=verb,
        source_cluster_ids=clusters if clusters is not None else ["c1"],
        rationale_th="เหตุผล",
    )


async def test_clean_draft_passes_without_retry():
    with patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)):
        out = await ps._ensure_smart(_draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META)
    assert out.retry_count == 0
    assert out.escalated is False
    assert out.smart_check.passed


async def test_hard_fail_retries_with_criterion_and_escalates():
    bad = _draft("ข้อมูลทางสถิติ", verb="ออกแบบ")  # verb absent → S_VERB forever
    fix_calls: list[list[dict]] = []

    async def fake_heavy(model, messages, **kw):
        fix_calls.append(messages)
        return ps._SingleDraftResponse(plo=bad)  # never fixes it

    with (
        patch.object(ps, "complete_heavy", side_effect=fake_heavy),
        patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)),
    ):
        out = await ps._ensure_smart(bad, {"c1"}, META)

    assert out.retry_count == 3
    assert out.escalated is True
    assert len(fix_calls) == 3
    assert "Specific" in fix_calls[0][1]["content"]  # criterion hint named in retry prompt


async def test_soft_fail_flags_without_blocking():
    judge = ps._SmartSoftJudge(
        specific_object_ok=True,
        achievable_ok=False,
        relevant_alignment_ok=False,
        notes_th="ระดับสูงไป",
    )
    with patch.object(ps, "complete_light", AsyncMock(return_value=judge)):
        out = await ps._ensure_smart(_draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META)
    assert out.escalated is False
    assert set(out.soft_flags) == {"A_level", "R_alignment"}
    assert out.smart_check.passed  # soft fails never block
