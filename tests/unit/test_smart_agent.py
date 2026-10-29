"""The SMART validation agent: its budgets, its refusals, and the code gate.

Successor to `test_smart_retry_loop.py`. Every behaviour that file locked is
still pinned here, except the two that were assertions about the old gate's
internals rather than about what it guaranteed: the exact repair count and the
exact wording of a fix prompt. Those became the agent's business, and coupling
tests to them again is what forced this rewrite.

The loop is driven by scripting *tool intents* — ("get_need", {...}) — never
wire-format assistant turns. Each intent is executed against the real tools, so
a tool whose signature drifts fails the test. Assertions read
`fake.tools_called`, never `len(fake.calls) == 4`.
"""

from __future__ import annotations

from typing import Any

import pytest
from instructor.core.exceptions import IncompleteOutputException
from pydantic import ValidationError

from curriculum_agent.models import BloomLevel, Need, ProgramMetadata, StakeholderEvidence
from curriculum_agent.smart_vocabulary import SmartFindingCode
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages import smart_agent as sa
from curriculum_agent.stages.smart_agent_tools import (
    EvidenceIndex,
    SiblingSummary,
    ToolBudget,
    ValidationContext,
)

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


def _need(need_id: str = "N1") -> Need:
    return Need(
        need_id=need_id,
        program_id="cs-test",
        statement_th=f"ต้องการบัณฑิตที่ออกแบบระบบสารสนเทศสำหรับงาน {need_id} ได้",
        ksec_category="S",
        bloom_level=BloomLevel.CREATE,
        member_skill_ids=[f"S-{need_id}"],
        source_evidence_ids=[f"E-{need_id}"],
        freq=2,
        demand_score=0.8,
    )


def _draft(
    statement_th: str = "ออกแบบระบบสารสนเทศตามมาตรฐานอุตสาหกรรมได้",
    verb: str = "ออกแบบ",
    need_ids: list[str] | None = None,
) -> ps._PLODraft:
    return ps._PLODraft(
        statement_th=statement_th,
        bloom_level=BloomLevel.CREATE,
        action_verb_th=verb,
        source_need_ids=need_ids or ["N1"],
        rationale_th="ทักษะที่ตลาดต้องการ",
    )


class _FakeIndex:
    """An EvidenceIndex over in-memory rows."""

    def __init__(self, rows: list[StakeholderEvidence]) -> None:
        self._by_id = {r.evidence_id: r for r in rows}

    async def get(self, evidence_id: str) -> StakeholderEvidence | None:
        return self._by_id.get(evidence_id)


def _evidence(evidence_id: str = "E-N1", text: str = "ต้องการผู้ที่ออกแบบระบบได้") -> Any:
    return StakeholderEvidence(
        evidence_id=evidence_id,
        program_id="cs-test",
        stakeholder_type="employer",
        source_name="ประกาศรับสมัครงาน",
        raw_text_th=text,
    )


def _ctx(
    draft: ps._PLODraft | None = None,
    *,
    needs: list[Need] | None = None,
    siblings: list[SiblingSummary] | None = None,
    evidence: list[Any] | None = None,
) -> ValidationContext:
    draft = draft or _draft()
    needs = needs or [_need()]
    return ValidationContext(
        program_id="cs-test",
        plo_id="PLO1",
        draft=draft,
        authoritative_need_ids=tuple(n.need_id for n in needs),
        known_need_ids=frozenset(n.need_id for n in needs),
        needs_by_id={n.need_id: n for n in needs},
        cited_evidence_ids=frozenset(e for n in needs for e in n.source_evidence_ids),
        siblings=siblings or [],
        evidence_index=_FakeIndex(evidence if evidence is not None else [_evidence()]),  # type: ignore[arg-type]
        budget=ToolBudget(),
    )


class FakeToolModel:
    """A 'model' that plays a fixed script of tool intents, then a verdict.

    The script names tools and arguments, not assistant messages, so it survives
    a change to how the loop encodes a turn. Every intent runs against the real
    tool implementations over in-memory fixtures, which is the whole reason not
    to stub the tools.
    """

    def __init__(self, script: list[Any], closing: Any = None) -> None:
        self._script = list(script)
        # What the Finish-only closing call answers with: a Finish, an Exception
        # to raise, or None for "this fake has no closing answer" (it raises).
        self._closing = closing
        self.turns = 0
        self.tools_called: list[str] = []
        self.messages_seen: list[list[dict[str, Any]]] = []
        self.kwargs_seen: list[dict[str, Any]] = []

    async def __call__(self, response_model, messages, **kwargs):  # noqa: ANN001, ANN003
        self.messages_seen.append([dict(m) for m in messages])
        self.kwargs_seen.append(dict(kwargs))
        if response_model is sa.ClosingStep:
            if isinstance(self._closing, sa.Finish):
                return sa.ClosingStep(reasoning_th="หมดรอบ สรุปผล", action=self._closing)
            raise (
                self._closing if isinstance(self._closing, Exception) else RuntimeError("no close")
            )
        self.turns += 1
        step = self._script[min(self.turns - 1, len(self._script) - 1)]
        if isinstance(step, Exception):
            raise step
        if isinstance(step, sa.Finish):
            return sa.ValidationStep(reasoning_th="สรุปผล", action=step)
        if isinstance(step, sa.RequestRepair):
            return sa.ValidationStep(reasoning_th="ต้องแก้", action=step)
        tool, args = step
        self.tools_called.append(tool)
        return sa.ValidationStep(
            reasoning_th=f"ขอดู {tool}",
            action=sa.CallTool(kind="call_tool", tool=tool, **args),
        )


def _finish(**overrides: Any) -> sa.Finish:
    overrides.setdefault("diagnosis_th", "ตรวจแล้วผ่านทุกเกณฑ์")
    return sa.Finish(kind="finish", **overrides)


def _drive(
    monkeypatch: pytest.MonkeyPatch, script: list[Any], closing: Any = None
) -> FakeToolModel:
    fake = FakeToolModel(script, closing)
    monkeypatch.setattr(sa, "complete_validation", fake)
    return fake


# ---------------------- the loop's shape ----------------------


async def test_a_clean_draft_finishes_without_a_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behaviour 1 of the old file: a sound draft costs no repair and is not
    escalated."""
    fake = _drive(monkeypatch, [("check_hard", {}), _finish()])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.repair_count == 0
    assert result.reason is sa.ValidationReason.FINISHED
    assert result.soft_findings == []
    assert fake.tools_called == ["check_hard"]


async def test_a_soft_failure_is_flagged_and_never_escalates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behaviours 3, 6 and 8: soft verdicts reach the verdict, and no number of
    them blocks. Immutable rule 5."""
    _drive(
        monkeypatch,
        [
            ("check_hard", {}),
            _finish(
                specific_object_ok=False,
                measurable_ok=False,
                achievable_ok=False,
                relevant_needs_ok=False,
                time_bound_ok=False,
                findings_th={"A_level": "ระดับสูงเกินปริญญาตรี"},
                diagnosis_th="ทุกข้ออ่อน",
            ),
        ],
    )

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert set(result.soft_flags) == {
        "S_object",
        "M_assessable",
        "A_level",
        "R_needs",
        "T_horizon",
    }
    assert all(f.severity == "soft" for f in result.soft_findings)
    assert result.repair_count == 0


async def test_the_soft_verdicts_are_derived_from_the_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stored once, read two ways — so the booleans and the findings cannot
    disagree about the same criterion."""
    _drive(monkeypatch, [_finish(measurable_ok=False, diagnosis_th="วัดไม่ได้")])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.soft_verdicts == {
        "specific_object_ok": True,
        "measurable_ok": False,
        "achievable_ok": True,
        "actor_ok": True,
        "scope_ok": True,
        "relevant_needs_ok": True,
        "time_bound_ok": True,
    }


# ---------------------- repair handoff ----------------------


async def test_a_repair_is_written_by_the_plo_synthesis_model_not_the_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user's decision, and the sort of thing that regresses silently: the
    validator diagnoses, the Thai-first synthesis slot writes."""
    _drive(
        monkeypatch,
        [
            sa.RequestRepair(
                kind="request_repair",
                instruction_th="แทน 'ตระหนักถึง' ด้วยกริยาที่สังเกตได้",
                criteria=[SmartFindingCode.M_FORBIDDEN],
            ),
            _finish(),
        ],
    )
    repair_calls: list[Any] = []

    async def fake_repair(model, messages, **kw):  # noqa: ANN001, ANN003
        repair_calls.append(messages)
        return ps._SingleDraftResponse(plo=_draft("วิเคราะห์ความเสี่ยงของระบบได้", "วิเคราะห์"))

    monkeypatch.setattr(sa, "complete_plo_synthesis", fake_repair)

    bad = _draft("ตระหนักถึงความเสี่ยงของระบบ", "ตระหนัก")
    result = await sa.run_smart_agent(bad, _ctx(bad), META)

    assert len(repair_calls) == 1, "the repair went somewhere other than complete_plo_synthesis"
    assert result.statement_th == "วิเคราะห์ความเสี่ยงของระบบได้"
    assert result.repair_count == 1


async def test_the_repair_request_cannot_carry_a_thai_sentence() -> None:
    """The mechanism behind the rule, pinned as a schema fact. If the field
    existed, a helpful model would fill it in and "a repair is never answered by
    a different model than wrote the draft" would be one field away."""
    assert "statement_th" not in sa.RequestRepair.model_fields
    assert "statement_en" not in sa.RequestRepair.model_fields


async def test_a_repair_carries_the_new_verb_with_the_new_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rewrite that changes the verb in the sentence without changing
    action_verb_th fails S forever — the exact failure the old retry-loop tests
    were built around. The result carries a whole draft for this reason."""
    _drive(
        monkeypatch,
        [sa.RequestRepair(kind="request_repair", instruction_th="ใช้กริยาที่วัดได้"), _finish()],
    )

    async def fake_repair(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SingleDraftResponse(plo=_draft("ประเมินคุณภาพของระบบได้", "ประเมิน"))

    monkeypatch.setattr(sa, "complete_plo_synthesis", fake_repair)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.statement_th == "ประเมินคุณภาพของระบบได้"
    assert result.action_verb_th == "ประเมิน"


async def test_the_repair_call_bounds_output_and_hidden_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drive(
        monkeypatch,
        [
            sa.RequestRepair(
                kind="request_repair",
                instruction_th="แก้คำกริยา",
                criteria=[SmartFindingCode.M_FORBIDDEN],
            ),
            _finish(),
        ],
    )
    seen: dict[str, Any] = {}

    async def fake_repair(model, messages, **kw):  # noqa: ANN001, ANN003
        seen.update(kw)
        return ps._SingleDraftResponse(plo=_draft("ประเมินคุณภาพของระบบได้", "ประเมิน"))

    monkeypatch.setattr(sa, "complete_plo_synthesis", fake_repair)

    await sa.run_smart_agent(_draft(), _ctx(), META)

    assert seen["max_tokens"] == 4096
    assert seen["reasoning_max_tokens"] == 1024


async def test_a_repair_re_pins_the_evidence_trail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behaviour 4: the gate judges the ids that ship, not the model's echo. A
    replacement draft is a fresh object the model filled in, so the pin has to
    happen again."""
    _drive(
        monkeypatch,
        [sa.RequestRepair(kind="request_repair", instruction_th="แก้ประโยค"), _finish()],
    )

    async def echoes_a_wrong_id(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SingleDraftResponse(
            plo=_draft("วิเคราะห์ความเสี่ยงได้", "วิเคราะห์", need_ids=["WRONG-ID"])
        )

    monkeypatch.setattr(sa, "complete_plo_synthesis", echoes_a_wrong_id)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.source_need_ids == ["N1"]


async def test_the_repair_observation_shows_the_code_verdict_both_ways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handed only the new sentence, the validator has to trust its own reading
    of a criterion pure code just decided — and cannot tell a rewrite it likes
    from one that passes."""
    fake = _drive(
        monkeypatch,
        [sa.RequestRepair(kind="request_repair", instruction_th="แก้คำที่วัดไม่ได้"), _finish()],
    )

    async def fake_repair(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SingleDraftResponse(plo=_draft("วิเคราะห์ความเสี่ยงได้", "วิเคราะห์"))

    monkeypatch.setattr(sa, "complete_plo_synthesis", fake_repair)

    bad = _draft("เข้าใจความเสี่ยงของระบบ", "เข้าใจ")
    await sa.run_smart_agent(bad, _ctx(bad), META)

    observation = fake.messages_seen[-1][-1]["content"]
    assert "M_forbidden" in observation
    assert "->" in observation


# ---------------------- budgets and failure ----------------------


async def test_a_fourth_repair_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three, the SMART gate's long-standing policy. Refused rather than
    silently ignored, so the validator knows to finish."""
    fake = _drive(monkeypatch, [sa.RequestRepair(kind="request_repair", instruction_th="แก้อีก")])

    async def fake_repair(model, messages, **kw):  # noqa: ANN001, ANN003
        return ps._SingleDraftResponse(plo=_draft())

    monkeypatch.setattr(sa, "complete_plo_synthesis", fake_repair)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.repair_count == 3
    refusals = [
        m[-1]["content"] for m in fake.messages_seen if "ระบบปฏิเสธ" in m[-1].get("content", "")
    ]
    assert any("ไม่เกิน 3 รอบ" in r for r in refusals)


async def test_the_turn_budget_ends_the_loop_rather_than_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validator that never says finish must not be a stage that never
    returns — and must not manufacture an escalation on the way out."""
    _drive(monkeypatch, [("check_hard", {})])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.ran is False
    assert result.soft_findings == []
    assert result.reason in (
        sa.ValidationReason.TURN_BUDGET,
        sa.ValidationReason.REPAIR_BUDGET,
    )


async def test_the_closing_call_turns_an_exhausted_budget_into_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eight turns of tools and no finish used to discard every soft verdict. One
    Finish-only call after the budget keeps them, and the verdict is the agent's."""
    closing = _finish(
        measurable_ok=False, findings_th={"M_assessable": "วัดไม่ได้"}, diagnosis_th="ปิดรอบ"
    )
    fake = _drive(monkeypatch, [("check_hard", {})], closing=closing)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.reason is sa.ValidationReason.FINISHED_AT_BUDGET
    assert result.ran is True
    assert [f.criterion.value for f in result.soft_findings] == ["M_assessable"]
    assert result.turns == 8
    assert len(fake.messages_seen) == 9, "eight turns plus exactly one closing call"
    assert "finish" in fake.messages_seen[-1][-1]["content"]


async def test_a_failed_closing_call_falls_back_to_the_code_only_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _drive(monkeypatch, [("check_hard", {})], closing=RuntimeError("endpoint down"))

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.ran is False
    assert result.reason is sa.ValidationReason.TURN_BUDGET
    assert result.soft_findings == []
    assert len(fake.messages_seen) == 9


async def test_the_turns_left_note_appears_only_in_the_last_two_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _drive(monkeypatch, [("check_hard", {})])

    await sa.run_smart_agent(_draft(), _ctx(), META)

    note_seen = ["เหลืออีก" in m[-1]["content"] for m in fake.messages_seen[:8]]
    # messages_seen[i] is the conversation sent on turn i + 1.
    assert note_seen == [False, False, False, False, False, False, True, True]
    assert "เหลืออีก 2 รอบ" in fake.messages_seen[6][-1]["content"]
    assert "เหลืออีก 1 รอบ" in fake.messages_seen[7][-1]["content"]


async def test_a_provider_error_leaves_every_soft_verdict_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behaviour 7, and it matters more now: a dead judge used to cost flags, a
    dead agent would cost the whole gate. An agent that could not run must not
    produce findings."""
    _drive(monkeypatch, [RuntimeError("endpoint down")])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.ran is False
    assert result.reason is sa.ValidationReason.PROVIDER_ERROR
    assert result.soft_findings == []
    assert all(result.soft_verdicts.values())


async def test_the_kill_switch_skips_the_agent_without_calling_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ValidationReason.DISABLED` had no test and was unreachable in the
    bargain: the guard read `not validation_provider and not llm_provider`, and
    llm_provider is a Literal with no empty member, so the second half was
    never true. The documented kill switch ran the agent anyway.

    The assertion that matters is that no call is made -- a switch that still
    spends a provider call is not a switch."""
    from curriculum_agent.config import settings as live_settings

    monkeypatch.setattr(live_settings, "validation_provider", "")

    async def must_not_be_called(response_model, messages, **kwargs):  # noqa: ANN001, ANN003
        raise AssertionError("the agent ran with its provider switched off")

    monkeypatch.setattr(sa, "complete_validation", must_not_be_called)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.reason is sa.ValidationReason.DISABLED
    assert result.ran is False
    assert result.soft_findings == []
    assert all(result.soft_verdicts.values()), "a validator that did not run must not flag"


async def test_the_deadline_produces_a_code_only_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One stuck PLO must not hold the whole gather."""
    import asyncio

    async def never_answers(response_model, messages, **kwargs):  # noqa: ANN001, ANN003
        await asyncio.sleep(5)
        raise AssertionError("unreachable")

    monkeypatch.setattr(sa, "complete_validation", never_answers)
    monkeypatch.setattr(sa.settings, "validation_timeout_seconds", 1)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.reason is sa.ValidationReason.DEADLINE
    assert result.ran is False


async def test_a_repeated_tool_call_is_refused_without_spending_a_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeat is not progress, and re-running it spends a provider call to
    tell the model what it was already told."""
    fake = _drive(
        monkeypatch, [("get_need", {"need_id": "N1"}), ("get_need", {"need_id": "N1"}), _finish()]
    )
    ctx = _ctx()

    await sa.run_smart_agent(_draft(), ctx, META)

    refusals = [
        m[-1]["content"] for m in fake.messages_seen if "ระบบปฏิเสธ" in m[-1].get("content", "")
    ]
    assert any("อาร์กิวเมนต์เดิม" in r for r in refusals)


# ---------------------- what the validator may see ----------------------


async def test_evidence_the_plo_does_not_cite_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _drive(monkeypatch, [("get_evidence", {"evidence_id": "E-OTHER"}), _finish()])

    await sa.run_smart_agent(_draft(), _ctx(), META)

    observation = fake.messages_seen[-1][-1]["content"]
    assert "ไม่ได้อ้างถึงหลักฐาน" in observation


async def test_a_fourth_evidence_read_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap lives in the tool, not in a prompt asking nicely: the loop is the
    one place a prompt can accumulate the corpus one turn at a time, invisibly
    to the designer."""
    need = _need().model_copy(update={"source_evidence_ids": ["E1", "E2", "E3", "E4"]})
    fake = _drive(
        monkeypatch,
        [
            ("get_evidence", {"evidence_id": "E1"}),
            ("get_evidence", {"evidence_id": "E2"}),
            ("get_evidence", {"evidence_id": "E3"}),
            ("get_evidence", {"evidence_id": "E4"}),
            _finish(),
        ],
    )
    ctx = _ctx(needs=[need], evidence=[_evidence(f"E{i}") for i in range(1, 5)])

    await sa.run_smart_agent(_draft(), ctx, META)

    refusals = [m[-1]["content"] for m in fake.messages_seen if "ปฏิเสธ" in m[-1].get("content", "")]
    assert any("ไม่เกิน 3 รายการ" in r for r in refusals)


async def test_an_evidence_excerpt_says_that_it_is_an_excerpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without truncated/total_chars the validator reasons about a forty-page
    standard as if the first paragraph were all of it."""
    long_text = "ก" * 5000
    fake = _drive(monkeypatch, [("get_evidence", {"evidence_id": "E-N1"}), _finish()])

    await sa.run_smart_agent(_draft(), _ctx(evidence=[_evidence("E-N1", long_text)]), META)

    observation = fake.messages_seen[-1][-1]["content"]
    assert '"truncated": true' in observation
    assert '"total_chars": 5000' in observation
    assert observation.count("ก") <= 700


async def test_a_need_outside_this_plos_trail_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_need reads the context, never a repository — so it cannot reach a
    Need this PLO does not cite, let alone another program's."""
    fake = _drive(monkeypatch, [("get_need", {"need_id": "N9"}), _finish()])

    await sa.run_smart_agent(_draft(), _ctx(), META)

    observation = fake.messages_seen[-1][-1]["content"]
    assert "ไม่ได้อ้างถึง Need" in observation


async def test_the_validator_never_sees_the_designer_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behaviour 5, extended. The note reaches the draft prompt and nothing
    else; a validator that could read it could relay the wording into a repair
    instruction, and the note would arrive at a repair prompt second-hand."""
    fake = _drive(
        monkeypatch,
        [sa.RequestRepair(kind="request_repair", instruction_th="แก้ประโยค"), _finish()],
    )
    repair_messages: list[Any] = []

    async def fake_repair(model, messages, **kw):  # noqa: ANN001, ANN003
        repair_messages.append(messages)
        return ps._SingleDraftResponse(plo=_draft())

    monkeypatch.setattr(sa, "complete_plo_synthesis", fake_repair)
    note = "ขอให้เน้นคำว่านวัตกรรม"

    await sa.run_smart_agent(_draft(), _ctx(), META)

    every_message = [m["content"] for turn in fake.messages_seen for m in turn] + [
        m["content"] for messages in repair_messages for m in messages
    ]
    assert all(note not in content for content in every_message)
    assert "note_th" not in ValidationContext.__dataclass_fields__


async def test_a_sibling_is_never_its_own_sibling(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _drive(monkeypatch, [("list_sibling_plos", {}), _finish()])
    siblings = [
        SiblingSummary(
            plo_id=pid,
            statement_th=f"ผลลัพธ์ {pid}",
            bloom_level=BloomLevel.CREATE,
            is_optional=False,
            source_need_ids=[pid],
        )
        for pid in ("PLO1", "PLO2")
    ]

    await sa.run_smart_agent(_draft(), _ctx(siblings=siblings), META)

    observation = fake.messages_seen[-1][-1]["content"]
    assert "PLO2" in observation
    assert '"plo_id": "PLO1"' not in observation


async def test_the_need_statement_reaches_the_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behaviour 9, in its new form: the statement travels through get_need
    rather than being pasted into a prompt string."""
    fake = _drive(monkeypatch, [("get_need", {"need_id": "N1"}), _finish()])

    await sa.run_smart_agent(_draft(), _ctx(), META)

    observation = fake.messages_seen[-1][-1]["content"]
    assert "ออกแบบระบบสารสนเทศ" in observation


async def test_the_opening_prompt_names_the_need_ids_get_need_accepts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prompt used to list the Need sentences without their ids, which left
    `get_need` uncallable: a live agent passed a sentence as `need_id`, was
    refused, read the refusal as a broken evidence trail, and spent two repairs
    telling the writer to make the Thai cite a UUID.

    The ids come from the context rather than a parameter of their own, so the
    prompt cannot advertise a Need the tool would refuse."""
    fake = _drive(monkeypatch, [("check_hard", {}), _finish()])

    await sa.run_smart_agent(_draft(), _ctx(), META)

    opening = fake.messages_seen[0][-1]["content"]
    assert "N1" in opening
    assert "ออกแบบระบบสารสนเทศ" in opening


async def test_check_hard_reads_the_pure_function(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same function, never a reimplementation — and the need ids are not
    the validator's to override."""
    fake = _drive(monkeypatch, [("check_hard", {}), _finish()])
    bad = _draft("เข้าใจหลักการออกแบบระบบ", "เข้าใจ")

    await sa.run_smart_agent(bad, _ctx(bad), META)

    observation = fake.messages_seen[-1][-1]["content"]
    assert "M_forbidden" in observation
    assert '"passed": false' in observation


async def test_a_malformed_step_twice_ends_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Instructor has already re-asked by then. A third is a model that cannot
    answer the schema."""
    error = ValidationError.from_exception_data("ValidationStep", [])
    _drive(monkeypatch, [error, error])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.reason is sa.ValidationReason.MALFORMED
    assert result.ran is False


def _retry_exception(inner: Exception) -> Exception:
    """The exception a spent `max_retries` actually raises.

    Built rather than mocked because the classification under test is the class
    itself: instructor wraps the last ValidationError in this instead of
    re-raising it, and the wrapper is not a ValidationError.
    """
    from instructor.core.exceptions import FailedAttempt, InstructorRetryException

    return InstructorRetryException(
        inner,
        n_attempts=3,
        total_usage=0,
        failed_attempts=[FailedAttempt(attempt_number=1, exception=inner, completion=None)],
    )


def _truncated_json_error() -> ValidationError:
    """A cut-off completion, as Pydantic reports it. This is the live failure:
    the model's Thai ran past the completion limit and the JSON string never
    closed."""
    return ValidationError.from_exception_data(
        "ValidationStep",
        [
            {
                "type": "json_invalid",
                "loc": ("reasoning_th",),
                "input": '{"reasoning_th": "ผลลัพธ์',
                "ctx": {"error": "EOF while parsing a string at line 1 column 247"},
            }
        ],
    )


async def test_a_spent_retry_is_a_malformed_step_not_a_dead_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this pins: instructor raises InstructorRetryException, which
    subclasses InstructorError rather than ValidationError, so the loop caught
    it as a provider error and abandoned the verdict on the first bad step --
    `_MAX_MALFORMED` was unreachable. One live PLO in eight lost its agent
    verdict to a single truncated completion."""
    fake = _drive(
        monkeypatch,
        [_retry_exception(_truncated_json_error()), ("check_hard", {}), _finish()],
    )

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.ran is True, "a re-askable schema failure must not end the verdict"
    assert result.reason is sa.ValidationReason.FINISHED
    assert fake.turns == 3


async def test_two_spent_retries_end_as_malformed_not_as_a_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It still gives up -- on the budget, and under the reason that names what
    happened. `code_only` either way, but the diagnosis a designer reads
    differs."""
    error = _retry_exception(_truncated_json_error())
    _drive(monkeypatch, [error, error])

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.reason is sa.ValidationReason.MALFORMED
    assert result.ran is False
    assert result.soft_findings == []


async def test_every_step_bounds_its_own_completion_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thai costs several tokens per character and the JSON escapes each one,
    so an unbounded step is the truncation that produced the failure above."""
    fake = _drive(monkeypatch, [("check_hard", {}), _finish()])

    await sa.run_smart_agent(_draft(), _ctx(), META)

    assert fake.kwargs_seen, "no validation call was made"
    for kwargs in fake.kwargs_seen:
        assert kwargs.get("max_tokens") == sa._MAX_STEP_TOKENS


def test_the_malformed_log_line_names_the_reason() -> None:
    """`str(InstructorRetryException)` is the whole <failed_attempts> block, and
    reading the raw log body was the only way to tell a truncated completion
    from a schema the model could not satisfy."""
    reason = sa._schema_failure_reason(_retry_exception(_truncated_json_error()))

    assert "EOF while parsing a string" in reason
    assert "reasoning_th" in reason
    assert "failed_attempts" not in reason
    assert reason.count(chr(10)) == 0, "the reason has to fit on the log line"


def test_a_tool_call_missing_its_argument_is_a_schema_error() -> None:
    """Enforced on the model's own schema, so a miss is an Instructor re-ask
    rather than a dispatcher branch returning a string to interpret."""
    with pytest.raises(ValueError, match="requires 'need_id'"):
        sa.CallTool(kind="call_tool", tool="get_need")

    # check_hard needs nothing.
    assert sa.CallTool(kind="call_tool", tool="check_hard").tool.value == "check_hard"


async def test_the_evidence_index_reads_the_table_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ten concurrent validators citing overlapping evidence would otherwise be
    ten full-table reads: EvidenceRepository has no get_by_id."""
    calls = 0

    class OneShotRepo:
        async def list_by_program(self, program_id: str) -> list[Any]:
            nonlocal calls
            calls += 1
            return [_evidence("E1"), _evidence("E2")]

    index = EvidenceIndex("cs-test", OneShotRepo())  # type: ignore[arg-type]

    assert (await index.get("E1")) is not None
    assert (await index.get("E2")) is not None
    assert (await index.get("E9")) is None
    assert calls == 1


async def test_actor_and_scope_failures_are_soft_findings_under_a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Soft, like every interpreted verdict: they never escalate and never cost a
    repair on their own."""
    _drive(
        monkeypatch,
        [
            ("check_hard", {}),
            _finish(
                actor_ok=False,
                scope_ok=False,
                findings_th={
                    "A_actor": "ผู้กระทำคือหลักสูตร",
                    "A_scope": "เป็นงานพัฒนาโมเดล AI ไม่ใช่งานแปล",
                },
                diagnosis_th="ควรส่งกลับขั้น Need",
            ),
        ],
    )

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert set(result.soft_flags) == {"A_actor", "A_scope"}
    notes = {f.criterion.value: f.note_th for f in result.soft_findings}
    assert notes["A_scope"] == "เป็นงานพัฒนาโมเดล AI ไม่ใช่งานแปล"
    assert result.soft_verdicts["actor_ok"] is False
    assert result.soft_verdicts["scope_ok"] is False
    assert result.repair_count == 0


async def test_the_loop_hands_the_validator_the_programs_field_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prompt builder can carry the yardstick; this is what proves the loop
    passes it. Without the field line scope_ok has nothing to be judged against,
    and on a program with no scope_th — the common case — it would be a no-op."""
    fake = _drive(monkeypatch, [_finish()])
    scoped = META.model_copy(update={"scope_th": "หลักสูตรนี้ครอบคลุมการพัฒนาซอฟต์แวร์และระบบสารสนเทศ"})

    await sa.run_smart_agent(_draft(), _ctx(), scoped)

    opening = fake.messages_seen[0][1]["content"]
    assert "สาขาวิทยาการคอมพิวเตอร์" in opening
    assert "ขอบเขตวิชาชีพของหลักสูตร: หลักสูตรนี้ครอบคลุมการพัฒนาซอฟต์แวร์" in opening


# ---------------------- hidden reasoning ----------------------
#
# The validation model spends one max_tokens on hidden reasoning and on the
# answer. On stored OPT1 it reasoned for all 4,096 tokens and answered nothing,
# two runs out of two. Bounding reasoning on every step fixed that and cost the
# verdict: OPT8's A_scope flag held 4/4 with reasoning and 2/4 without. So the
# bound is applied only to a PLO whose step actually ran away.


class _RunawayOnce:
    """A validator that truncates on its first uncapped call, then behaves."""

    def __init__(self, script: list[Any]) -> None:
        self.inner = FakeToolModel(script)
        self.calls: list[int | None] = []
        self._ran_away = False

    async def __call__(self, response_model, messages, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append(kwargs.get("reasoning_max_tokens"))
        if kwargs.get("reasoning_max_tokens") is None and not self._ran_away:
            self._ran_away = True
            raise IncompleteOutputException(last_completion=None)
        return await self.inner(response_model, messages, **kwargs)


async def test_a_healthy_step_is_asked_with_reasoning_unbounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _drive(monkeypatch, [("check_hard", {}), _finish()])

    await sa.run_smart_agent(_draft(), _ctx(), META)

    assert all(k.get("reasoning_max_tokens") is None for k in fake.kwargs_seen)


async def test_a_step_that_ran_away_is_asked_again_with_reasoning_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The re-ask is the same step, so it costs no turn and is not malformed:
    nothing the model *answered* was wrong, it never answered."""
    fake = _RunawayOnce([("check_hard", {}), _finish()])
    monkeypatch.setattr(sa, "complete_validation", fake)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert fake.calls[0] is None
    assert fake.calls[1] is not None and fake.calls[1] < sa._MAX_STEP_TOKENS
    assert result.reason is sa.ValidationReason.FINISHED
    assert result.ran is True
    assert result.turns == 2


async def test_once_a_step_ran_away_the_rest_of_that_plo_stays_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The input that set it off is still in the conversation on the next turn.
    Going back to unbounded would spend another full step cap to rediscover it."""
    fake = _RunawayOnce([("check_hard", {}), ("bloom_lookup", {"verb_th": "ออกแบบ"}), _finish()])
    monkeypatch.setattr(sa, "complete_validation", fake)

    await sa.run_smart_agent(_draft(), _ctx(), META)

    assert fake.calls[0] is None
    assert all(c is not None for c in fake.calls[1:])
    assert len(fake.calls) == 4


async def test_a_step_truncated_even_when_bounded_is_malformed_not_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Then the answer itself is too long for the step cap. That is the model
    failing the schema, and it gets the malformed budget — not the provider-error
    path, which abandons the verdict on the first occurrence."""

    async def always_truncated(response_model, messages, **kwargs):  # noqa: ANN001, ANN003
        raise IncompleteOutputException(last_completion=None)

    monkeypatch.setattr(sa, "complete_validation", always_truncated)

    result = await sa.run_smart_agent(_draft(), _ctx(), META)

    assert result.reason is sa.ValidationReason.MALFORMED
