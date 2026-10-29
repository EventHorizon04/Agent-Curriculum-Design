"""What the two-phase stage guarantees.

Drafting and validating used to be fused in one sequential loop, so none of
these properties could even be stated: a validator could not see the set it was
judging against, and one PLO's failure was one PLO's failure because nothing
else was in flight.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import BloomLevel, Need, ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps
from tests.support.smart_agent import set_soft_judge

META = ProgramMetadata(
    program_id="cs-test",
    name_th="วิทยาการคอมพิวเตอร์",
    name_en="Computer Science",
    field="วิทยาการคอมพิวเตอร์",
    degree_level="bachelor",
    duration_years=4,
    faculty="คณะวิทยาศาสตร์",
    university="มหาวิทยาลัยทดสอบ",
)

_VERBS = {
    "N1": ("ออกแบบ", BloomLevel.CREATE),
    "N2": ("วิเคราะห์", BloomLevel.ANALYZE),
    "N3": ("ประเมิน", BloomLevel.EVALUATE),
}


def _need(need_id: str, demand: float) -> Need:
    return Need(
        need_id=need_id,
        program_id="cs-test",
        statement_th=f"ต้องการบัณฑิตที่ทำงานด้าน {need_id} ได้ตามมาตรฐานอุตสาหกรรม",
        ksec_category="S",
        bloom_level=BloomLevel.CREATE,
        member_skill_ids=[f"S-{need_id}"],
        source_evidence_ids=[f"E-{need_id}"],
        freq=2,
        demand_score=demand,
    )


def _draft_for(need_id: str) -> ps._PLODraft:
    verb, level = _VERBS[need_id]
    return ps._PLODraft(
        statement_th=f"{verb}ระบบสารสนเทศสำหรับงาน {need_id} ตามมาตรฐานอุตสาหกรรมได้",
        bloom_level=level,
        action_verb_th=verb,
        source_need_ids=[need_id],
        rationale_th=f"ทักษะที่ตลาดต้องการสำหรับ {need_id}",
    )


def _state(needs: list[Need]) -> dict:
    return {
        "program_id": "cs-test",
        "metadata": META.model_dump(mode="json"),
        "needs": [n.model_dump(mode="json") for n in needs],
    }


def _patch_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())


def _fake_synthesis(fails_for: set[str] | None = None):
    """A draft call that routes by the Need id in the prompt body."""

    async def fake(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        need_id = next(nid for nid in _VERBS if nid in body)
        if fails_for and need_id in fails_for:
            raise RuntimeError(f"provider refused {need_id}")
        return ps._SingleDraftResponse(plo=_draft_for(need_id))

    return fake


def _capture_siblings(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Record the sibling ids each PLO was validated against, then let the real
    validation run — a stub would prove the plumbing and nothing else."""
    seen: dict[str, list[str]] = {}
    real = ps.validate_and_build

    async def wrapper(draft, **kwargs):  # noqa: ANN001, ANN003
        seen[kwargs["plo_id"]] = [s.plo_id for s in kwargs["siblings"]]
        return await real(draft, **kwargs)

    monkeypatch.setattr(ps, "validate_and_build", wrapper)
    return seen


async def test_every_draft_is_validated_against_the_others_and_not_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole reason for two phases: overlap is a property of the set, and a
    validator that cannot see the set cannot judge it. An outcome in its own
    sibling list would be a duplicate the validator faithfully discovers."""
    _patch_repos(monkeypatch)
    monkeypatch.setattr(ps, "complete_plo_synthesis", _fake_synthesis())
    set_soft_judge(monkeypatch)
    seen = _capture_siblings(monkeypatch)

    await ps.run(_state([_need("N1", 0.9), _need("N2", 0.6), _need("N3", 0.3)]))

    assert seen == {
        "PLO1": ["PLO2", "PLO3"],
        "PLO2": ["PLO1", "PLO3"],
        "PLO3": ["PLO1", "PLO2"],
    }


async def test_a_failed_draft_leaves_its_number_unused_and_contributes_no_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gap says "this Need failed". The validator sees the drafts that exist,
    not a hole where one should have been."""
    _patch_repos(monkeypatch)
    monkeypatch.setattr(ps, "complete_plo_synthesis", _fake_synthesis(fails_for={"N2"}))
    set_soft_judge(monkeypatch)
    seen = _capture_siblings(monkeypatch)

    state = await ps.run(_state([_need("N1", 0.9), _need("N2", 0.6), _need("N3", 0.3)]))

    assert [p["plo_id"] for p in state["plos"]] == ["PLO1", "PLO3"]
    assert seen == {"PLO1": ["PLO3"], "PLO3": ["PLO1"]}


async def test_one_slot_failing_to_build_does_not_lose_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PLOs are built concurrently now, so an exception escaping one frame would
    take out every other outcome in the same gather."""
    _patch_repos(monkeypatch)
    monkeypatch.setattr(ps, "complete_plo_synthesis", _fake_synthesis())
    set_soft_judge(monkeypatch)

    real = ps.validate_and_build

    async def explode_on_plo2(draft, **kwargs):  # noqa: ANN001, ANN003
        if kwargs["plo_id"] == "PLO2":
            # An empty evidence trail is the realistic version of this: PLO's
            # check_evidence is not gated on escalation.
            kwargs = {
                **kwargs,
                "needs": [kwargs["needs"][0].model_copy(update={"source_evidence_ids": []})],
            }
        return await real(draft, **kwargs)

    monkeypatch.setattr(ps, "validate_and_build", explode_on_plo2)

    state = await ps.run(_state([_need("N1", 0.9), _need("N2", 0.6), _need("N3", 0.3)]))

    assert [p["plo_id"] for p in state["plos"]] == ["PLO1", "PLO3"]


async def test_numbering_comes_from_demand_not_from_which_draft_finishes_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slot selection happens before any call, and gather preserves input order.
    The day someone switches to as_completed for a progress bar, PLO4 starts
    meaning a different outcome between runs — and designers cite these ids."""
    _patch_repos(monkeypatch)
    set_soft_judge(monkeypatch)

    order: list[str] = []
    # Each draft waits for the one below it in demand to finish, so completion
    # order is forced to be the reverse of demand order without any real-time delay.
    finished = {nid: asyncio.Event() for nid in _VERBS}
    waits_for = {"N3": None, "N2": "N3", "N1": "N2"}
    entered: set[str] = set()
    all_entered = asyncio.Event()

    async def out_of_order_synthesis(model, messages, **kw):  # noqa: ANN001, ANN003
        body = messages[-1]["content"]
        need_id = next(nid for nid in _VERBS if nid in body)
        entered.add(need_id)
        if entered == set(_VERBS):
            all_entered.set()
        # Every draft is in flight before any may finish; then the least-demanded
        # Need answers first.
        await asyncio.wait_for(all_entered.wait(), timeout=5)
        blocker = waits_for[need_id]
        if blocker is not None:
            await asyncio.wait_for(finished[blocker].wait(), timeout=5)
        order.append(need_id)
        finished[need_id].set()
        return ps._SingleDraftResponse(plo=_draft_for(need_id))

    monkeypatch.setattr(ps, "complete_plo_synthesis", out_of_order_synthesis)

    state = await ps.run(_state([_need("N1", 0.9), _need("N2", 0.6), _need("N3", 0.3)]))

    assert order == ["N3", "N2", "N1"], "the test needs the drafts to finish out of order"
    assert [p["plo_id"] for p in state["plos"]] == ["PLO1", "PLO2", "PLO3"]
    assert [p["source_need_ids"][0] for p in state["plos"]] == ["N1", "N2", "N3"]


async def test_the_two_phases_are_bounded_by_different_ceilings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase A is one call per PLO, so the per-call ceiling fits. Phase B is a
    loop of several serial calls per PLO, so what bounds it is how many loops
    run at once — sharing one knob would let a raise for extraction multiply the
    validation bill."""
    _patch_repos(monkeypatch)
    monkeypatch.setattr(ps, "complete_plo_synthesis", _fake_synthesis())
    set_soft_judge(monkeypatch)

    limits: list[int] = []
    real = ps.gather_bounded

    async def record(limit, factories):  # noqa: ANN001
        limits.append(limit)
        return await real(limit, factories)

    monkeypatch.setattr(ps, "gather_bounded", record)

    await ps.run(_state([_need("N1", 0.9), _need("N2", 0.6)]))

    assert limits == [
        ps.settings.llm_max_concurrency,
        ps.settings.validation_max_concurrent_plos,
    ]


async def test_the_merge_entry_point_still_drafts_and_validates_in_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The designer-driven N:1 endpoint creates a single outcome and has no set
    to draft first, so the facade has to keep working with its old signature."""
    monkeypatch.setattr(ps, "complete_plo_synthesis", _fake_synthesis())
    set_soft_judge(monkeypatch)

    plo = await ps.synthesize_from_needs(META, [_need("N1", 0.9)], "cs-test", {"N1"}, "PLO7")

    assert plo is not None
    assert plo.plo_id == "PLO7"
    assert plo.source_need_ids == ["N1"]


async def test_a_draft_carries_the_authoritative_ids_before_it_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pin moved into draft_from_needs when the halves split. After the
    split the gate is no longer the only thing between the model's echo and the
    database, so the pin belongs where the draft is made."""

    async def echoes_a_wrong_id(model, messages, **kw):  # noqa: ANN001, ANN003
        draft = _draft_for("N1")
        draft.source_need_ids = ["WRONG-ID"]
        return ps._SingleDraftResponse(plo=draft)

    monkeypatch.setattr(ps, "complete_plo_synthesis", echoes_a_wrong_id)

    drafted = await ps.draft_from_needs(META, [_need("N1", 0.9)], "PLO1")

    assert drafted is not None
    assert drafted.source_need_ids == ["N1"]


async def test_the_draft_call_bounds_output_and_hidden_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GLM once wrote 131,072 tokens of looping JSON with no cap on this call."""
    seen: dict[str, object] = {}

    async def spy(model, messages, **kw):  # noqa: ANN001, ANN003
        seen.update(kw)
        return ps._SingleDraftResponse(plo=_draft_for("N1"))

    monkeypatch.setattr(ps, "complete_plo_synthesis", spy)

    await ps.draft_from_needs(META, [_need("N1", 0.9)], "PLO1")

    assert seen["max_tokens"] == 4096
    assert seen["reasoning_max_tokens"] == 1024


async def test_a_draft_failure_returns_none_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ps, "complete_plo_synthesis", AsyncMock(side_effect=RuntimeError("endpoint down"))
    )

    assert await ps.draft_from_needs(META, [_need("N1", 0.9)], "PLO1") is None


def test_a_sibling_summary_omits_what_the_validator_cannot_act_on() -> None:
    """Nine other outcomes' rationale and evidence trails are nine times the
    context for information the validator cannot use."""
    fields = set(ps.SiblingSummary.model_fields)

    assert fields == {"plo_id", "statement_th", "bloom_level", "is_optional", "source_need_ids"}
    assert "rationale_th" not in fields
    assert "source_evidence_ids" not in fields
    assert "smart_check" not in fields


async def test_validation_never_returns_none_for_a_failed_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An escalated PLO is kept for human repair, never dropped. None means the
    outcome could not be constructed at all."""
    monkeypatch.setattr(
        ps, "complete_plo_synthesis", AsyncMock(side_effect=RuntimeError("no repair available"))
    )
    set_soft_judge(monkeypatch)

    # A verb that is not in the statement: S_VERB fails and cannot be repaired.
    bad = ps._PLODraft(
        statement_th="ระบบสารสนเทศตามมาตรฐานอุตสาหกรรม",
        bloom_level=BloomLevel.CREATE,
        action_verb_th="ออกแบบ",
        source_need_ids=["N1"],
        rationale_th="เหตุผล",
    )
    plo = await ps.validate_and_build(
        bad,
        metadata=META,
        needs=[_need("N1", 0.9)],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
    )

    assert plo is not None
    assert plo.smart_escalated is True


async def test_the_agent_cannot_declare_a_hard_failure_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The load-bearing guarantee. The validator signs off on a statement that
    still contains a forbidden word, and pure code escalates it anyway —
    `hard_failures` runs on the final statement whatever the agent said, so the
    agent's influence is monotone: it can shrink the failure list, never declare
    it empty. Immutable rule 5 held by construction.
    """
    from tests.support.smart_agent import agent_verdict

    async def signs_off_on_anything(draft, ctx, metadata, **kw):  # noqa: ANN001, ANN003
        return agent_verdict(draft, diagnosis_th="ผ่านทุกเกณฑ์")

    monkeypatch.setattr(ps, "run_smart_agent", signs_off_on_anything)

    plo = await ps.validate_and_build(
        ps._PLODraft(
            statement_th="เข้าใจหลักการออกแบบระบบสารสนเทศ",
            bloom_level=BloomLevel.UNDERSTAND,
            action_verb_th="เข้าใจ",
            source_need_ids=["N1"],
            rationale_th="เหตุผล",
        ),
        metadata=META,
        needs=[_need("N1", 0.9)],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
    )

    assert plo is not None
    assert plo.smart_escalated is True, "the agent talked its way past the code gate"
    assert plo.smart_check.measurable is False
    # And the reason is recorded, not just logged — the gap the old gate left.
    assert [f.criterion.value for f in plo.smart_check.hard_findings] == ["M_forbidden"]
    assert plo.smart_diagnosis_th is not None
    assert "M_forbidden" in plo.smart_diagnosis_th


async def test_a_code_only_verdict_is_recorded_as_such(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "the agent judged this and it failed" and "the agent never ran" are
    different facts, and the UI must not attribute a diagnosis to something that
    never ran."""
    from curriculum_agent.stages.smart_agent import ValidationReason, code_only_result

    async def endpoint_down(draft, ctx, metadata, **kw):  # noqa: ANN001, ANN003
        return code_only_result(
            draft, ValidationReason.PROVIDER_ERROR, "ไม่ได้ตรวจ (เรียกผู้ตรวจไม่สำเร็จ)"
        )

    monkeypatch.setattr(ps, "run_smart_agent", endpoint_down)

    plo = await ps.validate_and_build(
        _draft_for("N1"),
        metadata=META,
        needs=[_need("N1", 0.9)],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
    )

    assert plo is not None
    assert plo.smart_validated_by == "code_only"
    assert plo.smart_escalated is False, "an agent that could not run must not escalate"
    assert plo.soft_flags == []


async def test_an_unbuildable_outcome_is_a_gap_not_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_evidence is not gated on escalation, so a Need with an empty
    evidence trail refuses at PLO construction — after the gate has passed it."""
    monkeypatch.setattr(ps, "complete_plo_synthesis", _fake_synthesis())
    set_soft_judge(monkeypatch)
    trail_less = _need("N1", 0.9).model_copy(update={"source_evidence_ids": []})

    plo = await ps.validate_and_build(
        _draft_for("N1"),
        metadata=META,
        needs=[trail_less],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
    )

    assert plo is None


@pytest.mark.parametrize("code", ["A_actor", "A_scope"])
async def test_actor_or_scope_failing_makes_the_outcome_not_achievable(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    """SMARTCheck keeps its five booleans — no migration, and every stored row
    still reads — so the two new verdicts fold into A. `passed` has to stop
    reporting success for an outcome the validator said is not a graduate's to
    achieve, while escalation still reads the hard failures alone."""
    from curriculum_agent.models import SmartFinding
    from curriculum_agent.smart_vocabulary import SmartFindingCode
    from tests.support.smart_agent import agent_verdict

    async def flags(draft, ctx, metadata, **kw):  # noqa: ANN001, ANN003
        return agent_verdict(
            draft,
            soft_findings=[
                SmartFinding(criterion=SmartFindingCode(code), severity="soft", note_th="x")
            ],
            diagnosis_th="ส่งกลับขั้น Need",
        )

    monkeypatch.setattr(ps, "run_smart_agent", flags)

    plo = await ps.validate_and_build(
        _draft_for("N1"),
        metadata=META,
        needs=[_need("N1", 0.9)],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
    )

    assert plo is not None
    assert plo.smart_check.achievable is False
    assert plo.smart_escalated is False
    assert plo.soft_flags == [code]


def test_every_adopted_draft_loses_the_graduate_prefix() -> None:
    """`_adopt` is the one place every draft enters — the first one and each
    repair — so the subject prefix is stripped there and cannot ship, however
    often a repair writes it back."""
    draft = ps._PLODraft(
        statement_th="บัณฑิตสามารถวิเคราะห์ระบบสารสนเทศสำหรับงาน N1 ได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        source_need_ids=["N1"],
        rationale_th="ทักษะที่ตลาดต้องการสำหรับ N1",
    )

    adopted = ps._adopt(draft, ["N1"])

    assert adopted.statement_th == "วิเคราะห์ระบบสารสนเทศสำหรับงาน N1 ได้"


async def test_a_plo_closed_at_the_budget_gets_the_code_disagrees_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verdict the agent produced at the budget is still the agent's: when code
    then escalates the PLO, the diagnosis says code disagreed."""
    from curriculum_agent.stages.smart_agent import ValidationReason
    from tests.support.smart_agent import agent_verdict

    async def closes_at_budget(draft, ctx, metadata, **kw):  # noqa: ANN001, ANN003
        return agent_verdict(
            draft, diagnosis_th="ปิดรอบ", reason=ValidationReason.FINISHED_AT_BUDGET
        )

    monkeypatch.setattr(ps, "run_smart_agent", closes_at_budget)

    plo = await ps.validate_and_build(
        ps._PLODraft(
            statement_th="เข้าใจหลักการออกแบบระบบสารสนเทศ",
            bloom_level=BloomLevel.UNDERSTAND,
            action_verb_th="เข้าใจ",
            source_need_ids=["N1"],
            rationale_th="เหตุผล",
        ),
        metadata=META,
        needs=[_need("N1", 0.9)],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
    )

    assert plo is not None
    assert plo.smart_escalated is True
    assert plo.smart_validated_by == "agent"
    assert plo.smart_diagnosis_th is not None
    assert plo.smart_diagnosis_th.startswith("โค้ดตรวจประโยคสุดท้ายแล้วยังไม่ผ่าน")
