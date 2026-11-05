"""What the SMART validation agent is allowed to look at, and nothing more.

Five tools. Four are pure functions over data the stage already loaded; only
`get_evidence` touches storage. Each one's refusals are the point: a validator
that can reach a Need outside the PLO's own trail, or read the whole evidence
corpus one turn at a time, is a validator whose context nobody can predict.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel

from curriculum_agent.data.repositories import EvidenceRepository
from curriculum_agent.models import (
    BloomLevel,
    EvidenceClassification,
    Need,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.smart_vocabulary import SmartFindingCode
from curriculum_agent.stages.bloom_verbs import (
    levels_for_verb,
    scan_statement_verbs,
    verbs_for_level,
)
from curriculum_agent.stages.smart_rules import CRITERION_FIX_HINTS_TH, hard_failures

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from curriculum_agent.stages.plo_synthesis import _PLODraft

# One evidence excerpt is capped, and so is how many a PLO may read.
#
# CLAUDE.md forbids passing full evidence text into synthesis prompts (a Need is
# summarized in <=200 tokens). The agent loop is the one new place where a
# prompt could accumulate the whole corpus one turn at a time, invisibly to the
# designer, so the cap belongs in the tool rather than in a prompt asking
# nicely. 600 characters is roughly 170-240 Thai tokens on these tokenizers.
_EVIDENCE_EXCERPT_CHARS = 600
_MAX_EVIDENCE_READS = 3


class NeedView(BaseModel):
    """One Need as the validator sees it.

    Ids, not member skill names: the Need sentence was written from those names
    already, and a list of them is noise for a SMART judgement.
    """

    need_id: str
    statement_th: str
    ksec_categories: list[str]
    bloom_level: BloomLevel
    freq: int
    demand_score: float
    source_stakeholder_types: list[StakeholderType]
    member_skill_count: int
    source_evidence_ids: list[str]


class EvidenceView(BaseModel):
    """One evidence item, excerpted.

    `truncated` and `total_chars` are not decoration. Without them the agent
    reasons about a forty-page สภาวิชาชีพ standard as if the first paragraph were
    all of it — the same defect `chunk_evidence_text` was written to fix.
    """

    evidence_id: str
    stakeholder_type: StakeholderType
    source_name: str
    classification: EvidenceClassification
    excerpt_th: str
    truncated: bool
    total_chars: int


class HardCheckResult(BaseModel):
    """The pure-code verdict, read rather than reimplemented.

    `bloom_verbs_found` is how the rubric's "exactly one recognized Bloom verb"
    rule becomes visible without changing `hard_failures`: a two-verb statement
    becomes something the validator can name in a repair instruction, while the
    S hard check keeps meaning exactly what its tests say it means.
    """

    statement_th: str
    action_verb_th: str
    failures: list[SmartFindingCode]
    hints_th: list[str]
    passed: bool
    bloom_verbs_found: list[str]
    bloom_verb_count: int


class BloomVerbResult(BaseModel):
    verb_th: str
    recognized: bool
    levels: list[BloomLevel]
    declared_level: BloomLevel
    matches_declared: bool
    adjacent_to_declared: bool
    suggestions_th: list[str]


class SiblingSummary(BaseModel):
    """What one outcome looks like to the validator judging another.

    Deliberately not a whole PLO. The sibling answers one question — is this
    outcome just another one restated? — and handing the validator full
    rationale and evidence trails for nine other PLOs is nine times the context
    for information it cannot act on.

    Overlap can only ever be a *soft* finding. It is a property of the set, and
    PLOs are validated concurrently: ten validators asked pairwise can each
    answer "not a duplicate" while the set holds two near twins, or PLO3 and
    PLO7 can flag each other, both escalate, both get repaired independently,
    and converge again. Program-level dedup belongs in plo_report, not in ten
    independent judgements trying to agree.

    Lives here rather than in plo_synthesis because SiblingPLOsResult has to
    name it as a real type for Pydantic to resolve, and plo_synthesis cannot be
    imported from this module at runtime without a cycle.
    """

    plo_id: str
    statement_th: str
    bloom_level: BloomLevel
    is_optional: bool
    source_need_ids: list[str]

    @classmethod
    def from_plo(cls, plo: Any) -> SiblingSummary:
        return cls(
            plo_id=plo.plo_id,
            statement_th=plo.statement_th,
            bloom_level=plo.bloom_level,
            is_optional=plo.is_optional,
            source_need_ids=list(plo.source_need_ids),
        )

    @classmethod
    def from_draft(cls, plo_id: str, draft: Any, *, is_optional: bool) -> SiblingSummary:
        """Takes the draft duck-typed rather than importing _PLODraft: the two
        callers pass a PLO and a draft, which agree on these five fields."""
        return cls(
            plo_id=plo_id,
            statement_th=draft.statement_th,
            bloom_level=draft.bloom_level,
            is_optional=is_optional,
            source_need_ids=list(draft.source_need_ids),
        )


class SiblingPLOsResult(BaseModel):
    """The other outcomes, and the Needs still being drafted alongside this one.

    Two lists because PLOs are validated concurrently: most siblings do not
    exist as outcomes yet when a validator asks. `note_th` says which is which,
    so "is this one just PLO2 again?" is answerable in the only form it can be
    answered at this point in the run.
    """

    plos: list[SiblingSummary]
    pending_need_statements_th: list[str]
    note_th: str


class ToolObservation(BaseModel):
    """One envelope for every tool, so the observation builder has one shape."""

    tool: str
    ok: bool
    payload: dict[str, Any] | None = None
    error_th: str | None = None


class EvidenceIndex:
    """Every evidence row for one program, fetched at most once per stage run.

    `EvidenceRepository` has no get_by_id — only `list_by_program` — so ten
    concurrent validators citing overlapping evidence would otherwise be ten
    full-table reads. The lock makes the first caller pay and the rest wait.
    """

    def __init__(self, program_id: str, repo: EvidenceRepository | None = None) -> None:
        self._program_id = program_id
        self._repo = repo or EvidenceRepository()
        self._lock = asyncio.Lock()
        self._by_id: dict[str, StakeholderEvidence] | None = None

    async def get(self, evidence_id: str) -> StakeholderEvidence | None:
        async with self._lock:
            if self._by_id is None:
                rows = await self._repo.list_by_program(self._program_id)
                self._by_id = {row.evidence_id: row for row in rows}
                logger.debug(f"EvidenceIndex loaded {len(self._by_id)} rows for {self._program_id}")
        return self._by_id.get(evidence_id)


@dataclass
class ToolBudget:
    """Counters. Mutable, and deliberately not on the frozen context. Each judge run
    gets its own copy (repeat calls, evidence reads); only `reasoning_bounded`
    is shared across a PLO's runs."""

    evidence_reads: set[str] = field(default_factory=set)
    seen_calls: set[str] = field(default_factory=set)
    # Set once a step's hidden reasoning ran to the step cap. Per PLO, not per judge
    # run, because the input that set it off stays in every conversation about this
    # PLO: each run is seeded from the caller's budget and writes the flag back —
    # see smart_agent._judge_once and _ask_step.
    reasoning_bounded: bool = False


@dataclass(frozen=True)
class ValidationContext:
    """Everything the tools may see, assembled once per PLO by the stage.

    Holds the Need objects the stage already loaded rather than a
    NeedRepository: `get_need` must not be able to reach a Need outside this
    PLO's own trail, and the cheapest way to guarantee that is not to hand it
    the query.

    `note_th` is absent by construction. The designer's note reaches the draft
    prompt and nothing else; if the validator could see it, it could relay the
    wording into a repair instruction and the note would arrive at a repair
    prompt second-hand — which is the invariant
    `test_note_reaches_the_draft_prompt_but_never_a_fix_prompt` protects.
    """

    program_id: str
    plo_id: str
    draft: _PLODraft
    authoritative_need_ids: tuple[str, ...]
    known_need_ids: frozenset[str]
    needs_by_id: Mapping[str, Need]
    cited_evidence_ids: frozenset[str]
    siblings: Sequence[SiblingSummary]
    pending_need_statements_th: Sequence[str] = ()
    evidence_index: EvidenceIndex | None = None
    budget: ToolBudget = field(default_factory=ToolBudget)


# ------------------------------ the tools ------------------------------


def check_hard(
    ctx: ValidationContext,
    statement_th: str | None = None,
    action_verb_th: str | None = None,
) -> HardCheckResult:
    """Read `smart_rules.hard_failures` — the same function, never a copy.

    The optional arguments let the validator probe a candidate phrasing before
    spending a repair round on it. The need ids are **not** overridable: those
    are the code's to decide, the same way `_PLODraft` omits `plo_id` and
    `source_evidence_ids`.
    """
    statement = statement_th if statement_th is not None else ctx.draft.statement_th
    verb = action_verb_th if action_verb_th is not None else ctx.draft.action_verb_th
    failures = hard_failures(
        statement, verb, list(ctx.authoritative_need_ids), set(ctx.known_need_ids)
    )
    verbs_found = scan_statement_verbs(statement)
    return HardCheckResult(
        statement_th=statement,
        action_verb_th=verb,
        failures=[SmartFindingCode(f.value) for f in failures],
        hints_th=[CRITERION_FIX_HINTS_TH[f] for f in failures],
        passed=not failures,
        bloom_verbs_found=verbs_found,
        bloom_verb_count=len(verbs_found),
    )


def bloom_lookup(ctx: ValidationContext, verb_th: str) -> BloomVerbResult:
    """Which Bloom level(s) a verb sits at, against the level the draft declared.

    Refuses nothing: `recognized=False` is a legitimate answer, and often the
    most useful one — it says the statement names no recognized Bloom verb.
    """
    from curriculum_agent.stages.bloom_verbs import are_adjacent

    levels = levels_for_verb(verb_th)
    declared = ctx.draft.bloom_level
    return BloomVerbResult(
        verb_th=verb_th,
        recognized=bool(levels),
        levels=levels,
        declared_level=declared,
        matches_declared=declared in levels,
        adjacent_to_declared=any(are_adjacent(level, declared) for level in levels),
        suggestions_th=verbs_for_level(declared)[:8],
    )


def get_need(ctx: ValidationContext, need_id: str) -> NeedView:
    """One of *this PLO's* Needs.

    Raises for anything else, and never falls back to NeedRepository — that
    would be a cross-program read dressed up as a helpful default.
    """
    need = ctx.needs_by_id.get(need_id)
    if need is None:
        available = ", ".join(sorted(ctx.needs_by_id)) or "(ไม่มี)"
        raise KeyError(f"PLO นี้ไม่ได้อ้างถึง Need '{need_id}' — Need ที่อ้างถึงคือ {available}")
    return NeedView(
        need_id=need.need_id,
        statement_th=need.statement_th,
        ksec_categories=[t.value for t in need.ksec_categories],
        bloom_level=need.bloom_level,
        freq=need.freq,
        demand_score=need.demand_score,
        source_stakeholder_types=list(need.source_stakeholder_types),
        member_skill_count=len(need.member_skill_ids),
        source_evidence_ids=list(need.source_evidence_ids),
    )


async def get_evidence(ctx: ValidationContext, evidence_id: str) -> EvidenceView:
    """One evidence item this PLO cites, excerpted, up to three per PLO.

    The two refusals are what keep the read set bounded and traceable: evidence
    the PLO does not cite is none of the validator's business, and a fourth
    distinct read is the loop starting to browse.
    """
    if evidence_id not in ctx.cited_evidence_ids:
        raise KeyError(
            f"PLO นี้ไม่ได้อ้างถึงหลักฐาน '{evidence_id}' "
            f"— อ้างถึง {', '.join(sorted(ctx.cited_evidence_ids)) or '(ไม่มี)'}"
        )
    budget = ctx.budget
    if evidence_id not in budget.evidence_reads and len(budget.evidence_reads) >= (
        _MAX_EVIDENCE_READS
    ):
        raise PermissionError(
            f"อ่านหลักฐานได้ไม่เกิน {_MAX_EVIDENCE_READS} รายการต่อ PLO "
            f"— อ่านแล้ว {', '.join(sorted(budget.evidence_reads))}"
        )
    if ctx.evidence_index is None:
        raise PermissionError("ไม่มีดัชนีหลักฐานสำหรับรอบนี้ ตัดสินจาก Need ที่อ้างถึงแทน")

    row = await ctx.evidence_index.get(evidence_id)
    if row is None:
        raise KeyError(f"ไม่พบหลักฐาน '{evidence_id}' ในโปรแกรมนี้")
    budget.evidence_reads.add(evidence_id)

    full = row.raw_text_th
    return EvidenceView(
        evidence_id=row.evidence_id,
        stakeholder_type=row.stakeholder_type,
        source_name=row.source_name,
        classification=row.classification,
        excerpt_th=full[:_EVIDENCE_EXCERPT_CHARS],
        truncated=len(full) > _EVIDENCE_EXCERPT_CHARS,
        total_chars=len(full),
    )


def list_sibling_plos(ctx: ValidationContext) -> SiblingPLOsResult:
    """The other outcomes in this program, and this run's other Needs.

    Never includes the PLO under validation: an outcome in its own sibling list
    is a duplicate the validator would faithfully discover.
    """
    others = sorted(
        (s for s in ctx.siblings if s.plo_id != ctx.plo_id),
        key=lambda s: s.plo_id,
    )
    if others and ctx.pending_need_statements_th:
        note = (
            "รายการ plos คือผลลัพธ์อื่นในชุดเดียวกัน (บางรายการยังเป็นฉบับร่าง) "
            "และ pending คือ Need อื่นที่กำลังร่างในรอบนี้"
        )
    elif others:
        note = "รายการ plos คือผลลัพธ์อื่นในชุดเดียวกัน"
    else:
        note = "ยังไม่มีผลลัพธ์อื่นในชุดนี้ให้เทียบ"
    return SiblingPLOsResult(
        plos=list(others),
        pending_need_statements_th=list(ctx.pending_need_statements_th),
        note_th=note,
    )


TOOL_NAMES = ("check_hard", "bloom_lookup", "get_need", "get_evidence", "list_sibling_plos")

# Which argument each tool requires. Enforced on the model's own schema (see
# stages/smart_agent.CallTool) so a miss is an Instructor re-ask rather than a
# branch in the dispatcher returning an error string.
TOOL_REQUIRED_ARG: dict[str, str | None] = {
    "check_hard": None,
    "bloom_lookup": "verb_th",
    "get_need": "need_id",
    "get_evidence": "evidence_id",
    "list_sibling_plos": None,
}


async def run_tool(
    ctx: ValidationContext,
    tool: str,
    *,
    need_id: str | None = None,
    evidence_id: str | None = None,
    statement_th: str | None = None,
    action_verb_th: str | None = None,
    verb_th: str | None = None,
) -> ToolObservation:
    """Dispatch one tool call, turning a refusal into an observation.

    A refusal is data the validator can act on ("that evidence is not cited by
    this PLO"), not a stage failure — it spends a turn and the loop continues.
    An unexpected exception is deliberately *not* caught here: that is a bug in
    a tool, and the loop's own error handling should see it as one.
    """
    try:
        if tool == "check_hard":
            result: BaseModel = check_hard(ctx, statement_th, action_verb_th)
        elif tool == "bloom_lookup":
            result = bloom_lookup(ctx, verb_th or "")
        elif tool == "get_need":
            result = get_need(ctx, need_id or "")
        elif tool == "get_evidence":
            result = await get_evidence(ctx, evidence_id or "")
        elif tool == "list_sibling_plos":
            result = list_sibling_plos(ctx)
        else:
            return ToolObservation(tool=tool, ok=False, error_th=f"ไม่มีเครื่องมือชื่อ '{tool}'")
    except (KeyError, PermissionError) as exc:
        return ToolObservation(tool=tool, ok=False, error_th=str(exc).strip("'\""))
    return ToolObservation(tool=tool, ok=True, payload=result.model_dump(mode="json"))


def call_fingerprint(
    tool: str,
    *,
    need_id: str | None = None,
    evidence_id: str | None = None,
    statement_th: str | None = None,
    action_verb_th: str | None = None,
    verb_th: str | None = None,
) -> str:
    """A stable key for "this exact call again".

    The loop refuses a repeat without spending a provider call on it. JSON-mode
    models genuinely need that break, and a repeat is not progress.
    """
    return "\x00".join(
        [
            tool,
            need_id or "",
            evidence_id or "",
            statement_th or "",
            action_verb_th or "",
            verb_th or "",
        ]
    )
