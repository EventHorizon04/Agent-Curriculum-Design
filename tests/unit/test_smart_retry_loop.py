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
    program_goals_th=["เป้าหมายหลักสูตรที่ 1"],
    program_objectives_th=["obj"],
)

_SOFT_OK = ps._SmartSoftJudge()  # every verdict defaults True


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
        out = await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], ["ตลาดต้องการ"], "PLO1"
        )
    assert out.retry_count == 0
    assert out.escalated is False
    assert out.smart_check.passed


async def test_hard_fail_retries_with_criterion_and_escalates():
    bad = _draft("ข้อมูลทางสถิติ", verb="ออกแบบ")  # verb absent → S_VERB forever
    fix_calls: list[list[dict]] = []

    async def fake_synthesis(model, messages, **kw):
        fix_calls.append(messages)
        return ps._SingleDraftResponse(plo=bad)  # never fixes it

    with (
        patch.object(ps, "complete_synthesis", side_effect=fake_synthesis),
        patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)),
    ):
        out = await ps._ensure_smart(bad, {"c1"}, META, ["c1"], ["ตลาดต้องการ"], "PLO1")

    assert out.retry_count == 3
    assert out.escalated is True
    assert len(fix_calls) == 3
    assert "Specific" in fix_calls[0][1]["content"]  # criterion hint named in retry prompt


async def test_soft_fail_flags_without_blocking():
    judge = ps._SmartSoftJudge(
        specific_object_ok=True,
        achievable_ok=False,
        relevant_needs_ok=False,
        notes_th="ระดับสูงไป",
    )
    with patch.object(ps, "complete_light", AsyncMock(return_value=judge)):
        out = await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], ["ตลาดต้องการ"], "PLO1"
        )
    assert out.escalated is False
    assert set(out.soft_flags) == {"A_level", "R_needs"}
    assert out.smart_check.passed is False  # soft fails reach SMARTCheck but never escalate


async def test_gate_judges_authoritative_need_ids_not_the_models_echo():
    """The model may echo a wrong/unknown need id in source_need_ids; the gate
    must judge the ids that will actually ship (authoritative_need_ids passed
    in by the caller), not whatever the model returned.

    Without pinning the draft to authoritative_need_ids before hard_failures
    runs, this "WRONG-ID" (unknown to known_need_ids={"c1"}) would fail
    R_EVIDENCE, burn all 3 retries against a fix prompt that never mentions
    need ids (so it cannot repair the field — fake_synthesis below just echoes the
    same bad draft back, as a real model would when asked to fix an
    unrelated criterion), and escalate a PLO whose real, shipped evidence
    trail was correct all along.
    """
    bad = _draft("วิเคราะห์ข้อมูลทางสถิติได้", needs=["WRONG-ID"])

    async def fake_synthesis(model, messages, **kw):
        return ps._SingleDraftResponse(plo=bad)

    with (
        patch.object(ps, "complete_synthesis", side_effect=fake_synthesis),
        patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)),
    ):
        out = await ps._ensure_smart(
            bad,
            {"c1"},
            META,
            authoritative_need_ids=["c1"],
            need_statements_th=["ตลาดต้องการ"],
            plo_id="PLO1",
        )

    assert out.retry_count == 0
    assert out.escalated is False
    assert out.smart_check.relevant is True
    assert out.draft.source_need_ids == ["c1"]


NEED = Need(
    need_id="c1",
    program_id="p1",
    statement_th="ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลทางสถิติได้",
    ksec_category=KSECCategory.S,
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

    async def fake_synthesis(model, messages, **kw):
        calls.append(messages)
        return ps._SingleDraftResponse(plo=bad)

    with (
        patch.object(ps, "complete_synthesis", side_effect=fake_synthesis),
        patch.object(ps, "complete_light", AsyncMock(return_value=_SOFT_OK)),
    ):
        await ps.synthesize_from_needs(META, [NEED], "p1", {"c1"}, "PLO1", note_th=note)

    # One draft call, then three fix attempts (_MAX_RETRIES).
    assert len(calls) == 4
    assert note in calls[0][1]["content"], "the draft prompt must carry the note"
    for i, fix in enumerate(calls[1:], start=1):
        joined = "".join(m["content"] for m in fix)
        assert note not in joined, f"fix attempt {i} leaked the note into a repair prompt"


async def test_a_soft_failure_reaches_smart_check_without_escalating():
    """SMARTCheck.achievable and .timely were hardcoded True and the judge's
    verdicts never reached SMARTCheck at all, so `passed` reported success for a
    flagged PLO. A soft failure must show in SMARTCheck and still not escalate."""
    judge = ps._SmartSoftJudge(measurable_ok=False, notes_th="ประเมินด้วยเครื่องมือใดไม่ชัด")

    with patch.object(ps, "complete_light", AsyncMock(return_value=judge)):
        out = await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], ["ตลาดต้องการ"], "PLO1"
        )

    assert out.smart_check.measurable is False
    assert out.smart_check.passed is False
    assert out.escalated is False
    assert "M_assessable" in out.soft_flags


async def test_a_judge_exception_leaves_every_soft_verdict_true():
    """An LLM hiccup must degrade toward 'not flagged' rather than falsely flagging
    sound work."""
    with patch.object(ps, "complete_light", AsyncMock(side_effect=RuntimeError("boom"))):
        out = await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], ["ตลาดต้องการ"], "PLO1"
        )

    assert out.soft_flags == []
    assert out.smart_check.achievable is True
    assert out.smart_check.timely is True


async def test_soft_criteria_never_escalate_even_when_all_five_fail():
    """Escalation reads hard-check failures alone — an immutable project rule."""
    judge = ps._SmartSoftJudge(
        specific_object_ok=False,
        measurable_ok=False,
        achievable_ok=False,
        relevant_needs_ok=False,
        time_bound_ok=False,
    )

    with patch.object(ps, "complete_light", AsyncMock(return_value=judge)):
        out = await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"), {"c1"}, META, ["c1"], ["ตลาดต้องการ"], "PLO1"
        )

    assert out.escalated is False
    assert out.retry_count == 0
    assert sorted(out.soft_flags) == sorted(
        ["S_object", "M_assessable", "A_level", "R_needs", "T_horizon"]
    )


async def test_the_needs_statements_reach_the_judge_prompt():
    """R is judged against the Needs the PLO cites, so the statements must travel
    from synthesize_from_needs into the prompt."""
    seen: list[list[dict[str, str]]] = []

    async def capture(model, messages, **kw):  # noqa: ANN001, ANN003
        seen.append(messages)
        return ps._SmartSoftJudge()

    with patch.object(ps, "complete_light", side_effect=capture):
        await ps._ensure_smart(
            _draft("วิเคราะห์ข้อมูลทางสถิติได้"),
            {"c1"},
            META,
            ["c1"],
            ["ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้"],
            "PLO1",
        )

    assert "ตลาดต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้" in seen[0][1]["content"]
