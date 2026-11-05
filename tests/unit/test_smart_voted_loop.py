"""The voted loop: several judge runs per round, one repair per failed round.

`test_smart_agent.py` covers one run (tools, malformed steps, closing calls) at
`validation_runs=1`. Here the agent runs at its default of five, and the judge
model is a script of `Finish` verdicts consumed in call order, so each test names
exactly what every run said and asserts what the loop did with it: how many runs
it spent, whether it repaired, which statement it reports.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from curriculum_agent.prompts.smart_agent import (
    build_smart_agent_prompt,
    build_vote_repair_instruction_th,
)
from curriculum_agent.smart_vocabulary import SmartFindingCode
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages import smart_agent as sa
from tests.unit.test_smart_agent import META, _ctx, _draft, _finish, _need

_FAIL_M = {"measurable_ok": False, "findings_th": {"M_assessable": "วัดไม่ได้"}}


class ScriptedJudges:
    """A judge model whose Nth call answers with the Nth scripted entry.

    An entry is a `Finish`, or an exception to raise. The last entry repeats, so
    "everyone passes" is a one-element script. Every run here ends on its first
    turn, so one call is one run. Calls are counted, and the number of runs in
    flight at once is recorded for the semaphore test.
    """

    def __init__(self, script: list[Any], *, delay: float = 0.0) -> None:
        self._script = list(script)
        self._delay = delay
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.closing_calls = 0

    async def __call__(self, response_model, messages, **kwargs):  # noqa: ANN001, ANN003
        if response_model is sa.ClosingStep:
            self.closing_calls += 1
            raise RuntimeError("no closing answer scripted")
        entry = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            if isinstance(entry, Exception):
                raise entry
            return sa.JudgeStep(reasoning_th="สรุปผล", action=entry)
        finally:
            self.in_flight -= 1


class ScriptedRepairs:
    """The synthesis slot, as the repair sees it: returns the next scripted draft."""

    def __init__(self, drafts: list[Any]) -> None:
        self._drafts = list(drafts)
        self.messages: list[Any] = []

    async def __call__(self, model, messages, **kwargs):  # noqa: ANN001, ANN003
        self.messages.append(messages)
        draft = self._drafts[min(len(self.messages) - 1, len(self._drafts) - 1)]
        return ps._SingleDraftResponse(plo=draft)

    @property
    def calls(self) -> int:
        return len(self.messages)


def _judges(monkeypatch: pytest.MonkeyPatch, script: list[Any], **kw: Any) -> ScriptedJudges:
    judges = ScriptedJudges(script, **kw)
    monkeypatch.setattr(sa, "complete_validation", judges)
    return judges


def _repairs(monkeypatch: pytest.MonkeyPatch, *drafts: Any) -> ScriptedRepairs:
    repairs = ScriptedRepairs(list(drafts))
    monkeypatch.setattr(sa, "complete_plo_synthesis", repairs)
    return repairs


@pytest.fixture(autouse=True)
def _five_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sa.settings, "validation_runs", 5)

    async def no_repair_scripted(model, messages, **kwargs):  # noqa: ANN001, ANN003
        raise AssertionError("a repair was requested that the test did not script")

    monkeypatch.setattr(sa, "complete_plo_synthesis", no_repair_scripted)


_BETTER = _draft("ประเมินคุณภาพของระบบสารสนเทศได้", "ประเมิน")


# ---------------------- how many runs a round spends ----------------------


async def test_unanimous_pass_stops_after_three_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three agreeing runs out of five already fix every verdict: the other two
    could not change a majority, so they are not paid for."""
    judges = _judges(monkeypatch, [_finish()])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert judges.calls == 3
    assert result.ran is True
    assert result.soft_findings == []
    assert result.repair_count == 0
    assert result.reason is sa.ValidationReason.FINISHED


async def test_split_runs_all_five(monkeypatch: pytest.MonkeyPatch) -> None:
    """One dissent in the first three leaves the vote open, so the round runs
    the rest. Two of five is not a majority: nothing is flagged, nothing repaired."""
    judges = _judges(
        monkeypatch,
        [_finish(**_FAIL_M, diagnosis_th="วัดไม่ได้"), _finish(), _finish(), _finish(), _finish()],
    )

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert judges.calls == 5
    assert result.soft_findings == []
    assert result.repair_count == 0


async def test_validation_runs_one_single_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The kill switch for voting: threshold 1, a batch of 1, one call."""
    monkeypatch.setattr(sa.settings, "validation_runs", 1)
    judges = _judges(monkeypatch, [_finish()])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert judges.calls == 1
    assert result.ran is True


# ---------------------- the vote decides repair ----------------------


async def test_majority_soft_failure_triggers_one_repair_then_rejudge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pass_ = _finish()
    fail = _finish(**_FAIL_M, repair_hint_th="ระบุงานที่สังเกตได้", diagnosis_th="วัดไม่ได้")
    judges = _judges(monkeypatch, [fail, fail, fail, pass_])
    repairs = _repairs(monkeypatch, _BETTER)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert repairs.calls == 1
    # Round one: three failing runs decide it. Round two: three passing runs.
    assert judges.calls == 6
    assert result.repair_count == 1
    assert result.statement_th == _BETTER.statement_th
    assert result.soft_findings == [], "the repaired sentence was judged clean"
    instruction = repairs.messages[0][1]["content"]
    assert "M_assessable" in instruction
    assert "ระบุงานที่สังเกตได้" in instruction, "the representative's hint reaches the repair"


async def test_actor_scope_majority_is_not_repaired_but_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rewording cannot change who does the work or whose profession it is."""
    fail = _finish(
        actor_ok=False,
        scope_ok=False,
        findings_th={"A_actor": "ผู้กระทำคือสถาบัน", "A_scope": "งานของวิชาชีพอื่น"},
        diagnosis_th="ควรส่งกลับขั้น Need",
    )
    judges = _judges(monkeypatch, [fail])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert judges.calls == 3
    assert result.repair_count == 0
    assert set(result.soft_flags) == {"A_actor", "A_scope"}
    notes = {f.criterion.value: f.note_th for f in result.soft_findings}
    assert notes["A_actor"] == "ผู้กระทำคือสถาบัน"


async def test_a_finding_without_a_note_falls_back_to_the_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _judges(monkeypatch, [_finish(actor_ok=False, diagnosis_th="ผู้กระทำไม่ใช่บัณฑิต")])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert [f.note_th for f in result.soft_findings] == ["ผู้กระทำไม่ใช่บัณฑิต"]
    assert result.diagnosis_th == "ผู้กระทำไม่ใช่บัณฑิต"


async def test_allow_repair_false_judges_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A designer's own sentence is judged and never rewritten."""
    judges = _judges(monkeypatch, [_finish(**_FAIL_M, diagnosis_th="วัดไม่ได้")])
    bad = _draft("เข้าใจหลักการออกแบบระบบ", "เข้าใจ")  # a hard failure too

    result = await sa.run_smart_agent(bad, _ctx(bad), META, allow_repair=False)

    assert judges.calls == 3
    assert result.repair_count == 0
    assert result.statement_th == bad.statement_th
    assert result.soft_flags == ["M_assessable"]


async def test_max_three_repairs_four_judgings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three repairs, and the last of them is judged: four rounds of three runs."""
    judges = _judges(monkeypatch, [_finish(**_FAIL_M, diagnosis_th="วัดไม่ได้")])
    versions = [_draft(f"ออกแบบระบบสารสนเทศฉบับที่ {n} ได้", "ออกแบบ") for n in (1, 2, 3)]
    repairs = _repairs(monkeypatch, *versions)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert repairs.calls == 3
    assert judges.calls == 12
    assert result.repair_count == 3
    assert result.statement_th == versions[-1].statement_th
    assert result.soft_flags == ["M_assessable"]


# ---------------------- a round that could not vote ----------------------


async def test_too_few_runs_use_no_soft_verdicts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two of five runs answered and both found fault; three are needed for a
    vote. A verdict from a minority of the requested runs is not manufactured."""
    fail = _finish(**_FAIL_M, diagnosis_th="วัดไม่ได้")
    down = RuntimeError("endpoint down")
    judges = _judges(monkeypatch, [fail, down, down, fail, down])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert judges.calls == 5
    assert result.ran is False
    assert result.soft_findings == []
    assert result.repair_count == 0, "no vote and no hard failure: nothing drives a repair"


async def test_no_round_voted_is_code_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _judges(monkeypatch, [RuntimeError("endpoint down")])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.ran is False
    assert result.reason is sa.ValidationReason.PROVIDER_ERROR
    assert result.soft_findings == []
    assert all(result.soft_verdicts.values())


async def test_malformed_runs_everywhere_are_code_only_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = ValidationError.from_exception_data("JudgeStep", [])
    judges = _judges(monkeypatch, [error])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.ran is False
    assert result.reason is sa.ValidationReason.MALFORMED
    # Three failures out of five requested can no longer reach a vote of three,
    # so the round stops after its first batch; each run tried its one salvage call.
    assert judges.calls == 6
    assert judges.closing_calls == 3


async def test_a_hard_failure_drives_repair_even_when_no_round_voted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard failures are the code's, not the vote's: a dead judge endpoint does
    not stop the repair of a sentence code already knows is wrong."""
    _judges(monkeypatch, [RuntimeError("endpoint down")])
    repairs = _repairs(monkeypatch, _draft("วิเคราะห์ความเสี่ยงของระบบได้", "วิเคราะห์"))
    bad = _draft("เข้าใจความเสี่ยงของระบบ", "เข้าใจ")

    result = await sa.run_smart_agent(bad, _ctx(bad), META)

    assert repairs.calls == 1
    assert "M_forbidden" in repairs.messages[0][1]["content"]
    assert result.ran is False
    assert result.statement_th == "วิเคราะห์ความเสี่ยงของระบบได้"
    assert result.repair_count == 1


# ---------------------- decision 20 ----------------------


async def test_repair_adding_hard_failure_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rewrite that breaks something the old sentence did not is worse than no
    rewrite. It still costs a repair, and the unchanged sentence is not judged
    again: the loop goes straight to the next attempt."""
    judges = _judges(monkeypatch, [_finish(**_FAIL_M, diagnosis_th="วัดไม่ได้")])
    worse = _draft("เข้าใจความเสี่ยงของระบบ", "เข้าใจ")
    repairs = _repairs(monkeypatch, worse)
    original = _draft()

    result = await sa.run_smart_agent(original, _ctx(), META)

    assert repairs.calls == 3
    assert judges.calls == 3, "an unchanged statement is not re-judged"
    assert result.repair_count == 3
    assert result.statement_th == original.statement_th
    assert result.soft_flags == ["M_assessable"]


async def test_a_failed_repair_call_costs_a_repair_and_keeps_the_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judges = _judges(monkeypatch, [_finish(**_FAIL_M, diagnosis_th="วัดไม่ได้")])

    async def down(model, messages, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("synthesis endpoint down")

    monkeypatch.setattr(sa, "complete_plo_synthesis", down)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert judges.calls == 3
    assert result.repair_count == 3
    assert result.statement_th == _draft().statement_th


# ---------------------- the clock ----------------------


async def test_timeout_keeps_last_judged_statement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Round one voted and repaired; round two never answered. The statement the
    designer gets is the one a vote covered, not the unjudged rewrite."""
    fail = _finish(**_FAIL_M, diagnosis_th="วัดไม่ได้")
    calls = 0

    async def hangs_after_round_one(response_model, messages, **kwargs):  # noqa: ANN001, ANN003
        nonlocal calls
        calls += 1
        if calls > 3:
            await asyncio.sleep(10)
        return sa.JudgeStep(reasoning_th="สรุปผล", action=fail)

    monkeypatch.setattr(sa, "complete_validation", hangs_after_round_one)
    _repairs(monkeypatch, _BETTER)
    monkeypatch.setattr(sa.settings, "validation_timeout_seconds", 1)
    original = _draft()

    result = await sa.run_smart_agent(original, _ctx(), META)

    assert result.reason is sa.ValidationReason.DEADLINE
    assert result.ran is True
    assert result.statement_th == original.statement_th
    assert result.soft_flags == ["M_assessable"]
    assert result.repair_count == 1
    assert "(หมดเวลา — ใช้ผลตรวจรอบล่าสุด)" in (result.diagnosis_th or "")


# ---------------------- shared resources ----------------------


async def test_judge_runs_never_exceed_the_shared_concurrency_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three PLOs times five runs would be fifteen calls in flight; the semaphore
    is shared by every PLO on the loop, so it stays at the limit."""
    monkeypatch.setattr(sa.settings, "llm_max_concurrency", 2)
    judges = _judges(monkeypatch, [_finish()], delay=0.01)

    await asyncio.gather(*(sa.run_smart_agent(_draft(), _ctx(), META) for _ in range(3)))

    assert judges.calls == 9
    assert judges.max_in_flight == 2


async def test_each_judge_run_has_its_own_tool_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """A repeat-call refusal is per run. Run two asking for what run one asked
    for is not a repeat, so it must be answered rather than refused."""
    ctx = _ctx()

    async def asks_check_hard_then_finishes(response_model, messages, **kwargs):  # noqa: ANN001, ANN003
        user_turns = [m for m in messages if m["role"] == "user"]
        if len(user_turns) == 1:
            return sa.JudgeStep(
                reasoning_th="ตรวจ",
                action=sa.CallTool(kind="call_tool", tool="check_hard"),
            )
        assert "ระบบปฏิเสธ" not in user_turns[-1]["content"]
        return sa.JudgeStep(reasoning_th="สรุปผล", action=_finish())

    monkeypatch.setattr(sa, "complete_validation", asks_check_hard_then_finishes)

    result = await sa.run_smart_agent(_draft(), ctx, META)

    assert result.ran is True
    assert ctx.budget.seen_calls == set(), "the caller's budget is never touched"


# ---------------------- the code gate still has the last word ----------------------


async def test_hard_failure_still_escalates_via_validate_and_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Immutable rule 5. Every judge run passes every soft criterion and the
    repairs change nothing, so the vote is clean, and the PLO is escalated anyway:
    `hard_failures` on the shipped statement, not the vote, decides."""
    _judges(monkeypatch, [_finish()])
    bad = _draft("เข้าใจหลักการออกแบบระบบ", "เข้าใจ")
    _repairs(monkeypatch, bad)

    plo = await ps.validate_and_build(
        bad,
        metadata=META,
        needs=[_need()],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
    )

    assert plo is not None
    assert plo.smart_escalated is True
    assert plo.smart_validated_by == "agent"
    assert plo.soft_flags == []
    assert plo.smart_retry_count == 3


async def test_validate_and_build_passes_allow_repair_to_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bool] = []

    async def spy(draft, ctx, metadata, *, enabled=True, allow_repair=True):  # noqa: ANN001
        seen.append(allow_repair)
        return sa.code_only_result(draft, sa.ValidationReason.SKIPPED, "ทดสอบ")

    monkeypatch.setattr(ps, "run_smart_agent", spy)
    for allow in (True, False):
        await ps.validate_and_build(
            _draft(),
            metadata=META,
            needs=[_need()],
            program_id="cs-test",
            plo_id="PLO1",
            known_need_ids={"N1"},
            allow_repair=allow,
        )

    assert seen == [True, False]


# ---------------------- the prompts ----------------------


def test_judge_schema_has_no_request_repair() -> None:
    assert "request_repair" not in str(sa.JudgeStep.model_json_schema())
    system = build_smart_agent_prompt(
        statement_th="ออกแบบระบบได้",
        bloom_level="create",
        action_verb_th="ออกแบบ",
        degree_level="bachelor",
        duration_years=4,
        cited_needs=[("N1", "ต้องการ")],
        cited_evidence_ids=[],
        sibling_count=0,
    )[0]["content"]
    assert "request_repair" not in system
    assert "repair_hint_th" in system
    assert sa.Finish.model_fields["repair_hint_th"].default == ""


def test_repair_instruction_builder_caps_and_excludes() -> None:
    instruction = build_vote_repair_instruction_th(
        ["ประโยคต้องขึ้นต้นด้วย action_verb_th"],
        [
            (SmartFindingCode.M_ASSESSABLE.value, "วัดไม่ได้"),
            (SmartFindingCode.A_ACTOR.value, "ผู้กระทำคือสถาบัน"),
            (SmartFindingCode.A_SCOPE.value, "งานของวิชาชีพอื่น"),
        ],
        "ระบุงานที่สังเกตได้",
    )

    assert "ประโยคต้องขึ้นต้นด้วย action_verb_th" in instruction
    assert "M_assessable: วัดไม่ได้" in instruction
    assert "ระบุงานที่สังเกตได้" in instruction
    assert "A_actor" not in instruction
    assert "A_scope" not in instruction

    long = build_vote_repair_instruction_th(["ก" * 500], [("M_assessable", "ข" * 500)], "ค" * 400)
    assert len(long) <= 800
