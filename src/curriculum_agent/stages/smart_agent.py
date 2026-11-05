"""The SMART validation agent: voted judge runs, and a repair loop around them.

**Judge, vote, repair.** One PLO is judged several times (`validation_runs`,
default 5) by independent tool-using runs, each ending in a `Finish`. A soft
criterion counts as failed only when a majority of the successful runs failed it
(`smart_vote`, pure code), because the same model at temperature 0 still answers
differently from run to run. A run never asks for a repair: it reports verdicts, a
diagnosis and a short `repair_hint_th`. When the code found a hard failure or the
vote found a repairable soft one, *this module* builds one instruction from the
code's hints plus the majority's findings and gets `complete_plo_synthesis` to
rewrite the sentence, then judges the new sentence again, up to
`validation_max_repairs` times. `validation_runs=1` is the single-run agent.

**Why a structured action loop rather than native tool-calling.** Instructor is
wired in `Mode.JSON` for every slot (`llm._get_client`), and reading a
`tool_calls` envelope would mean dropping to the raw client and hand-parsing
JSON — which this project forbids — or keying the client cache on `(provider,
mode)`, changing the one function all five slots share for the benefit of one.
It would also tie the loop to providers that implement tool-calling, when every
provider field accepts `None` to mean "follow LLM_PROVIDER" and running the
whole pipeline on one endpoint is a supported arrangement. So the model answers
with a step object carrying a discriminated action, the loop executes it, and
the result goes back as the next user turn. A malformed action is then a
Pydantic `ValidationError`, which Instructor re-asks with the error attached.

**What keeps immutable rule 5 intact.** Three things, and none of them are
conventions the agent could talk its way past:

1. `Finish` carries soft verdicts, a diagnosis and a repair hint. It has no field
   that can clear a hard failure, and `check_hard` is a *read* of the pure
   function whose result is never retained as the verdict. Hard failures drive
   repair from `hard_failures` directly; no vote can remove one.
2. `validate_and_build` runs `hard_failures` on the final statement after this
   loop returns, whatever way it returned, and that call decides `escalated`.
   The agent's only causal route to the outcome is getting `complete_plo_synthesis`
   to write a better sentence, which code then re-judges — so its power is
   monotone: it can shrink the failure list, never declare it empty. A repair
   that introduces a hard failure the previous sentence did not have is discarded.
3. A repair is written by the synthesis slot, never here. `Finish` has no
   statement field, so the Thai a designer submits to MHESI still comes from the
   slot that wrote the draft.
"""

from __future__ import annotations

import asyncio
import dataclasses
import weakref
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeVar

from instructor.core.exceptions import IncompleteOutputException, InstructorRetryException
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, model_validator
from tenacity import AsyncRetrying, retry_if_not_exception_type, stop_after_attempt

from curriculum_agent.config import settings
from curriculum_agent.llm import complete_plo_synthesis, complete_validation
from curriculum_agent.models import ProgramMetadata, SmartFinding
from curriculum_agent.prompts.program_context import build_program_context_th
from curriculum_agent.prompts.smart_agent import (
    build_agent_repair_prompt,
    build_closing_after_malformed_instruction,
    build_closing_instruction,
    build_refusal_observation,
    build_smart_agent_prompt,
    build_tool_observation,
    build_turns_left_note,
    build_vote_repair_instruction_th,
)
from curriculum_agent.smart_vocabulary import HARD_CODES, SmartFindingCode
from curriculum_agent.stages.smart_agent_tools import (
    TOOL_REQUIRED_ARG,
    ToolBudget,
    ValidationContext,
    call_fingerprint,
    run_tool,
)
from curriculum_agent.stages.smart_rules import CRITERION_FIX_HINTS_TH, hard_failures
from curriculum_agent.stages.smart_vote import (
    SOFT_VERDICTS,
    JudgeRun,
    SoftVote,
    first_batch_size,
    is_decided,
    repairable,
    vote,
)

# Consecutive malformed steps before the loop gives up. Instructor has already
# re-asked twice by then, so a third is a model that cannot answer the schema.
_MAX_MALFORMED = 2

# Ceiling on one step's completion. Sized for the largest step the schema
# allows — a Finish carrying `diagnosis_th` plus a note per finding — and
# generous because Thai is expensive to generate: a llama tokenizer spends
# several tokens per Thai character, and the JSON these models emit escapes
# each one as a \uXXXX sequence, so the 800-character `reasoning_th` bound is
# worth thousands of tokens on its own. A live run truncated mid-string 38 Thai
# characters in ("EOF while parsing a string at line 1 column 247"), which
# costs the whole verdict for that PLO. The ceiling is cheap because it caps
# what may be generated, not what is billed.
_MAX_STEP_TOKENS = 4096

# Output and hidden-reasoning caps for the PLO draft call (plo_synthesis) and the
# repair call below. Defined here because plo_synthesis already imports this
# module, so the reverse import would be a cycle. Without a cap GLM looped while
# writing the JSON and produced 131,072 completion tokens (finish_reason='length',
# reasoning_tokens=0); Instructor retried twice more and the stage took 77 minutes.
PLO_MAX_TOKENS = 4096
PLO_REASONING_MAX_TOKENS = 1024

# Ceiling on one step's *hidden* reasoning, used only after a step ran away. The
# validation model on OpenRouter spends one max_tokens on reasoning and answer
# alike, and nothing stops the first from taking all of it: on stored OPT1 it
# reasoned for 4,096 tokens (about 12,000 characters) and returned no content,
# two runs out of two, for a step whose answer was "call check_hard". Given
# 16,000 it stopped at 5,715. The step failed as malformed, the loop gave up,
# and the verdict fell to code_only — which drops every soft criterion. On
# healthy turns the same model reasoned for 22 to 335 tokens.
#
# Bounding it on every step was tried first and measured worse. With the bound
# set this endpoint reports 0 reasoning tokens — it behaves as off, whatever the
# number — and the judgement loosened with it: OPT8's out-of-scope flag, which
# held 4/4 with reasoning, held 2/4 without. So `_ask_step` asks unbounded, and
# bounds only a PLO whose step came back truncated. A cap rather than `effort`
# because it is correct whether or not the provider honours the number.
_MAX_REASONING_TOKENS = 1024

# Two attempts, as before, for a schema miss — instructor re-asks with the
# validation error quoted, which is worth a call. Not for a truncation: its
# default policy retries every exception, so a runaway step spent the full step
# cap twice (141 seconds on OPT1's first turn) and still reached the loop
# truncated. A blind retry cannot fix a runaway; bounding reasoning can, and
# only the loop can decide to do that. Built per call because tenacity's
# Retrying objects carry state.
_STEP_ATTEMPTS = 2

# Turns remaining at or below which each observation says so.
_TURNS_LEFT_WARNING = 2


def _step_retrying() -> AsyncRetrying:
    return AsyncRetrying(
        stop=stop_after_attempt(_STEP_ATTEMPTS),
        retry=retry_if_not_exception_type(IncompleteOutputException),
    )


_StepT = TypeVar("_StepT", bound=BaseModel)


async def _ask_step(
    messages: list[dict[str, Any]],
    ctx: ValidationContext,
    response_model: type[_StepT],
) -> _StepT:
    """One validation step, with hidden reasoning bounded only once it ran away.

    A truncation on an unbounded step is re-asked at once with reasoning bounded,
    inside the same turn: the model never answered, so nothing it said was
    malformed, and the input that set it off is still there — so the bound stays
    for the rest of this PLO. A truncation on a bounded step propagates; the
    answer itself outgrew the step cap, and the loop treats that as malformed.
    """

    async def ask(reasoning_max_tokens: int | None) -> _StepT:
        return await complete_validation(
            response_model,
            messages,
            max_retries=_step_retrying(),
            temperature=0,
            max_tokens=_MAX_STEP_TOKENS,
            reasoning_max_tokens=reasoning_max_tokens,
        )

    if not ctx.budget.reasoning_bounded:
        try:
            return await ask(None)
        except IncompleteOutputException:
            logger.warning(
                f"  SMART agent {ctx.plo_id}: hidden reasoning ran to the "
                f"{_MAX_STEP_TOKENS}-token step cap with no answer — asking again "
                f"with reasoning bounded for the rest of this PLO"
            )
            ctx.budget.reasoning_bounded = True
    return await ask(_MAX_REASONING_TOKENS)


def _schema_failure_reason(exc: Exception, *, limit: int = 240) -> str:
    """The one line worth logging out of a step that failed validation.

    `str(InstructorRetryException)` is the entire `<failed_attempts>` block --
    every attempt, every message, the whole offending input value -- which
    loguru prints as a wall of text that does not say why the step failed. It
    took reading the raw log body to find that a live failure was a truncated
    completion rather than a schema the model could not satisfy, so the reason
    belongs in the line itself.

    The underlying error is the first constructor argument (instructor chains
    `from` the tenacity RetryError, so `__cause__` is not it) and its first
    Pydantic error message is the answer: a cut-off completion reads "Invalid
    JSON: EOF while parsing a string", a real schema miss names the field.
    """
    inner: Any = exc
    if isinstance(exc, InstructorRetryException):
        attempts = getattr(exc, "failed_attempts", None)
        if attempts:
            inner = attempts[-1].exception
        elif exc.args:
            inner = exc.args[0]
    if isinstance(inner, ValidationError) and inner.errors():
        first = inner.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ())) or "response"
        return f"{where}: {first.get('msg', '')}"[:limit]
    text = str(inner).strip()
    return text.splitlines()[0][:limit] if text else type(inner).__name__


class ValidationReason(StrEnum):
    """Why the loop stopped. Reported, logged, and folded into the diagnosis.

    FINISHED_AT_BUDGET, FINISHED_AFTER_MALFORMED and REPAIR_BUDGET are no longer
    produced: a voted result has no single run to attribute them to. They stay
    because `validate_and_build` and older tests branch on them, and a member
    removed here would be one more place an old stored value could not be read.
    """

    FINISHED = "finished"
    # The turns ran out and one Finish-only call still produced the verdict.
    FINISHED_AT_BUDGET = "finished_at_budget"
    # Malformed steps ran out and one Finish-only call still produced the verdict.
    FINISHED_AFTER_MALFORMED = "finished_after_malformed"
    TURN_BUDGET = "turn_budget"
    REPAIR_BUDGET = "repair_budget"
    PROVIDER_ERROR = "provider_error"
    MALFORMED = "malformed"
    DEADLINE = "deadline"
    DISABLED = "disabled"
    SKIPPED = "skipped"


class ValidationToolName(StrEnum):
    GET_NEED = "get_need"
    GET_EVIDENCE = "get_evidence"
    CHECK_HARD = "check_hard"
    BLOOM_LOOKUP = "bloom_lookup"
    LIST_SIBLING_PLOS = "list_sibling_plos"


class CallTool(BaseModel):
    """One tool call.

    A single flat argument bag rather than a nested union per tool: the model
    answers in JSON mode with no tool-use training, and one level of anyOf is
    already the most it handles reliably.
    """

    kind: Literal["call_tool"]
    tool: ValidationToolName
    need_id: str | None = None
    evidence_id: str | None = None
    statement_th: str | None = Field(default=None, max_length=500)
    action_verb_th: str | None = Field(default=None, max_length=60)
    verb_th: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def _require_the_named_tools_argument(self) -> CallTool:
        """Enforced on the schema, so a miss is an Instructor re-ask rather than
        a branch in the dispatcher returning an error string the model has to
        interpret."""
        required = TOOL_REQUIRED_ARG[self.tool.value]
        if required is not None and not getattr(self, required):
            raise ValueError(f"tool '{self.tool.value}' requires '{required}'")
        return self


class Finish(BaseModel):
    """One judge run's verdict. Soft only — nothing here can clear a hard failure.

    `repair_hint_th` says what to change, never a sentence: there is no statement
    field on purpose. If there were, a helpful model would fill it in and "a repair
    is never answered by a different model than wrote the draft" would be one
    field away from false. The Thai sentence is written by `complete_plo_synthesis`.
    """

    kind: Literal["finish"]
    specific_object_ok: bool = True
    measurable_ok: bool = True
    achievable_ok: bool = True
    actor_ok: bool = True
    scope_ok: bool = True
    relevant_needs_ok: bool = True
    time_bound_ok: bool = True
    findings_th: dict[str, str] = Field(default_factory=dict)
    diagnosis_th: str = Field(min_length=1, max_length=600)
    repair_hint_th: str = Field(default="", max_length=400)


class JudgeStep(BaseModel):
    """One turn of a judge run. `reasoning_th` comes first on purpose: field order
    is schema order is generation order, so the model reasons before it commits.

    No repair action is offered: a repair is decided from the vote, not by one run.
    """

    reasoning_th: str = Field(min_length=1, max_length=800)
    action: Annotated[CallTool | Finish, Field(discriminator="kind")]


class ClosingStep(BaseModel):
    """The call made when the turns are spent: a `Finish` and nothing else.

    No tool can be named, so the schema, not the prompt, is what stops the model
    spending the extra call on more work.
    """

    reasoning_th: str = Field(min_length=1, max_length=800)
    action: Finish


class SmartAgentResult(BaseModel):
    """What the loop hands back.

    Carries a whole replacement draft, not a bare statement. A repair that
    changes the verb in the sentence without changing `action_verb_th` fails S
    forever — which is the exact failure the retry-loop tests were written
    around — so the two must travel together.
    """

    model_config = {"extra": "forbid"}

    statement_th: str
    statement_en: str | None
    bloom_level: Any
    action_verb_th: str
    rationale_th: str
    distinctive_feature_th: str | None
    source_need_ids: list[str]
    soft_findings: list[SmartFinding] = Field(default_factory=list)
    diagnosis_th: str | None = None
    repair_count: int = 0
    turns: int = 0
    reason: ValidationReason = ValidationReason.FINISHED
    ran: bool = True

    @property
    def soft_flags(self) -> list[str]:
        return [f.criterion.value for f in self.soft_findings]

    @property
    def soft_verdicts(self) -> dict[str, bool]:
        """One boolean per soft verdict, derived from the findings so the two cannot drift."""
        failed = {f.criterion for f in self.soft_findings}
        return {field: code not in failed for field, code in SOFT_VERDICTS}


def _result_from_draft(draft: Any, **overrides: Any) -> SmartAgentResult:
    return SmartAgentResult(
        statement_th=draft.statement_th,
        statement_en=draft.statement_en,
        bloom_level=draft.bloom_level,
        action_verb_th=draft.action_verb_th,
        rationale_th=draft.rationale_th,
        distinctive_feature_th=draft.distinctive_feature_th,
        source_need_ids=list(draft.source_need_ids),
        **overrides,
    )


def code_only_result(
    draft: Any,
    reason: ValidationReason,
    note_th: str,
    *,
    repair_count: int = 0,
    turns: int = 0,
) -> SmartAgentResult:
    """The verdict when the agent could not run, or could not finish.

    Every soft verdict stays true and no flag is manufactured. An agent that
    could not run must not produce findings — the same discipline the light
    soft judge had, now covering the whole gate. `ran=False` is what lets the
    caller record `code_only` rather than claim an agent judged this.

    It still carries the repairs and turns that did happen: a PLO that spent
    three repairs and then ran out of turns has been rewritten three times, and
    reporting zero would hide that from the designer reading the count.
    """
    return _result_from_draft(
        draft,
        diagnosis_th=note_th,
        reason=reason,
        ran=False,
        soft_findings=[],
        repair_count=repair_count,
        turns=turns,
    )


async def _repair(
    draft: Any,
    instruction_th: str,
    criteria: Sequence[str],
    ctx: ValidationContext,
    metadata: ProgramMetadata,
) -> Any | None:
    """Ask the synthesis slot for a replacement sentence.

    Returns the adopted draft, or None when the call failed. Whether the new
    sentence is *better* is not decided here: the caller compares the code's
    verdict on the two (decision 20) and the next judge round reads it.
    """
    from curriculum_agent.stages.plo_synthesis import _adopt, _SingleDraftResponse

    try:
        fixed = await complete_plo_synthesis(
            _SingleDraftResponse,
            build_agent_repair_prompt(
                statement_th=draft.statement_th,
                bloom_level=draft.bloom_level.value,
                action_verb_th=draft.action_verb_th,
                degree_level=metadata.degree_level,
                instruction_th=instruction_th,
                criteria=list(criteria),
                keep_th=None,
            ),
            max_retries=2,
            max_tokens=PLO_MAX_TOKENS,
            reasoning_max_tokens=PLO_REASONING_MAX_TOKENS,
        )
    except Exception as exc:
        logger.warning(f"  SMART agent {ctx.plo_id}: repair call failed: {exc}")
        return None

    # Re-pinned immediately: the gate judges the ids that will ship, and a
    # replacement draft is a fresh object the model filled in.
    return _adopt(fixed.plo, list(ctx.authoritative_need_ids))


def _corrected_unjudged(progress: _Progress, ctx: ValidationContext) -> bool:
    """True when the current draft was never voted on but has strictly fewer hard
    failures than the last judged one.

    Decision 20 guarantees the current draft's hard failures are a subset of the
    judged one's, so shipping it can only shrink the failure list. Judging the
    older sentence instead would escalate a PLO over a defect already repaired,
    because a validator that could not run must not escalate (rule 5).
    """
    if progress.vote is None or progress.judged is None or progress.current is progress.judged:
        return False
    return len(_hard_on(progress.current, ctx)) < len(_hard_on(progress.judged, ctx))


_CORRECTED_UNJUDGED_NOTE_TH = "แก้ประโยคแล้วแต่ผู้ตรวจยังไม่ได้ตรวจประโยคใหม่"


@dataclass
class _Progress:
    """What the loop has settled so far, held outside it so a timeout can read it.

    `judged` is the last statement a usable vote covered, and `vote` is that
    vote: the two only ever move together. `current` is the draft being worked on,
    which is ahead of `judged` between a repair and the next round.
    """

    current: Any
    judged: Any | None = None
    vote: SoftVote | None = None
    repairs: int = 0
    turns: int = 0


# One semaphore per event loop, shared by every PLO's judge runs. asyncio
# primitives bind to the loop they first wait on, so a module-global one breaks
# the moment a second loop (every pytest-asyncio test) touches it.
_JUDGE_SEMAPHORES: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _judge_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _JUDGE_SEMAPHORES.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(max(1, settings.llm_max_concurrency))
        _JUDGE_SEMAPHORES[loop] = semaphore
    return semaphore


def _hard_on(draft: Any, ctx: ValidationContext) -> list[Any]:
    return hard_failures(
        draft.statement_th,
        draft.action_verb_th,
        list(ctx.authoritative_need_ids),
        set(ctx.known_need_ids),
    )


def _judge_run(finish: Finish, turns: int) -> JudgeRun:
    """One run's verdict in the shape `smart_vote` counts."""
    failed: set[SmartFindingCode] = set()
    notes: dict[SmartFindingCode, str] = {}
    for field_name, code in SOFT_VERDICTS:
        if getattr(finish, field_name):
            continue
        failed.add(code)
        notes[code] = finish.findings_th.get(code.value) or finish.findings_th.get(field_name) or ""
    return JudgeRun(
        failed=frozenset(failed),
        notes_th=notes,
        diagnosis_th=finish.diagnosis_th,
        repair_hint_th=finish.repair_hint_th,
        turns=turns,
    )


def _voted_result(
    progress: _Progress,
    *,
    reason: ValidationReason = ValidationReason.FINISHED,
    note_th: str = "",
) -> SmartAgentResult:
    """The result for the last statement a usable vote covered, with that vote."""
    voted = progress.vote
    assert voted is not None and progress.judged is not None
    representative = voted.representative
    findings = [
        SmartFinding(
            criterion=code,
            severity="soft",
            note_th=representative.notes_th.get(code) or representative.diagnosis_th,
        )
        for code in voted.failed
    ]
    diagnosis = (
        f"{representative.diagnosis_th} {note_th}".strip()
        if note_th
        else (representative.diagnosis_th)
    )
    return _result_from_draft(
        progress.judged,
        soft_findings=findings,
        diagnosis_th=diagnosis,
        repair_count=progress.repairs,
        turns=progress.turns,
        reason=reason,
    )


async def run_smart_agent(
    draft: Any,
    ctx: ValidationContext,
    metadata: ProgramMetadata,
    *,
    enabled: bool = True,
    allow_repair: bool = True,
) -> SmartAgentResult:
    """Validate one draft: judge it by vote, repairing through the synthesis slot.

    Never raises for a bad verdict: every exit produces a result, and
    `validate_and_build` re-runs the pure-code checks on whatever comes back.

    The Needs the prompt lists come from `ctx` rather than from a parameter of
    their own, and that is the point: `ctx.needs_by_id` is exactly the set
    `get_need` will serve, so the prompt cannot advertise a Need the tool would
    refuse. A parallel argument could disagree with it, and the version that
    passed statements without their ids left `get_need` uncallable.

    `enabled=False` is the per-run switch (`POST /plos/run`, `run_validation`):
    it skips the agent for this run only, without touching `.env`.

    `allow_repair=False` judges and never rewrites. It is how a designer-edited
    PLO is revalidated: the sentence is theirs, and a repair would replace it.
    """
    # The kill switch. Not `and not settings.llm_provider`: that field is a
    # Literal with no empty member, so the second half could never be true and
    # the branch was unreachable -- VALIDATION_PROVIDER= made the API fail to
    # boot instead, and leaving it unset resolved to llm_provider and ran the
    # agent anyway.
    if not settings.validation_provider:
        return code_only_result(
            draft, ValidationReason.DISABLED, "ไม่ได้ตรวจ (ปิดการใช้ validation agent)"
        )

    # The per-run switch (POST /plos/run, run_validation=false). Checked after
    # the .env kill switch on purpose: a request can turn the agent off for one
    # run, never on when no endpoint is configured. Distinct from DISABLED so a
    # stored PLO says which of the two produced its code-only verdict.
    if not enabled:
        return code_only_result(draft, ValidationReason.SKIPPED, "ไม่ได้ตรวจ (ปิดการตรวจในรอบนี้)")

    progress = _Progress(current=draft)
    try:
        async with asyncio.timeout(settings.validation_timeout_seconds):
            return await _voted_loop(ctx, metadata, progress, allow_repair=allow_repair)
    except TimeoutError:
        logger.warning(
            f"  SMART agent {ctx.plo_id}: gave up after "
            f"{settings.validation_timeout_seconds}s "
            f"({progress.repairs} repairs, voted={progress.vote is not None})"
        )
        if _corrected_unjudged(progress, ctx):
            return code_only_result(
                progress.current,
                ValidationReason.DEADLINE,
                f"{_CORRECTED_UNJUDGED_NOTE_TH} (หมดเวลา — ใช้ผลตรวจรอบล่าสุด)",
                repair_count=progress.repairs,
                turns=progress.turns,
            )
        if progress.vote is not None:
            return _voted_result(
                progress,
                reason=ValidationReason.DEADLINE,
                note_th="(หมดเวลา — ใช้ผลตรวจรอบล่าสุด)",
            )
        return code_only_result(
            progress.current,
            ValidationReason.DEADLINE,
            f"ไม่ได้ตรวจครบ (เกิน {settings.validation_timeout_seconds} วินาที)",
            repair_count=progress.repairs,
            turns=progress.turns,
        )


_NO_VOTE_NOTE_TH: dict[ValidationReason, str] = {
    ValidationReason.MALFORMED: "ไม่ได้ตรวจครบ (ผู้ตรวจตอบไม่ตรงรูปแบบซ้ำ)",
    ValidationReason.TURN_BUDGET: "ไม่ได้ตรวจครบ (ผู้ตรวจใช้ครบรอบแล้วยังไม่สรุปผล)",
    ValidationReason.PROVIDER_ERROR: "ไม่ได้ตรวจ (เรียกผู้ตรวจไม่สำเร็จ)",
}


async def _judge_round(
    draft: Any,
    ctx: ValidationContext,
    metadata: ProgramMetadata,
    requested: int,
    failures: list[ValidationReason],
) -> list[JudgeRun | None]:
    """The runs of one round: a first batch, and the rest only if it left the
    vote open. Every run waits on the shared semaphore, so N PLOs times M runs
    stays inside `llm_max_concurrency`."""

    async def one() -> JudgeRun | None:
        async with _judge_semaphore():
            return await _judge_once(draft, ctx, metadata, failures=failures)

    runs: list[JudgeRun | None] = list(
        await asyncio.gather(*(one() for _ in range(first_batch_size(requested))))
    )
    if not is_decided(runs, requested):
        runs += await asyncio.gather(*(one() for _ in range(requested - len(runs))))
    return runs


async def _voted_loop(
    ctx: ValidationContext,
    metadata: ProgramMetadata,
    progress: _Progress,
    *,
    allow_repair: bool,
) -> SmartAgentResult:
    requested = settings.validation_runs
    failures: list[ValidationReason] = []
    logger.info(
        f"  SMART agent {ctx.plo_id}: start (model={settings.validation_model}, "
        f"{requested} runs / {settings.validation_max_turns} turns / "
        f"{settings.validation_max_repairs} repairs)"
    )

    rounds = 0
    judge_next = True
    hard: list[Any] = []
    to_fix: list[SmartFindingCode] = []
    round_vote: SoftVote | None = None
    while True:
        if judge_next:
            rounds += 1
            runs = await _judge_round(progress.current, ctx, metadata, requested, failures)
            progress.turns += sum(run.turns for run in runs if run is not None)
            round_vote = vote(runs, requested)
            if round_vote is not None:
                progress.judged = progress.current
                progress.vote = round_vote
            hard = _hard_on(progress.current, ctx)
            to_fix = repairable(round_vote.failed) if round_vote is not None else []

        stop = (
            (not hard and not to_fix)
            or not allow_repair
            or progress.repairs >= settings.validation_max_repairs
        )
        if judge_next:
            logger.info(
                f"  SMART agent {ctx.plo_id}: round={rounds} "
                f"runs_used={round_vote.runs_used if round_vote else 0}/{requested} "
                f"failed={[c.value for c in round_vote.failed] if round_vote else []} "
                f"hard={[f.value for f in hard]} repair={not stop}"
            )
        if stop:
            break

        representative = round_vote.representative if round_vote is not None else None
        soft = [
            (code.value, representative.notes_th.get(code) or representative.diagnosis_th)
            for code in to_fix
            if representative is not None
        ]
        instruction = build_vote_repair_instruction_th(
            [CRITERION_FIX_HINTS_TH[f] for f in hard],
            soft,
            representative.repair_hint_th if representative is not None else "",
        )
        criteria = [f.value for f in hard] + [code.value for code in to_fix]
        # A repair is spent when it is attempted: a failed or discarded one is
        # still budget used, or a stuck PLO would loop on the same sentence.
        progress.repairs += 1
        logger.info(
            f"  SMART agent {ctx.plo_id} repair {progress.repairs}/"
            f"{settings.validation_max_repairs}: {criteria}"
        )
        repaired = await _repair(progress.current, instruction, criteria, ctx, metadata)
        judge_next = False
        if repaired is None:
            continue
        introduced = set(_hard_on(repaired, ctx)) - set(hard)
        if introduced:
            # Decision 20: a rewrite that breaks something the old sentence did
            # not is worse than no rewrite. The previous draft stays.
            logger.warning(
                f"  SMART agent {ctx.plo_id}: repair discarded, it introduced "
                f"{[f.value for f in introduced]}"
            )
            continue
        if (repaired.statement_th, repaired.action_verb_th) == (
            progress.current.statement_th,
            progress.current.action_verb_th,
        ):
            # Nothing changed, so there is nothing new to judge.
            continue
        progress.current = repaired
        judge_next = True

    if progress.vote is None or _corrected_unjudged(progress, ctx):
        reason = next(
            (
                r
                for r in (
                    ValidationReason.MALFORMED,
                    ValidationReason.TURN_BUDGET,
                    ValidationReason.PROVIDER_ERROR,
                )
                if r in failures
            ),
            ValidationReason.PROVIDER_ERROR,
        )
        logger.warning(
            f"  SMART agent {ctx.plo_id}: no round held a vote after {rounds} "
            f"({reason.value}) — code-only verdict"
        )
        return code_only_result(
            progress.current,
            reason,
            _NO_VOTE_NOTE_TH[reason]
            if progress.vote is None
            else f"{_CORRECTED_UNJUDGED_NOTE_TH} {_NO_VOTE_NOTE_TH[reason]}",
            repair_count=progress.repairs,
            turns=progress.turns,
        )
    return _voted_result(progress)


def _with_turns_left(observation: str, turn: int) -> str:
    """Append the turns-left note once two or fewer turns remain after this one
    and at least half the budget is spent."""
    turns_left = settings.validation_max_turns - turn
    # The closing call already guarantees a verdict, so the note must not end
    # investigation early on a small budget.
    if 1 <= turns_left <= _TURNS_LEFT_WARNING and turn * 2 >= settings.validation_max_turns:
        return f"{observation}\n{build_turns_left_note(turns_left)}"
    return observation


async def _judge_once(
    draft: Any,
    ctx: ValidationContext,
    metadata: ProgramMetadata,
    *,
    failures: list[ValidationReason] | None = None,
) -> JudgeRun | None:
    """One judge run over `draft`: a tool-using conversation that ends in a Finish.

    Runs on its own copy of the context (a fresh `ToolBudget` for the repeat-call
    and evidence counters, the draft being judged), so concurrent runs share no
    counters. The runaway-reasoning bound is the exception: it is per PLO, seeded
    from `ctx.budget` and written back to it. Returns None when the run cannot produce a
    verdict — a provider error, or malformed/over-long steps the closing call
    cannot salvage — and says why through `failures` when the caller wants it.
    """
    # Counters are per run, but the reasoning bound is per PLO: a PLO whose step
    # ran away starts every later run bounded, and a run that trips it tells the
    # caller's budget so later runs and rounds of this PLO start bounded too.
    run_ctx = dataclasses.replace(
        ctx,
        draft=draft,
        budget=ToolBudget(reasoning_bounded=ctx.budget.reasoning_bounded),
    )
    try:
        return await _run_judge(draft, run_ctx, metadata, failures)
    finally:
        if run_ctx.budget.reasoning_bounded:
            ctx.budget.reasoning_bounded = True


async def _run_judge(
    draft: Any,
    run_ctx: ValidationContext,
    metadata: ProgramMetadata,
    failures: list[ValidationReason] | None,
) -> JudgeRun | None:
    def failed(reason: ValidationReason) -> None:
        if failures is not None:
            failures.append(reason)

    messages: list[dict[str, Any]] = build_smart_agent_prompt(
        statement_th=draft.statement_th,
        bloom_level=draft.bloom_level.value,
        action_verb_th=draft.action_verb_th,
        degree_level=metadata.degree_level,
        duration_years=metadata.duration_years,
        program_context=build_program_context_th(metadata.model_dump()),
        scope_th=metadata.scope_th or None,
        cited_needs=[
            (need_id, run_ctx.needs_by_id[need_id].statement_th)
            for need_id in run_ctx.authoritative_need_ids
            if need_id in run_ctx.needs_by_id
        ],
        cited_evidence_ids=sorted(run_ctx.cited_evidence_ids),
        sibling_count=len([s for s in run_ctx.siblings if s.plo_id != run_ctx.plo_id]),
    )

    malformed = 0
    turn = 0
    for turn in range(1, settings.validation_max_turns + 1):
        try:
            step = await _ask_step(messages, run_ctx, JudgeStep)
        # InstructorRetryException is what a schema failure actually reaches
        # here as: instructor re-asks internally and, once the retries are
        # spent, wraps the last ValidationError rather than re-raising it. It
        # subclasses InstructorError, not ValidationError, so catching only the
        # latter sent every malformed answer down the provider-error path -- one
        # bad step abandoned the whole verdict and `_MAX_MALFORMED` could never
        # be reached. The bare ValidationError stays caught beside it: a step
        # that fails validation outside instructor's retry wrapper is the same
        # condition and deserves the same budget. So does a truncation that
        # survived bounded reasoning (see _ask_step): the answer outgrew the cap.
        except (InstructorRetryException, ValidationError, IncompleteOutputException) as exc:
            malformed += 1
            logger.warning(
                f"  SMART agent {run_ctx.plo_id} turn {turn}: malformed step "
                f"({malformed}/{_MAX_MALFORMED}): {_schema_failure_reason(exc)}"
            )
            if malformed >= _MAX_MALFORMED:
                salvaged = await _closing_call(
                    run_ctx,
                    messages,
                    build_closing_after_malformed_instruction(),
                    ValidationReason.FINISHED_AFTER_MALFORMED,
                    turns=turn,
                )
                if salvaged is None:
                    failed(ValidationReason.MALFORMED)
                return salvaged
            messages.append(
                {
                    "role": "user",
                    "content": _with_turns_left(
                        build_refusal_observation("รูปแบบคำตอบไม่ถูกต้อง"), turn
                    ),
                }
            )
            continue
        except Exception as exc:
            # Instructor has already re-asked. A second failure is a dead
            # endpoint, not bad luck — and an agent that could not run must not
            # manufacture an escalation.
            logger.warning(f"  SMART agent {run_ctx.plo_id} turn {turn}: provider error: {exc}")
            failed(ValidationReason.PROVIDER_ERROR)
            return None

        malformed = 0
        messages.append({"role": "assistant", "content": step.model_dump_json()})
        action = step.action

        if isinstance(action, Finish):
            logger.debug(
                f"  SMART agent {run_ctx.plo_id}: run finished turns={turn} "
                f"evidence_reads={len(run_ctx.budget.evidence_reads)}"
            )
            return _judge_run(action, turn)

        fingerprint = call_fingerprint(
            action.tool.value,
            need_id=action.need_id,
            evidence_id=action.evidence_id,
            statement_th=action.statement_th,
            action_verb_th=action.action_verb_th,
            verb_th=action.verb_th,
        )
        if fingerprint in run_ctx.budget.seen_calls:
            # A repeat is not progress, and re-running it spends a provider call
            # to tell the model something it was already told.
            messages.append(
                {
                    "role": "user",
                    "content": _with_turns_left(
                        build_refusal_observation(
                            f"เรียก {action.tool.value} ด้วยอาร์กิวเมนต์เดิมไปแล้ว "
                            "— ใช้ข้อมูลที่มีหรือสรุปด้วย finish"
                        ),
                        turn,
                    ),
                }
            )
            continue
        run_ctx.budget.seen_calls.add(fingerprint)

        observation_result = await run_tool(
            run_ctx,
            action.tool.value,
            need_id=action.need_id,
            evidence_id=action.evidence_id,
            statement_th=action.statement_th,
            action_verb_th=action.action_verb_th,
            verb_th=action.verb_th,
        )
        outcome_th = (
            "ok" if observation_result.ok else f"refused: {observation_result.error_th or ''}"
        )
        logger.debug(
            f"  SMART agent {run_ctx.plo_id} turn {turn}: {action.tool.value} {outcome_th}"
        )
        messages.append(
            {
                "role": "user",
                "content": _with_turns_left(build_tool_observation(observation_result), turn),
            }
        )

    # The turns are spent without a Finish. Discarding the run loses every soft
    # verdict for work the model did do, so ask once more for a Finish and
    # nothing else. This call is not a turn.
    closed = await _closing_call(
        run_ctx,
        messages,
        build_closing_instruction(turn),
        ValidationReason.FINISHED_AT_BUDGET,
        turns=turn,
    )
    if closed is None:
        logger.warning(
            f"  SMART agent {run_ctx.plo_id}: turn budget exhausted after {turn} turns — no verdict"
        )
        failed(ValidationReason.TURN_BUDGET)
    return closed


async def _closing_call(
    ctx: ValidationContext,
    messages: list[dict[str, Any]],
    instruction: str,
    reason: ValidationReason,
    *,
    turns: int,
) -> JudgeRun | None:
    """One Finish-only call that salvages the verdict when a run cannot go on.

    Used when the turns run out and when malformed steps run out. Returns None
    when the call itself fails, so the caller counts the run as not having voted.
    """
    messages.append({"role": "user", "content": instruction})
    try:
        closing = await _ask_step(messages, ctx, ClosingStep)
    except Exception as exc:
        logger.warning(
            f"  SMART agent {ctx.plo_id}: closing call failed ({type(exc).__name__}): "
            f"{_schema_failure_reason(exc)}"
        )
        return None
    logger.debug(
        f"  SMART agent {ctx.plo_id}: run closed ({reason.value}) turns={turns} "
        f"evidence_reads={len(ctx.budget.evidence_reads)}"
    )
    return _judge_run(closing.action, turns)


def hard_findings_for(failures: Sequence[Any], hints_th: Sequence[str]) -> list[SmartFinding]:
    """The surviving hard failures, as findings a designer can read.

    This is what the old gate threw away: `fails` was logged and dropped, so an
    escalated PLO recorded that it failed and never which criterion did it.
    """
    out: list[SmartFinding] = []
    for failure, hint in zip(failures, hints_th, strict=False):
        code = SmartFindingCode(getattr(failure, "value", failure))
        if code not in HARD_CODES:
            continue
        out.append(SmartFinding(criterion=code, severity="hard", note_th=hint))
    return out
