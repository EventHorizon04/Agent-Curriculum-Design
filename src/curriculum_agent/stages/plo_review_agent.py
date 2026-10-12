"""The PLO QA agent: a small structured action loop over the finished set.

Stage 06 (spec 2026-10-12). The same shape as `smart_agent` and for the same
reasons — instructor JSON mode, one step object with a discriminated action, no
native tool-calling — but smaller on purpose: three tools, four calls, six steps,
and no tool that reaches evidence. The agency is in choosing which suspicion to
check, not in seeing more; a reviewer that reads the upstream detail anchors on
it instead of judging the set as written.

Nothing here decides what is stored. `plo_review.accept_review` judges the
answer entry by entry and computes every number in code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Literal

from instructor.core.exceptions import IncompleteOutputException
from loguru import logger
from pydantic import BaseModel, Field
from tenacity import AsyncRetrying, retry_if_not_exception_type, stop_after_attempt

from curriculum_agent.config import settings
from curriculum_agent.llm import complete_plo_review
from curriculum_agent.models import Need, ReviewToolCall
from curriculum_agent.prompts.plo_review import (
    build_plo_review_prompt,
    build_review_observation,
    build_review_refusal,
)
from curriculum_agent.stages.bloom_verbs import levels_for_verb, scan_statement_verbs
from curriculum_agent.stages.plo_review_facts import ReviewDossier
from curriculum_agent.stages.smart_rules import declares_too_many_verbs, strip_outcome_prefix

MAX_TOOL_CALLS = 4
MAX_STEPS = 6
# A Finish carries every section in Thai, which JSON escapes per character.
_MAX_STEP_TOKENS = 8192
# Bounded on every step. Unbounded, this slot produced nothing on the tourism set
# 3/3 (one truncation at 8192 tokens, two 180s timeouts); bounded at 1024 it
# answered 3/3 in 45-57s (spec 2026-10-04, "Measured").
_MAX_REASONING_TOKENS = 1024
_STEP_ATTEMPTS = 2


class ReviewToolName(StrEnum):
    BLOOM_LOOKUP = "bloom_lookup"
    CHECK_VERBS = "check_verbs"
    NEED_DETAIL = "need_detail"


# Loose on purpose (plain strings, defaults everywhere): a pydantic failure fails
# the whole step and loses every good entry with the bad one. `accept_review`
# judges entry by entry.
class Redundancy(BaseModel):
    plo_ids: list[str] = Field(default_factory=list)
    reason_th: str = ""
    suggestion_th: str = ""


class KsecVerdict(BaseModel):
    plo_id: str = ""
    suggested: list[str] = Field(default_factory=list)
    reason_th: str = ""


class BloomVerdict(BaseModel):
    plo_id: str = ""
    suggested_level: str | None = None
    reason_th: str = ""


class UnusedVerdict(BaseModel):
    need_id: str = ""
    verdict: str = ""
    reason_th: str = ""


class ReviewCallTool(BaseModel):
    kind: Literal["call_tool"]
    tool: ReviewToolName
    arg: str = Field(min_length=1, max_length=120)


class ReviewFinish(BaseModel):
    """The answer. It has no field for any number — those are code's."""

    kind: Literal["finish"]
    redundancies: list[Redundancy] = Field(default_factory=list)
    ksec: list[KsecVerdict] = Field(default_factory=list)
    bloom: list[BloomVerdict] = Field(default_factory=list)
    bloom_distribution_th: str = ""
    coverage_th: str = ""
    unused_needs: list[UnusedVerdict] = Field(default_factory=list)
    summary_th: str = ""


class ReviewStep(BaseModel):
    """`reasoning_th` first: field order is generation order."""

    reasoning_th: str = ""
    action: Annotated[ReviewCallTool | ReviewFinish, Field(discriminator="kind")]


@dataclass
class AgentOutcome:
    finish: ReviewFinish | None
    reason: str | None  # None when finished; "failed" | "timeout"
    tool_calls: list[ReviewToolCall] = field(default_factory=list)


def run_review_tool(
    dossier: ReviewDossier,
    unused_needs: Mapping[str, Need],
    tool: ReviewToolName,
    arg: str,
) -> tuple[bool, dict[str, Any]]:
    """One tool, pure. (False, {"error_th": ...}) is a refusal the model reads."""
    arg = arg.strip()
    if tool is ReviewToolName.BLOOM_LOOKUP:
        levels = [lv.value for lv in levels_for_verb(arg)]
        return True, {"verb_th": arg, "recognized": bool(levels), "levels": levels}
    if tool is ReviewToolName.CHECK_VERBS:
        item = next((i for i in dossier.items if i.plo_id == arg), None)
        if item is None:
            return False, {"error_th": f"ไม่มี PLO รหัส {arg} ในชุดนี้"}
        declared = scan_statement_verbs(item.action_verb_th)
        return True, {
            "plo_id": item.plo_id,
            "action_verb_th": item.action_verb_th,
            "opens_with_declared_verb": bool(item.action_verb_th)
            and strip_outcome_prefix(item.statement_th).startswith(item.action_verb_th),
            "declared_verbs": declared,
            "too_many_verbs": declares_too_many_verbs(item.action_verb_th),
            "levels": {v: [lv.value for lv in levels_for_verb(v)] for v in declared},
        }
    need = unused_needs.get(arg)
    if need is not None and any(
        u.need_id == arg and u.exclusion == "unwritten" for u in dossier.unused_needs
    ):
        # Its rationale is a fallback sentence naming member skills, and the
        # reviewer is kept away from skill-level text.
        return False, {"error_th": "Need นี้ยังไม่มีประโยคที่ผู้ออกแบบเขียนไว้ จึงไม่มีรายละเอียดให้ดู"}
    if need is None:
        return False, {"error_th": "need_detail ใช้ได้กับ Need ในรายการที่ไม่ได้เป็น PLO เท่านั้น"}
    return True, {
        "need_id": need.need_id,
        "rationale_th": need.rationale_th,
        "rationale_note_th": "คำอธิบายของโมเดลที่เขียน Need นี้ ไม่ใช่หลักฐาน",
        "member_count": len(need.member_skill_ids),
        "stakeholder_coverage": {str(k): v for k, v in need.stakeholder_coverage.items()},
    }


def _step_retrying() -> AsyncRetrying:
    # A schema miss is worth one re-ask; a truncation is not (same as smart_agent).
    return AsyncRetrying(
        stop=stop_after_attempt(_STEP_ATTEMPTS),
        retry=retry_if_not_exception_type(IncompleteOutputException),
    )


async def _ask_step(messages: list[dict[str, Any]]) -> ReviewStep:
    return await complete_plo_review(
        ReviewStep,
        messages,
        max_retries=_step_retrying(),
        temperature=0,
        max_tokens=_MAX_STEP_TOKENS,
        reasoning_max_tokens=_MAX_REASONING_TOKENS,
    )


async def run_review_agent(
    dossier: ReviewDossier, unused_needs: Mapping[str, Need]
) -> AgentOutcome:
    """Run the loop. Never raises: every failure is an outcome with a reason."""
    messages: list[dict[str, Any]] = build_plo_review_prompt(dossier)
    calls: list[ReviewToolCall] = []
    try:
        async with asyncio.timeout(settings.plo_review_timeout_seconds):
            for step_no in range(1, MAX_STEPS + 1):
                step = await _ask_step(messages)
                messages.append({"role": "assistant", "content": step.model_dump_json()})
                action = step.action
                if isinstance(action, ReviewFinish):
                    logger.info(
                        f"plo_review agent: finish at step {step_no}, {len(calls)} tool call(s)"
                    )
                    return AgentOutcome(action, None, calls)
                if step_no == MAX_STEPS:
                    break
                if len(calls) >= MAX_TOOL_CALLS:
                    content = build_review_refusal(
                        f"ใช้เครื่องมือครบ {MAX_TOOL_CALLS} ครั้งแล้ว — สรุปผลด้วย finish"
                    )
                else:
                    arg = action.arg.strip()
                    calls.append(ReviewToolCall(tool=action.tool.value, arg=arg))
                    ok, payload = run_review_tool(dossier, unused_needs, action.tool, arg)
                    content = (
                        build_review_observation(action.tool.value, payload)
                        if ok
                        else build_review_refusal(payload["error_th"])
                    )
                if step_no == MAX_STEPS - 1:
                    content += " — รอบถัดไปเป็นรอบสุดท้าย ต้องสรุปด้วย finish"
                messages.append({"role": "user", "content": content})
    except TimeoutError:
        logger.warning(
            f"plo_review agent: timed out after {settings.plo_review_timeout_seconds}s "
            f"({len(calls)} tool call(s)) — code facts only"
        )
        return AgentOutcome(None, "timeout", calls)
    except Exception as exc:  # malformed step, truncation, provider error
        logger.warning(f"plo_review agent: step failed ({exc!r}) — code facts only")
        return AgentOutcome(None, "failed", calls)
    logger.warning(f"plo_review agent: {MAX_STEPS} steps without a finish — code facts only")
    return AgentOutcome(None, "failed", calls)
