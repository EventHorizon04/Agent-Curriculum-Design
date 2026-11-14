"""The single agent's loop: one conversation, one system prompt, a handler per task.

Same shape as `smart_agent._run_judge` — instructor JSON mode, one step object with
a discriminated action, no native tool-calling — but long-running: it reads a whole
evidence corpus, so the loop manages its own context. Raw evidence text is the only
thing it drops from history (oldest first, replaced by the agent's own note), and
only when the last call's prompt-token count says the budget is crossed.

The loop knows nothing about Needs or PLOs. A `TaskHandler` supplies the opening
message, receives every output action and answers with the observation text, and
owns the `SingleToolContext` the tools read. The loop never calls an LLM wrapper
other than `complete_single_agent`, and single-agent calls are not cached.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Any, Literal, Protocol

from instructor.core.exceptions import IncompleteOutputException, InstructorRetryException
from loguru import logger
from pydantic import BaseModel, Field, ValidationError
from tenacity import AsyncRetrying, retry_if_not_exception_type, stop_after_attempt

from curriculum_agent.config import settings
from curriculum_agent.llm import complete_single_agent
from curriculum_agent.models import BloomLevel, KSECCategory
from curriculum_agent.prompts.single_agent import (
    build_closing_instruction,
    build_dropped_marker,
    build_observation,
    build_refusal,
    build_single_agent_system,
    build_turns_left_note,
)
from curriculum_agent.stages.single_agent_tools import (
    CallTool,
    SingleToolContext,
    ToolName,
    run_single_tool,
)
from curriculum_agent.stages.smart_agent import _schema_failure_reason
from curriculum_agent.stages.smart_agent_tools import call_fingerprint

__all__ = [
    "CallTool",
    "ToolName",
    "run_single_agent",
]

_MAX_MALFORMED = 2
# A save_plo step carries Thai statement, rationale and findings, which JSON
# escapes per character, and unbounded hidden reasoning spends the same budget:
# the other agents' steps are 8192 for that reason, not 4096.
_MAX_STEP_TOKENS = 8192
_MAX_REASONING_TOKENS = 1024
_STEP_ATTEMPTS = 2
_TURNS_LEFT_WARNING = 5
# Past this share of the window with nothing left to drop, the next call would not fit.
_CONTEXT_CEILING = 0.95
_STATE_DEPENDENT_TOOLS = frozenset({"list_sibling_plos", "get_need", "need_detail"})


class Note(BaseModel):
    kind: Literal["note"]
    evidence_id: str
    points_th: str = Field(min_length=1, max_length=1200)


class SaveNeed(BaseModel):
    kind: Literal["save_need"]
    need_id: str | None = None
    statement_th: str
    rationale_th: str = ""
    ksec_categories: list[KSECCategory] = Field(min_length=1)
    bloom_level: BloomLevel
    source_evidence_ids: list[str] = Field(min_length=1)


class DropNeed(BaseModel):
    kind: Literal["drop_need"]
    need_id: str


class SoftVerdict(BaseModel):
    """The agent's own, unvoted verdict on the seven soft criteria (true = passes)."""

    specific_object_ok: bool
    measurable_ok: bool
    achievable_ok: bool
    actor_ok: bool
    scope_ok: bool
    relevant_needs_ok: bool
    time_bound_ok: bool
    findings_th: dict[str, str] = Field(default_factory=dict)  # keys: soft codes


class SavePLO(BaseModel):
    kind: Literal["save_plo"]
    plo_ref: str | None = None
    statement_th: str
    statement_en: str | None = None
    action_verb_th: str
    bloom_level: BloomLevel
    source_need_ids: list[str] = Field(min_length=1, max_length=5)
    rationale_th: str
    soft: SoftVerdict


class DropPLO(BaseModel):
    kind: Literal["drop_plo"]
    plo_ref: str


class Finish(BaseModel):
    """Nothing here can clear a hard failure: that check is code, run again at the end."""

    kind: Literal["finish"]
    summary_th: str = ""


class SingleStep(BaseModel):
    """`reasoning_th` first: field order is schema order is generation order."""

    reasoning_th: str
    action: Annotated[
        CallTool | Note | SaveNeed | DropNeed | SavePLO | DropPLO | Finish,
        Field(discriminator="kind"),
    ]


class ClosingStep(BaseModel):
    """The call made when the loop must end: a `Finish`, no tool can be named."""

    reasoning_th: str
    action: Finish


OutputAction = Note | SaveNeed | DropNeed | SavePLO | DropPLO
# "malformed": the loop ended through the closing call after _MAX_MALFORMED malformed
# steps in a row, not because the agent finished.
StopReason = Literal["finished", "turn_cap", "timeout", "context_full", "malformed"]


class TaskHandler(Protocol):
    tool_ctx: SingleToolContext

    def opening_message(self) -> str: ...

    def handle(self, action: OutputAction) -> str:
        """Apply one output action; return the observation (acceptance or a refusal)."""
        ...

    def note_for(self, evidence_id: str) -> str | None: ...


class LoopOutcome(BaseModel):
    stop_reason: StopReason
    turns: int
    dropped_evidence_count: int
    opened_evidence_ids: list[str]


class History:
    """The messages, and which user messages are raw evidence text (the only droppable ones)."""

    def __init__(self, initial: list[dict[str, str]]) -> None:
        self._messages: list[dict[str, str]] = [dict(m) for m in initial]
        self._evidence_at: dict[int, str] = {}
        self._dropped: set[str] = set()
        # Ids whose text is out of history right now; a re-read puts it back.
        self._absent: set[str] = set()

    def messages(self) -> list[dict[str, str]]:
        return self._messages

    def total_chars(self) -> int:
        return sum(len(m["content"]) for m in self._messages)

    def add_assistant(self, step_json: str) -> None:
        self._messages.append({"role": "assistant", "content": step_json})

    def add_observation(self, text: str, *, evidence_id: str | None = None) -> None:
        if evidence_id is not None:
            self._evidence_at[len(self._messages)] = evidence_id
            self._absent.discard(evidence_id)
        self._messages.append({"role": "user", "content": text})

    def drop_oldest_evidence(self, marker_for: Callable[[str], str]) -> int | None:
        """Replace the oldest evidence text still in history; chars freed, None if none left."""
        if not self._evidence_at:
            return None
        index = min(self._evidence_at)
        evidence_id = self._evidence_at.pop(index)
        before = len(self._messages[index]["content"])
        self._messages[index]["content"] = marker_for(evidence_id)
        self._dropped.add(evidence_id)
        self._absent.add(evidence_id)
        return before - len(self._messages[index]["content"])

    def add_user_note(self, text: str) -> None:
        """Say something to the agent without two user messages in a row.

        A refusal after a malformed step, and the closing instruction, have no
        assistant turn of their own to answer; some OpenAI-compatible providers
        reject consecutive user messages, so the text is folded into the last user
        message. If that message is evidence text, a later drop takes the note
        with it, which is harmless: it only mattered for the next call.
        """
        if self._messages and self._messages[-1]["role"] == "user":
            self._messages[-1]["content"] += "\n" + text
        else:
            self._messages.append({"role": "user", "content": text})

    @property
    def dropped_evidence_ids(self) -> set[str]:
        """Every item whose text was ever dropped (the count the outcome reports)."""
        return self._dropped

    @property
    def absent_evidence_ids(self) -> set[str]:
        """Items whose text is out of history now, so a read of them is not a repeat."""
        return self._absent


def _step_retrying() -> AsyncRetrying:
    # A schema miss is worth one re-ask; a truncation is not (same as smart_agent).
    return AsyncRetrying(
        stop=stop_after_attempt(_STEP_ATTEMPTS),
        retry=retry_if_not_exception_type(IncompleteOutputException),
    )


class _State:
    """What the loop knows, outside the timeout scope so a timeout can still report it."""

    def __init__(self, history: History) -> None:
        self.history = history
        self.turns = 0
        self.opened: list[str] = []
        self.reasoning_bounded = False


async def _ask(response_model: type[Any], state: _State, sink: list[int]) -> Any:
    """One step. Hidden reasoning is bounded only after it ran away, as in smart_agent."""

    async def ask(reasoning_max_tokens: int | None) -> Any:
        return await complete_single_agent(
            response_model,
            state.history.messages(),
            max_retries=_step_retrying(),
            temperature=0,
            max_tokens=_MAX_STEP_TOKENS,
            reasoning_max_tokens=reasoning_max_tokens,
            usage_sink=sink,
        )

    if not state.reasoning_bounded:
        try:
            return await ask(None)
        except IncompleteOutputException:
            logger.warning(
                f"  single agent: hidden reasoning ran to the {_MAX_STEP_TOKENS}-token step "
                "cap with no answer — asking again with reasoning bounded"
            )
            state.reasoning_bounded = True
    return await ask(_MAX_REASONING_TOKENS)


def _with_turns_left(text: str, turn: int) -> str:
    left = settings.single_agent_max_turns - turn
    if 1 <= left <= _TURNS_LEFT_WARNING:
        return f"{text}\n{build_turns_left_note(left)}"
    return text


def _fingerprint(call: CallTool) -> str:
    # A get_evidence part is a different call from the same item's other part.
    evidence_id = f"{call.evidence_id}#{call.part}" if call.tool == "get_evidence" else None
    return call_fingerprint(
        call.tool,
        need_id=call.need_id,
        evidence_id=evidence_id,
        statement_th=call.statement_th,
        action_verb_th=call.action_verb_th,
        verb_th=call.verb_th,
    )


def _shrink_context(state: _State, handler: TaskHandler, prompt_tokens: int) -> bool:
    """Drop the oldest evidence text while the prompt is over budget.

    `prompt_tokens` is the real count of the call just made; each drop lowers it by
    the share of characters freed. Returns True when nothing is left to drop and the
    estimate is still past the ceiling — the next call would not fit.
    """
    window = settings.single_agent_context_window_tokens
    estimate = float(prompt_tokens)
    while estimate > settings.single_agent_context_budget_ratio * window:
        total = state.history.total_chars()
        freed = state.history.drop_oldest_evidence(
            lambda evidence_id: build_dropped_marker(evidence_id, handler.note_for(evidence_id))
        )
        if freed is None:
            break
        estimate -= estimate * max(freed, 0) / max(total, 1)
    return estimate > _CONTEXT_CEILING * window


async def _closing(state: _State) -> None:
    """The one extra Finish-only call. Its answer carries nothing to store."""
    state.history.add_user_note(build_closing_instruction())
    try:
        await _ask(ClosingStep, state, [])
    except Exception as exc:
        logger.warning(f"  single agent: closing call failed ({type(exc).__name__}): {exc}")


async def _run(handler: TaskHandler, state: _State) -> StopReason:
    history = state.history
    seen_calls: set[str] = set()
    malformed = 0
    for turn in range(1, settings.single_agent_max_turns + 1):
        state.turns = turn
        sink: list[int] = []
        try:
            step: SingleStep = await _ask(SingleStep, state, sink)
        except (InstructorRetryException, ValidationError, IncompleteOutputException) as exc:
            malformed += 1
            logger.warning(
                f"  single agent turn {turn}: malformed step ({malformed}/{_MAX_MALFORMED}): "
                f"{_schema_failure_reason(exc)}"
            )
            if malformed >= _MAX_MALFORMED:
                await _closing(state)
                return "malformed"
            history.add_user_note(_with_turns_left(build_refusal("รูปแบบคำตอบไม่ถูกต้อง"), turn))
            continue
        malformed = 0

        # The call just made saw the history as it was; shrink before adding to it.
        context_full = bool(sink) and _shrink_context(state, handler, sink[-1])
        history.add_assistant(step.model_dump_json(exclude_none=True))
        action = step.action

        if isinstance(action, Finish):
            return "finished"
        if isinstance(action, CallTool):
            text, evidence_id = _tool_observation(handler, state, seen_calls, action)
            history.add_observation(_with_turns_left(text, turn), evidence_id=evidence_id)
        else:
            history.add_observation(_with_turns_left(handler.handle(action), turn))
            # What these tools answer depends on what the handler holds, which
            # this action may have changed: asking again is not a repeat.
            seen_calls.difference_update(
                {c for c in seen_calls if c.split("\x00", 1)[0] in _STATE_DEPENDENT_TOOLS}
            )
        if context_full:
            logger.warning(f"  single agent turn {turn}: context full, nothing left to drop")
            return "context_full"

    state.turns = settings.single_agent_max_turns
    await _closing(state)
    return "turn_cap"


def _tool_observation(
    handler: TaskHandler, state: _State, seen_calls: set[str], call: CallTool
) -> tuple[str, str | None]:
    """(observation text, evidence id when the text is raw evidence)."""
    fingerprint = _fingerprint(call)
    rereading_dropped = (
        call.tool == "get_evidence" and call.evidence_id in state.history.absent_evidence_ids
    )
    if fingerprint in seen_calls and not rereading_dropped:
        return (
            build_refusal(f"เรียก {call.tool} ด้วยอาร์กิวเมนต์เดิมไปแล้ว — ใช้ข้อมูลที่มีหรือทำขั้นต่อไป"),
            None,
        )
    seen_calls.add(fingerprint)
    result = run_single_tool(handler.tool_ctx, call)
    if not result.ok:
        return build_refusal(result.error_th or ""), None
    if result.evidence_id is not None and result.evidence_id not in state.opened:
        state.opened.append(result.evidence_id)
    return build_observation(call.tool, result.payload_json), result.evidence_id


async def run_single_agent(handler: TaskHandler) -> LoopOutcome:
    """Run one task to a stop reason. LLM errors other than a malformed step propagate."""
    state = _State(
        History(
            [
                {"role": "system", "content": build_single_agent_system()},
                {"role": "user", "content": handler.opening_message()},
            ]
        )
    )
    reason: StopReason
    scope = asyncio.timeout(settings.single_agent_timeout_seconds)
    try:
        async with scope:
            reason = await _run(handler, state)
    except TimeoutError:
        # A provider's own timeout is an error, not this loop's budget.
        if not scope.expired():
            raise
        reason = "timeout"
    logger.info(
        f"  single agent: stop={reason} turns={state.turns} "
        f"opened={len(state.opened)} dropped={len(state.history.dropped_evidence_ids)}"
    )
    return LoopOutcome(
        stop_reason=reason,
        turns=state.turns,
        dropped_evidence_count=len(state.history.dropped_evidence_ids),
        opened_evidence_ids=state.opened,
    )
