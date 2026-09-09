"""The SMART validation agent: a tool-using loop over one PLO draft.

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

1. `Finish` carries soft verdicts and a diagnosis. It has no field that can
   clear a hard failure, and `check_hard` is a *read* of the pure function
   whose result is never retained as the verdict.
2. `validate_and_build` runs `hard_failures` on the final statement after this
   loop returns, whatever way it returned, and that call decides `escalated`.
   The agent's only causal route to the outcome is getting `complete_synthesis`
   to write a better sentence, which code then re-judges — so its power is
   monotone: it can shrink the failure list, never declare it empty.
3. A repair is *requested*, never written here. `RequestRepair` has no
   statement field, so the Thai a designer submits to MHESI still comes from
   the synthesis slot.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Any, Literal

from instructor.core.exceptions import InstructorRetryException
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, model_validator

from curriculum_agent.config import settings
from curriculum_agent.llm import complete_synthesis, complete_validation
from curriculum_agent.models import ProgramMetadata, SmartFinding
from curriculum_agent.prompts.smart_agent import (
    build_agent_repair_prompt,
    build_refusal_observation,
    build_repair_observation,
    build_smart_agent_prompt,
    build_tool_observation,
)
from curriculum_agent.smart_vocabulary import HARD_CODES, SmartFindingCode
from curriculum_agent.stages.smart_agent_tools import (
    TOOL_REQUIRED_ARG,
    ValidationContext,
    call_fingerprint,
    run_tool,
)
from curriculum_agent.stages.smart_rules import hard_failures

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


# Soft verdict field -> the code recorded when it is false. These five strings
# are the ones the exporter and both frontend pages already render.
_SOFT_VERDICTS: tuple[tuple[str, SmartFindingCode], ...] = (
    ("specific_object_ok", SmartFindingCode.S_OBJECT),
    ("measurable_ok", SmartFindingCode.M_ASSESSABLE),
    ("achievable_ok", SmartFindingCode.A_LEVEL),
    ("relevant_needs_ok", SmartFindingCode.R_NEEDS),
    ("time_bound_ok", SmartFindingCode.T_HORIZON),
)


class ValidationReason(StrEnum):
    """Why the loop stopped. Reported, logged, and folded into the diagnosis."""

    FINISHED = "finished"
    TURN_BUDGET = "turn_budget"
    REPAIR_BUDGET = "repair_budget"
    PROVIDER_ERROR = "provider_error"
    MALFORMED = "malformed"
    DEADLINE = "deadline"
    DISABLED = "disabled"


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


class RequestRepair(BaseModel):
    """The agent asks for a rewrite; it never performs one.

    There is deliberately no `statement_th` field. If there were, a helpful
    model would fill it in and "a repair is never answered by a different model
    than wrote the draft" would be one field away from broken. The Thai sentence
    is written by `complete_synthesis`, always.
    """

    kind: Literal["request_repair"]
    instruction_th: str = Field(min_length=1, max_length=400)
    criteria: list[SmartFindingCode] = Field(default_factory=list)
    keep_th: str | None = Field(default=None, max_length=200)


class Finish(BaseModel):
    """The verdict. Soft only — nothing here can clear a hard failure."""

    kind: Literal["finish"]
    specific_object_ok: bool = True
    measurable_ok: bool = True
    achievable_ok: bool = True
    relevant_needs_ok: bool = True
    time_bound_ok: bool = True
    findings_th: dict[str, str] = Field(default_factory=dict)
    diagnosis_th: str = Field(min_length=1, max_length=600)


class ValidationStep(BaseModel):
    """One turn. `reasoning_th` comes first on purpose: field order is schema
    order is generation order, so the model reasons before it commits."""

    reasoning_th: str = Field(min_length=1, max_length=800)
    action: Annotated[CallTool | RequestRepair | Finish, Field(discriminator="kind")]


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
        """The five booleans, derived from the findings so the two cannot drift."""
        failed = {f.criterion for f in self.soft_findings}
        return {field: code not in failed for field, code in _SOFT_VERDICTS}


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


def _soft_findings(finish: Finish) -> list[SmartFinding]:
    """The failed soft verdicts, each with the model's note or a default one."""
    out: list[SmartFinding] = []
    for field_name, code in _SOFT_VERDICTS:
        if getattr(finish, field_name):
            continue
        note = finish.findings_th.get(code.value) or finish.findings_th.get(field_name) or ""
        out.append(
            SmartFinding(criterion=code, severity="soft", note_th=note or finish.diagnosis_th)
        )
    return out


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
    action: RequestRepair,
    ctx: ValidationContext,
    metadata: ProgramMetadata,
) -> tuple[Any, str] | None:
    """Ask the synthesis slot for a replacement sentence.

    Returns the adopted draft and an observation, or None when the call failed.
    """
    from curriculum_agent.stages.plo_synthesis import _adopt, _SingleDraftResponse

    before_statement = draft.statement_th
    before_fails = hard_failures(
        draft.statement_th,
        draft.action_verb_th,
        list(ctx.authoritative_need_ids),
        set(ctx.known_need_ids),
    )
    try:
        fixed = await complete_synthesis(
            _SingleDraftResponse,
            build_agent_repair_prompt(
                statement_th=draft.statement_th,
                bloom_level=draft.bloom_level.value,
                action_verb_th=draft.action_verb_th,
                degree_level=metadata.degree_level,
                instruction_th=action.instruction_th,
                criteria=[c.value for c in action.criteria],
                keep_th=action.keep_th,
            ),
            max_retries=2,
        )
    except Exception as exc:
        logger.warning(f"  SMART agent {ctx.plo_id}: repair call failed: {exc}")
        return None

    # Re-pinned immediately: the gate judges the ids that will ship, and a
    # replacement draft is a fresh object the model filled in.
    adopted = _adopt(fixed.plo, list(ctx.authoritative_need_ids))
    after_fails = hard_failures(
        adopted.statement_th,
        adopted.action_verb_th,
        adopted.source_need_ids,
        set(ctx.known_need_ids),
    )
    # The agent sees the new sentence *and* the code's verdict on it, so it can
    # never mistake a rewrite it likes for a rewrite that passes.
    observation = build_repair_observation(
        before_statement=before_statement,
        after_statement=adopted.statement_th,
        before_failures=[f.value for f in before_fails],
        after_failures=[f.value for f in after_fails],
    )
    return adopted, observation


async def run_smart_agent(
    draft: Any,
    ctx: ValidationContext,
    metadata: ProgramMetadata,
) -> SmartAgentResult:
    """Validate one draft, repairing through the synthesis slot when asked.

    Never raises for a bad verdict: every exit produces a result, and
    `validate_and_build` re-runs the pure-code checks on whatever comes back.

    The Needs the prompt lists come from `ctx` rather than from a parameter of
    their own, and that is the point: `ctx.needs_by_id` is exactly the set
    `get_need` will serve, so the prompt cannot advertise a Need the tool would
    refuse. A parallel argument could disagree with it, and the version that
    passed statements without their ids left `get_need` uncallable.
    """
    if not settings.validation_provider and not settings.llm_provider:
        return code_only_result(
            draft, ValidationReason.DISABLED, "ไม่ได้ตรวจ (ปิดการใช้ validation agent)"
        )

    try:
        async with asyncio.timeout(settings.validation_timeout_seconds):
            return await _loop(draft, ctx, metadata)
    except TimeoutError:
        logger.warning(
            f"  SMART agent {ctx.plo_id}: gave up after "
            f"{settings.validation_timeout_seconds}s — code-only verdict"
        )
        return code_only_result(
            draft,
            ValidationReason.DEADLINE,
            f"ไม่ได้ตรวจครบ (เกิน {settings.validation_timeout_seconds} วินาที)",
        )


async def _loop(
    draft: Any,
    ctx: ValidationContext,
    metadata: ProgramMetadata,
) -> SmartAgentResult:
    messages: list[dict[str, Any]] = build_smart_agent_prompt(
        statement_th=draft.statement_th,
        bloom_level=draft.bloom_level.value,
        action_verb_th=draft.action_verb_th,
        degree_level=metadata.degree_level,
        duration_years=metadata.duration_years,
        cited_needs=[
            (need_id, ctx.needs_by_id[need_id].statement_th)
            for need_id in ctx.authoritative_need_ids
            if need_id in ctx.needs_by_id
        ],
        cited_evidence_ids=sorted(ctx.cited_evidence_ids),
        sibling_count=len([s for s in ctx.siblings if s.plo_id != ctx.plo_id]),
    )
    logger.info(
        f"  SMART agent {ctx.plo_id}: start (model={settings.validation_model}, "
        f"budget {settings.validation_max_turns} turns / "
        f"{settings.validation_max_repairs} repairs)"
    )

    repairs = 0
    malformed = 0
    turn = 0
    for turn in range(1, settings.validation_max_turns + 1):
        try:
            step = await complete_validation(
                ValidationStep,
                messages,
                max_retries=2,
                temperature=0,
                max_tokens=_MAX_STEP_TOKENS,
            )
        # InstructorRetryException is what a schema failure actually reaches
        # here as: instructor re-asks internally and, once the retries are
        # spent, wraps the last ValidationError rather than re-raising it. It
        # subclasses InstructorError, not ValidationError, so catching only the
        # latter sent every malformed answer down the provider-error path -- one
        # bad step abandoned the whole verdict and `_MAX_MALFORMED` could never
        # be reached. The bare ValidationError stays caught beside it: a step
        # that fails validation outside instructor's retry wrapper is the same
        # condition and deserves the same budget.
        except (InstructorRetryException, ValidationError) as exc:
            malformed += 1
            logger.warning(
                f"  SMART agent {ctx.plo_id} turn {turn}: malformed step "
                f"({malformed}/{_MAX_MALFORMED}): {_schema_failure_reason(exc)}"
            )
            if malformed >= _MAX_MALFORMED:
                return code_only_result(
                    draft,
                    ValidationReason.MALFORMED,
                    "ไม่ได้ตรวจครบ (ผู้ตรวจตอบไม่ตรงรูปแบบซ้ำ)",
                    repair_count=repairs,
                    turns=turn,
                )
            messages.append(
                {"role": "user", "content": build_refusal_observation("รูปแบบคำตอบไม่ถูกต้อง")}
            )
            continue
        except Exception as exc:
            # Instructor has already re-asked. A second failure is a dead
            # endpoint, not bad luck — and an agent that could not run must not
            # manufacture an escalation.
            logger.warning(f"  SMART agent {ctx.plo_id} turn {turn}: provider error: {exc}")
            return code_only_result(
                draft,
                ValidationReason.PROVIDER_ERROR,
                "ไม่ได้ตรวจ (เรียกผู้ตรวจไม่สำเร็จ)",
                repair_count=repairs,
                turns=turn,
            )

        malformed = 0
        messages.append({"role": "assistant", "content": step.model_dump_json()})
        action = step.action

        if isinstance(action, Finish):
            logger.info(
                f"  SMART agent {ctx.plo_id}: finish turns={turn} repairs={repairs} "
                f"evidence_reads={len(ctx.budget.evidence_reads)}"
            )
            return _result_from_draft(
                draft,
                soft_findings=_soft_findings(action),
                diagnosis_th=action.diagnosis_th,
                repair_count=repairs,
                turns=turn,
                reason=ValidationReason.FINISHED,
            )

        if isinstance(action, RequestRepair):
            if repairs >= settings.validation_max_repairs:
                messages.append(
                    {
                        "role": "user",
                        "content": build_refusal_observation(
                            f"แก้ไขได้ไม่เกิน {settings.validation_max_repairs} รอบ "
                            "— สรุปผลตรวจด้วย finish"
                        ),
                    }
                )
                continue
            repairs += 1
            logger.info(
                f"  SMART agent {ctx.plo_id} repair {repairs}/{settings.validation_max_repairs}: "
                f'"{action.instruction_th}" {[c.value for c in action.criteria]}'
            )
            repaired = await _repair(draft, action, ctx, metadata)
            if repaired is None:
                messages.append(
                    {"role": "user", "content": build_refusal_observation("แก้ไขประโยคไม่สำเร็จ")}
                )
                continue
            draft, observation = repaired
            messages.append({"role": "user", "content": observation})
            continue

        fingerprint = call_fingerprint(
            action.tool.value,
            need_id=action.need_id,
            evidence_id=action.evidence_id,
            statement_th=action.statement_th,
            action_verb_th=action.action_verb_th,
            verb_th=action.verb_th,
        )
        if fingerprint in ctx.budget.seen_calls:
            # A repeat is not progress, and re-running it spends a provider call
            # to tell the model something it was already told.
            messages.append(
                {
                    "role": "user",
                    "content": build_refusal_observation(
                        f"เรียก {action.tool.value} ด้วยอาร์กิวเมนต์เดิมไปแล้ว — ใช้ข้อมูลที่มีหรือสรุปด้วย finish"
                    ),
                }
            )
            continue
        ctx.budget.seen_calls.add(fingerprint)

        observation_result = await run_tool(
            ctx,
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
        logger.debug(f"  SMART agent {ctx.plo_id} turn {turn}: {action.tool.value} {outcome_th}")
        messages.append({"role": "user", "content": build_tool_observation(observation_result)})

    logger.warning(
        f"  SMART agent {ctx.plo_id}: turn budget exhausted after {turn} turns "
        f"({repairs} repairs) — code-only verdict"
    )
    return code_only_result(
        draft,
        ValidationReason.TURN_BUDGET
        if repairs < settings.validation_max_repairs
        else ValidationReason.REPAIR_BUDGET,
        f"ไม่ได้ตรวจครบ (ใช้ครบ {turn} รอบแล้วยังไม่สรุปผล)",
        repair_count=repairs,
        turns=turn,
    )


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
