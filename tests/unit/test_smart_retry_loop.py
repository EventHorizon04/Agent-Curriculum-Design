from __future__ import annotations

from unittest.mock import AsyncMock, patch

from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
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


def _draft(statement: str, verb: str = "วิเคราะห์", needs: list[str] | None = None) -> ps._PLODraft:
    return ps._PLODraft(
        statement_th=statement,
        bloom_level="analyze",
        action_verb_th=verb,
        source_need_ids=needs if needs is not None else ["c1"],
        rationale_th="เหตุผล",
    )


async def test_clean_draft_passes_without_retry():
    with patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)):
        out = await ps._ensure_smart(_draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], "PLO1")
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
        out = await ps._ensure_smart(bad, {"c1"}, META, ["c1"], "PLO1")

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
        out = await ps._ensure_smart(_draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], "PLO1")
    assert out.escalated is False
    assert set(out.soft_flags) == {"A_level", "R_alignment"}
    assert out.smart_check.passed  # soft fails never block


async def test_gate_judges_authoritative_need_ids_not_the_models_echo():
    """The model may echo a wrong/unknown need id in source_need_ids; the gate
    must judge the ids that will actually ship (authoritative_need_ids passed
    in by the caller), not whatever the model returned.

    Without pinning the draft to authoritative_need_ids before hard_failures
    runs, this "WRONG-ID" (unknown to known_need_ids={"c1"}) would fail
    R_EVIDENCE, burn all 3 retries against a fix prompt that never mentions
    need ids (so it cannot repair the field — fake_heavy below just echoes the
    same bad draft back, as a real model would when asked to fix an
    unrelated criterion), and escalate a PLO whose real, shipped evidence
    trail was correct all along.
    """
    bad = _draft("วิเคราะห์ข้อมูลทางสถิติได้", needs=["WRONG-ID"])

    async def fake_heavy(model, messages, **kw):
        return ps._SingleDraftResponse(plo=bad)

    with (
        patch.object(ps, "complete_heavy", side_effect=fake_heavy),
        patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)),
    ):
        out = await ps._ensure_smart(
            bad, {"c1"}, META, authoritative_need_ids=["c1"], plo_id="PLO1"
        )

    assert out.retry_count == 0
    assert out.escalated is False
    assert out.smart_check.relevant is True
    assert out.draft.source_need_ids == ["c1"]


NEED = Need(
    need_id="c1",
    program_id="p1",
    statement_th="ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลทางสถิติได้",
    ksec_category=KSECCategory.SS,
    bloom_level=BloomLevel.ANALYZE,
    member_skill_ids=["S1"],
    source_evidence_ids=["E1"],
    freq=1,
    demand_score=0.6,
)


async def test_note_reaches_the_draft_prompt_but_never_a_fix_prompt():
    """The fix prompt repairs one named criterion while preserving the substance
    it was handed, which already carries the note's effect forward. Re-injecting
    guidance there invites a rewrite where a repair was asked for.
    """
    note = "เน้นบริบทอุตสาหกรรมยานยนต์"
    bad = _draft("ข้อมูลทางสถิติ", verb="ออกแบบ")  # verb absent → S_VERB never passes
    calls: list[list[dict]] = []

    async def fake_heavy(model, messages, **kw):
        calls.append(messages)
        return ps._SingleDraftResponse(plo=bad)

    with (
        patch.object(ps, "complete_heavy", side_effect=fake_heavy),
        patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)),
    ):
        await ps.synthesize_from_needs(META, [NEED], "p1", {"c1"}, "PLO1", note_th=note)

    # One draft call, then three fix attempts (_MAX_RETRIES).
    assert len(calls) == 4
    assert note in calls[0][1]["content"], "the draft prompt must carry the note"
    for i, fix in enumerate(calls[1:], start=1):
        joined = "".join(m["content"] for m in fix)
        assert note not in joined, f"fix attempt {i} leaked the note into a repair prompt"
