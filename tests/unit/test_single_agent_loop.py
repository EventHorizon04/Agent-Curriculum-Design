from __future__ import annotations

import asyncio
from typing import Any

import pytest
from instructor.core.exceptions import InstructorRetryException

from curriculum_agent.models import StakeholderEvidence, StakeholderType
from curriculum_agent.stages import single_agent_loop as loop
from curriculum_agent.stages.single_agent_loop import (
    CallTool,
    ClosingStep,
    DropNeed,
    Finish,
    History,
    Note,
    SingleStep,
    run_single_agent,
)
from curriculum_agent.stages.single_agent_tools import SingleToolContext

E1_TEXT = "เนื้อหาหลักฐานหนึ่ง " * 40
E2_TEXT = "เนื้อหาหลักฐานสอง " * 40


def _evidence(evidence_id: str, text: str) -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id=evidence_id,
        program_id="p",
        stakeholder_type=StakeholderType.EMPLOYER,
        source_name="แหล่ง",
        raw_text_th=text,
    )


class FakeHandler:
    def __init__(self) -> None:
        self.tool_ctx = SingleToolContext(
            evidence_by_id={"e1": _evidence("e1", E1_TEXT), "e2": _evidence("e2", E2_TEXT)},
            needs_by_id={},
            plos=[],
            part_chars=6000,
        )
        self.handled: list[Any] = []
        self.notes: dict[str, str] = {}
        self.refusals: list[str] = []

    def opening_message(self) -> str:
        return "เปิดงาน"

    def handle(self, action: Any) -> str:
        self.handled.append(action)
        if isinstance(action, Note):
            self.notes[action.evidence_id] = action.points_th
        return "รับแล้ว"

    def note_for(self, evidence_id: str) -> str | None:
        return self.notes.get(evidence_id)

    def finish_refusal(self) -> str | None:
        return self.refusals.pop(0) if self.refusals else None


class FakeLLM:
    """Plays a script of actions; appends a scripted prompt-token count per call."""

    def __init__(self) -> None:
        self._script: list[Any] = []
        self._closing: Any = None
        self._tokens: list[int] = []
        self.calls = 0
        self.messages_seen: list[list[dict[str, str]]] = []
        self.kwargs_seen: list[dict[str, Any]] = []
        self.delay = 0.0

    def script(self, *steps: Any, tokens: list[int] | None = None) -> None:
        self._script = list(steps)
        self._tokens = list(tokens or [])

    def closing(self, step: Any) -> None:
        self._closing = step

    async def __call__(self, response_model: Any, messages: Any, **kwargs: Any) -> Any:
        self.messages_seen.append([dict(m) for m in messages])
        self.kwargs_seen.append(dict(kwargs))
        if self.delay:
            await asyncio.sleep(self.delay)
        if response_model is ClosingStep:
            if isinstance(self._closing, Exception):
                raise self._closing
            return ClosingStep(reasoning_th="หมดรอบ", action=self._closing or Finish(kind="finish"))
        index = self.calls
        self.calls += 1
        if index < len(self._tokens):
            kwargs["usage_sink"].append(self._tokens[index])
        step = self._script[min(index, len(self._script) - 1)]
        if isinstance(step, Exception):
            raise step
        return SingleStep(reasoning_th="คิด", action=step)


def _tool(tool: str, **args: Any) -> CallTool:
    return CallTool(kind="call_tool", tool=tool, **args)


def _note(evidence_id: str, points: str) -> Note:
    return Note(kind="note", evidence_id=evidence_id, points_th=points)


def _finish() -> Finish:
    return Finish(kind="finish", summary_th="จบ")


def _malformed() -> InstructorRetryException:
    return InstructorRetryException(
        "bad", n_attempts=2, total_usage=0, messages=[], create_kwargs={}
    )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    llm = FakeLLM()
    monkeypatch.setattr(loop, "complete_single_agent", llm)
    return llm


@pytest.fixture
def handler() -> FakeHandler:
    return FakeHandler()


def _user_text(messages: list[dict[str, str]]) -> str:
    return "\n".join(m["content"] for m in messages if m["role"] == "user")


async def test_reads_notes_and_finishes(fake: FakeLLM, handler: FakeHandler) -> None:
    fake.script(_tool("get_evidence", evidence_id="e1"), _note("e1", "ต้องการนักแปล"), _finish())
    out = await run_single_agent(handler)
    assert (out.stop_reason, out.turns, out.opened_evidence_ids) == ("finished", 3, ["e1"])
    assert handler.handled == [Note(kind="note", evidence_id="e1", points_th="ต้องการนักแปล")]
    first = fake.messages_seen[0]
    assert first[0]["role"] == "system" and first[1] == {"role": "user", "content": "เปิดงาน"}
    assert fake.kwargs_seen[0]["temperature"] == 0


async def test_refused_finish_continues_the_loop(fake: FakeLLM, handler: FakeHandler) -> None:
    handler.refusals = ["ยังมีหลักฐาน requirement ไม่มี Need อ้าง"]
    fake.script(_finish(), _finish())
    out = await run_single_agent(handler)
    assert (out.stop_reason, out.turns) == ("finished", 2)
    second_call = fake.messages_seen[1]
    assert "ระบบปฏิเสธ" in second_call[-1]["content"]
    assert "requirement" in second_call[-1]["content"]


async def test_outcome_keeps_one_record_per_turn(fake: FakeLLM, handler: FakeHandler) -> None:
    handler.refusals = ["ยังขาด Need"]
    fake.script(_tool("get_evidence", evidence_id="e1"), _malformed(), _finish(), _finish())
    out = await run_single_agent(handler)
    assert [s.turn for s in out.steps] == [1, 2, 3, 4]
    read, bad, refused, done = out.steps
    assert read.action == {
        "kind": "call_tool",
        "tool": "get_evidence",
        "evidence_id": "e1",
        "part": 1,
    }
    assert read.reasoning_th == "คิด" and len(read.observation) <= 240
    assert bad.action is None and bad.observation.startswith("malformed")
    assert refused.action == {"kind": "finish", "summary_th": "จบ"}
    assert "ยังขาด Need" in refused.observation
    assert done.observation == "finish accepted"


async def test_finish_on_the_last_turn_is_never_refused(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_max_turns", 1)
    handler.refusals = ["ปฏิเสธ"]
    fake.script(_finish())
    out = await run_single_agent(handler)
    assert (out.stop_reason, out.turns) == ("finished", 1)
    assert handler.refusals == ["ปฏิเสธ"]


async def test_turn_cap_makes_a_closing_call(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_max_turns", 2)
    fake.script(_tool("bloom_lookup", verb_th="วิเคราะห์"), _tool("bloom_lookup", verb_th="ประเมิน"))
    fake.closing(_finish())
    out = await run_single_agent(handler)
    assert (out.stop_reason, out.turns) == ("turn_cap", 2)
    assert len(fake.messages_seen) == 3


async def test_timeout_is_a_stop_reason_not_an_exception(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_timeout_seconds", 0.01)
    fake.delay = 1.0
    fake.script(_finish())
    out = await run_single_agent(handler)
    assert out.stop_reason == "timeout"


async def test_repeated_identical_tool_call_is_refused(fake: FakeLLM, handler: FakeHandler) -> None:
    fake.script(
        _tool("bloom_lookup", verb_th="วิเคราะห์"),
        _tool("bloom_lookup", verb_th="วิเคราะห์"),
        _finish(),
    )
    await run_single_agent(handler)
    assert "ระบบปฏิเสธ" in fake.messages_seen[-1][-1]["content"]
    assert "ผลของ bloom_lookup" in fake.messages_seen[-1][-3]["content"]


async def test_two_malformed_steps_then_closing(fake: FakeLLM, handler: FakeHandler) -> None:
    fake.script(_malformed(), _malformed())
    fake.closing(_finish())
    out = await run_single_agent(handler)
    assert out.stop_reason == "malformed"
    assert out.turns == 2
    assert "รูปแบบคำตอบไม่ถูกต้อง" in fake.messages_seen[1][-1]["content"]
    assert len(fake.messages_seen) == 3
    for seen in fake.messages_seen:
        roles = [m["role"] for m in seen]
        assert all(a != b for a, b in zip(roles, roles[1:], strict=False)), roles


async def test_one_malformed_step_is_tolerated(fake: FakeLLM, handler: FakeHandler) -> None:
    fake.script(_malformed(), _tool("bloom_lookup", verb_th="สร้าง"), _finish())
    out = await run_single_agent(handler)
    assert out.stop_reason == "finished" and out.turns == 3


async def test_provider_error_propagates(fake: FakeLLM, handler: FakeHandler) -> None:
    fake.script(RuntimeError("endpoint down"))
    with pytest.raises(RuntimeError):
        await run_single_agent(handler)


async def test_oldest_evidence_text_is_dropped_first_and_replaced_by_the_note(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_context_window_tokens", 1000)
    fake.script(
        _tool("get_evidence", evidence_id="e1"),
        _note("e1", "โน้ต e1"),
        _tool("get_evidence", evidence_id="e2"),
        _finish(),
        tokens=[100, 200, 900, 300],
    )
    out = await run_single_agent(handler)
    sent = fake.messages_seen[-1]
    assert out.dropped_evidence_count == 1
    assert not any(E1_TEXT in m["content"] for m in sent)
    assert any("โน้ต e1" in m["content"] for m in sent)
    assert any(E2_TEXT in m["content"] for m in sent)


async def test_a_dropped_item_may_be_read_again(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_context_window_tokens", 1000)
    fake.script(
        _tool("get_evidence", evidence_id="e1"),
        _note("e1", "โน้ต e1"),
        _tool("bloom_lookup", verb_th="สร้าง"),
        _tool("get_evidence", evidence_id="e1"),
        _finish(),
        tokens=[100, 200, 900, 300, 300],
    )
    await run_single_agent(handler)
    sent = fake.messages_seen[-1]
    assert any(E1_TEXT in m["content"] for m in sent)
    assert not any("ระบบปฏิเสธ" in m["content"] for m in sent)


async def test_an_item_never_dropped_cannot_be_read_twice(
    fake: FakeLLM, handler: FakeHandler
) -> None:
    fake.script(
        _tool("get_evidence", evidence_id="e1"),
        _tool("get_evidence", evidence_id="e1"),
        _finish(),
    )
    await run_single_agent(handler)
    assert "ระบบปฏิเสธ" in fake.messages_seen[-1][-1]["content"]


async def test_small_corpus_drops_nothing(fake: FakeLLM, handler: FakeHandler) -> None:
    fake.script(
        _tool("get_evidence", evidence_id="e1"),
        _note("e1", "โน้ต"),
        _finish(),
        tokens=[100, 200, 300],
    )
    out = await run_single_agent(handler)
    assert out.dropped_evidence_count == 0
    assert any(E1_TEXT in m["content"] for m in fake.messages_seen[-1])


async def test_context_full_when_nothing_is_left_to_drop(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_context_window_tokens", 1000)
    fake.script(_tool("bloom_lookup", verb_th="สร้าง"), _finish(), tokens=[990])
    out = await run_single_agent(handler)
    assert out.stop_reason == "context_full" and out.turns == 1


async def test_between_budget_and_ceiling_with_nothing_to_drop_goes_on(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_context_window_tokens", 1000)
    fake.script(_tool("bloom_lookup", verb_th="สร้าง"), _finish(), tokens=[800, 800])
    assert (await run_single_agent(handler)).stop_reason == "finished"


async def test_turns_left_note_is_appended_near_the_end(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_max_turns", 8)
    fake.script(
        *[_tool("bloom_lookup", verb_th=f"กริยา{i}") for i in range(8)],
    )
    fake.closing(_finish())
    await run_single_agent(handler)
    users = _user_text(fake.messages_seen[-1])
    assert "เหลืออีก 5 รอบ" in users and "เหลืออีก 6 รอบ" not in users


async def test_output_actions_go_to_the_handler(fake: FakeLLM, handler: FakeHandler) -> None:
    fake.script(DropNeed(kind="drop_need", need_id="N1"), _finish())
    await run_single_agent(handler)
    assert handler.handled == [DropNeed(kind="drop_need", need_id="N1")]
    assert fake.messages_seen[-1][-1]["content"] == "รับแล้ว"


def test_history_drops_oldest_evidence_and_reports_chars() -> None:
    history = History([{"role": "system", "content": "s"}])
    history.add_observation("ก" * 100, evidence_id="e1")
    history.add_observation("ข" * 100, evidence_id="e2")
    freed = history.drop_oldest_evidence(lambda eid: f"[{eid}]")
    assert freed == 100 - len("[e1]")
    assert history.dropped_evidence_ids == {"e1"}
    assert history.messages()[1]["content"] == "[e1]"
    assert history.drop_oldest_evidence(lambda eid: f"[{eid}]") is not None
    assert history.drop_oldest_evidence(lambda eid: f"[{eid}]") is None


async def test_a_provider_timeout_is_an_error_not_the_loop_budget(
    fake: FakeLLM, handler: FakeHandler
) -> None:
    fake.script(TimeoutError("provider"))
    with pytest.raises(TimeoutError):
        await run_single_agent(handler)


async def test_state_dependent_tool_may_be_asked_again_after_a_save(
    fake: FakeLLM, handler: FakeHandler
) -> None:
    fake.script(
        _tool("list_sibling_plos"),
        DropNeed(kind="drop_need", need_id="N1"),
        _tool("list_sibling_plos"),
        _finish(),
    )
    await run_single_agent(handler)
    assert "ระบบปฏิเสธ" not in _user_text(fake.messages_seen[-1])


async def test_state_dependent_tool_twice_with_no_save_between_is_refused(
    fake: FakeLLM, handler: FakeHandler
) -> None:
    fake.script(_tool("list_sibling_plos"), _tool("list_sibling_plos"), _finish())
    await run_single_agent(handler)
    assert "ระบบปฏิเสธ" in fake.messages_seen[-1][-1]["content"]


async def test_a_pure_tool_stays_refused_after_a_save(fake: FakeLLM, handler: FakeHandler) -> None:
    fake.script(
        _tool("bloom_lookup", verb_th="สร้าง"),
        DropNeed(kind="drop_need", need_id="N1"),
        _tool("bloom_lookup", verb_th="สร้าง"),
        _finish(),
    )
    await run_single_agent(handler)
    assert "ระบบปฏิเสธ" in fake.messages_seen[-1][-1]["content"]


async def test_a_reread_after_a_drop_is_allowed_once_then_refused(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_context_window_tokens", 1000)
    fake.script(
        _tool("get_evidence", evidence_id="e1"),
        _note("e1", "โน้ต e1"),
        _tool("bloom_lookup", verb_th="สร้าง"),
        _tool("get_evidence", evidence_id="e1"),
        _tool("get_evidence", evidence_id="e1"),
        _finish(),
        tokens=[100, 200, 900, 300, 300, 300],
    )
    await run_single_agent(handler)
    assert "ระบบปฏิเสธ" in fake.messages_seen[-1][-1]["content"]


async def test_a_step_on_the_context_full_turn_is_still_handled(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_context_window_tokens", 1000)
    fake.script(DropNeed(kind="drop_need", need_id="N1"), _finish(), tokens=[990])
    out = await run_single_agent(handler)
    assert out.stop_reason == "context_full"
    assert handler.handled == [DropNeed(kind="drop_need", need_id="N1")]


async def test_dropping_continues_across_items_until_under_budget(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop.settings, "single_agent_context_window_tokens", 1000)
    big = {f"e{i}": "ก" * 3000 for i in (1, 2, 3)}
    handler.tool_ctx.evidence_by_id = {k: _evidence(k, v) for k, v in big.items()}
    fake.script(
        _tool("get_evidence", evidence_id="e1"),
        _tool("get_evidence", evidence_id="e2"),
        _tool("get_evidence", evidence_id="e3"),
        _tool("bloom_lookup", verb_th="สร้าง"),
        _finish(),
        tokens=[100, 100, 100, 850, 100],
    )
    out = await run_single_agent(handler)
    sent = _user_text(fake.messages_seen[-1])
    assert out.dropped_evidence_count == 2
    assert big["e3"] in sent and "ถูกนำออกจากบริบท" in sent
    assert sent.count("ข้อความหลักฐาน e") == 2


def test_history_add_user_note_folds_into_a_user_message() -> None:
    history = History([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])
    history.add_user_note("n")
    assert [m["role"] for m in history.messages()] == ["system", "user"]
    assert history.messages()[1]["content"] == "u\nn"
    history.add_assistant("{}")
    history.add_user_note("m")
    assert history.messages()[-1] == {"role": "user", "content": "m"}


def _outage() -> InstructorRetryException:
    import httpx
    import openai

    request = httpx.Request("POST", "http://x/v1/chat/completions")
    cause = openai.RateLimitError(
        "slow down", response=httpx.Response(429, request=request), body=None
    )
    return InstructorRetryException(
        cause, n_attempts=2, total_usage=0, messages=[], create_kwargs={}
    )


async def test_provider_outage_is_not_a_malformed_step(fake: FakeLLM, handler: FakeHandler) -> None:
    fake.script(_outage(), _outage(), _finish())
    with pytest.raises(InstructorRetryException):
        await run_single_agent(handler)
    assert fake.calls == 1  # no re-ask, no closing call


async def test_schema_failures_still_count_as_malformed(
    fake: FakeLLM, handler: FakeHandler
) -> None:
    fake.script(_malformed(), _malformed())
    assert (await run_single_agent(handler)).stop_reason == "malformed"


def test_one_shot_overrides_replace_the_half_budgets(
    fake: FakeLLM, handler: FakeHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def go() -> Any:
        fake.script(*[_tool("bloom_lookup", verb_th=f"กริยา{i}") for i in range(6)])
        fake.closing(_finish())
        return await run_single_agent(handler, max_turns=3, timeout_seconds=50)

    out = asyncio.run(go())
    assert (out.stop_reason, out.turns) == ("turn_cap", 3)


async def test_every_part_of_dropped_evidence_can_be_reread(handler: FakeHandler) -> None:
    handler.tool_ctx.part_chars = 100
    history = History([{"role": "system", "content": "s"}])
    state = loop._State(history, 10)
    seen: set[str] = set()

    def read(part: int) -> str:
        text, eid = loop._tool_observation(
            handler, state, seen, _tool("get_evidence", evidence_id="e1", part=part)
        )
        history.add_observation(text, evidence_id=eid, part=part)
        return text

    read(1)
    read(2)
    history.drop_oldest_evidence(lambda eid: f"[{eid}]")
    history.drop_oldest_evidence(lambda eid: f"[{eid}]")
    assert "ระบบปฏิเสธ" not in read(1)
    assert "ระบบปฏิเสธ" not in read(2)
    assert "ระบบปฏิเสธ" in read(1)
