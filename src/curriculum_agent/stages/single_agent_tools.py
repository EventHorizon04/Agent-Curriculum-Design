"""The single agent's tool bag.

Seven tools over data the handler already loaded, none of them storage-facing:
`get_evidence` pages through evidence text held in memory, and the Need/PLO tools
read what the handler keeps current in `SingleToolContext`. Unlike the SMART
validation agent there is no cited-only rule and no read cap — the needs task has
to read the whole corpus — so the bound on context is the loop's job (it drops the
oldest evidence text, see `single_agent_loop`), not a refusal here.

`check_hard`, `bloom_lookup`'s primitives, `check_verbs` and `list_sibling_plos`
delegate to the implementations the SMART agent and the PLO reviewer already use;
nothing of the rule logic is copied. `CallTool` lives here, not in the loop, so the
loop can import the tools without a cycle; the loop re-exports it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal, cast

from pydantic import BaseModel

from curriculum_agent.models import StakeholderEvidence
from curriculum_agent.prompts.single_agent import NeedBrief
from curriculum_agent.stages.bloom_verbs import levels_for_verb, verbs_for_level
from curriculum_agent.stages.plo_review_agent import ReviewToolName, run_review_tool
from curriculum_agent.stages.smart_agent_tools import (
    SiblingSummary,
    ValidationContext,
    check_hard,
    list_sibling_plos,
)

ToolName = Literal[
    "get_evidence",
    "get_need",
    "need_detail",
    "list_sibling_plos",
    "check_hard",
    "bloom_lookup",
    "check_verbs",
]

# A part is cut at whitespace only when that leaves at least this share of the
# window; Thai has few spaces, so an early one must not produce a sliver part.
_MIN_PART_SHARE = 0.5


class CallTool(BaseModel):
    """One tool call: a single flat argument bag, as in the validation agent."""

    kind: Literal["call_tool"]
    tool: ToolName
    evidence_id: str | None = None
    part: int = 1
    need_id: str | None = None
    statement_th: str | None = None
    action_verb_th: str | None = None
    verb_th: str | None = None


class ToolResult(BaseModel):
    ok: bool
    payload_json: str = ""
    error_th: str | None = None
    # Set only when the call returned evidence text, so the loop can tell raw
    # evidence from every other observation and drop it first.
    evidence_id: str | None = None


@dataclass
class SingleToolContext:
    evidence_by_id: dict[str, StakeholderEvidence]
    needs_by_id: dict[str, NeedBrief]  # the handler keeps this current
    plos: list[SiblingSummary]  # saved so far; the handler keeps this current
    part_chars: int
    read_parts: set[tuple[str, int]] = field(default_factory=set)


def evidence_parts(text: str, part_chars: int) -> list[str]:
    """Split text into parts of at most `part_chars`, losing nothing.

    A part ends after the last whitespace in its window when that is past the
    middle of the window, otherwise it is cut hard. Joining the parts gives the
    text back. Empty text is one empty part, so `part=1` always exists.
    """
    if len(text) <= part_chars:
        return [text]
    parts: list[str] = []
    rest = text
    while len(rest) > part_chars:
        window = rest[:part_chars]
        cut = max(window.rfind(" "), window.rfind("\n"))
        end = cut + 1 if cut + 1 >= part_chars * _MIN_PART_SHARE else part_chars
        parts.append(rest[:end])
        rest = rest[end:]
    if rest:
        parts.append(rest)
    return parts


def _err(message_th: str) -> ToolResult:
    return ToolResult(ok=False, error_th=message_th)


def _ok(payload: dict[str, Any] | BaseModel, *, evidence_id: str | None = None) -> ToolResult:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    return ToolResult(
        ok=True, payload_json=json.dumps(data, ensure_ascii=False), evidence_id=evidence_id
    )


def _get_evidence(ctx: SingleToolContext, call: CallTool) -> ToolResult:
    evidence_id = call.evidence_id or ""
    row = ctx.evidence_by_id.get(evidence_id)
    if row is None:
        return _err(f"ไม่พบหลักฐานรหัส '{evidence_id}' ใช้เฉพาะรหัสที่อยู่ในรายการ")
    parts = evidence_parts(row.raw_text_th, ctx.part_chars)
    if not 1 <= call.part <= len(parts):
        return _err(f"หลักฐาน {evidence_id} มี {len(parts)} ส่วน ขอส่วนที่ {call.part} ไม่ได้ (นับจาก 1)")
    ctx.read_parts.add((evidence_id, call.part))
    return _ok(
        {
            "evidence_id": evidence_id,
            "stakeholder_type": row.stakeholder_type.value,
            "source_name": row.source_name,
            "part": call.part,
            "parts": len(parts),
            "text": parts[call.part - 1],
        },
        evidence_id=evidence_id,
    )


def _get_need(ctx: SingleToolContext, call: CallTool) -> ToolResult:
    """`get_need` and `need_detail` are one implementation: the prompt says so."""
    need = ctx.needs_by_id.get(call.need_id or "")
    if need is None:
        available = ", ".join(sorted(ctx.needs_by_id)) or "(ไม่มี)"
        return _err(f"ไม่พบ Need รหัส '{call.need_id}' Need ที่มีคือ {available}")
    return _ok(
        {
            "need_id": need.need_id,
            "statement_th": need.statement_th,
            "ksec_categories": list(need.ksec_categories),
            "bloom_level": need.bloom_level,
            "demand_score": need.demand_score,
            "stakeholder_types": list(need.stakeholder_types),
            "evidence_ids": list(need.evidence_ids),
        }
    )


def _shim(ctx: SingleToolContext) -> ValidationContext:
    """A `ValidationContext` just wide enough for the delegated tools.

    `check_hard` with both arguments given and `list_sibling_plos` never read the
    draft, so it is a placeholder. The need ids are this context's own, as both the
    cited and the known set: here the agent checks wording only, so the citation
    criterion cannot fail (the handlers run the real hard check with real
    citations). An empty Need set gets one placeholder id for the same reason.
    """
    ids = tuple(ctx.needs_by_id) or ("-",)
    return ValidationContext(
        program_id="",
        plo_id="",
        draft=cast(Any, None),
        authoritative_need_ids=ids,
        known_need_ids=frozenset(ids),
        needs_by_id={},
        cited_evidence_ids=frozenset(),
        siblings=list(ctx.plos),
    )


def _check_verbs(call: CallTool) -> ToolResult:
    # run_review_tool answers by plo_id from a dossier; a one-item stand-in gives it
    # the statement and verb, so the answer is the reviewer's own, not a copy.
    item = SimpleNamespace(
        plo_id="draft",
        statement_th=call.statement_th or "",
        action_verb_th=call.action_verb_th or "",
    )
    dossier = cast(Any, SimpleNamespace(items=[item], unused_needs=[]))
    ok, payload = run_review_tool(dossier, {}, ReviewToolName.CHECK_VERBS, "draft")
    payload.pop("plo_id", None)
    return _ok(payload) if ok else _err(str(payload.get("error_th", "")))


def _bloom_lookup(verb_th: str) -> ToolResult:
    verb = verb_th.strip()
    levels = levels_for_verb(verb)
    return _ok(
        {
            "verb_th": verb,
            "recognized": bool(levels),
            "levels": [level.value for level in levels],
            "examples_th": {level.value: verbs_for_level(level)[:8] for level in levels},
        }
    )


def run_single_tool(ctx: SingleToolContext, call: CallTool) -> ToolResult:
    """Dispatch one call. A refusal is an observation the agent reads, not an exception."""
    tool = call.tool
    if tool == "get_evidence":
        if not call.evidence_id:
            return _err("get_evidence ต้องมี evidence_id")
        return _get_evidence(ctx, call)
    if tool in ("get_need", "need_detail"):
        if not call.need_id:
            return _err(f"{tool} ต้องมี need_id")
        return _get_need(ctx, call)
    if tool == "list_sibling_plos":
        return _ok(list_sibling_plos(_shim(ctx)))
    if tool == "bloom_lookup":
        if not call.verb_th:
            return _err("bloom_lookup ต้องมี verb_th")
        return _bloom_lookup(call.verb_th)
    if call.statement_th is None or not call.action_verb_th:
        return _err(f"{tool} ต้องมี statement_th และ action_verb_th")
    if tool == "check_hard":
        return _ok(check_hard(_shim(ctx), call.statement_th, call.action_verb_th))
    return _check_verbs(call)
