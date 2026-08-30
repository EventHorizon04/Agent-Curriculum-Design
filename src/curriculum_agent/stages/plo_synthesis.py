from __future__ import annotations

from collections.abc import Iterable

from loguru import logger
from pydantic import BaseModel, model_validator

from curriculum_agent.data.repositories import PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_heavy, complete_light
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    Need,
    ProgramMetadata,
    SMARTCheck,
    StakeholderType,
)
from curriculum_agent.prompts.smart_validator import build_smart_soft_judge_prompt
from curriculum_agent.prompts.stage_3_plo import build_plo_from_need_prompt
from curriculum_agent.stages.need_grouping import MAX_CORE_PLOS, MIN_NEEDS
from curriculum_agent.stages.smart_rules import (
    CRITERION_FIX_HINTS_TH,
    HardCriterion,
    hard_failures,
)

_MAX_RETRIES = 3

# Identifier scheme. Main outcomes are PLO1..PLOn ordered by descending demand,
# so PLO1 is the capability the labour market asked for most; supplementary
# outcomes derived from want-dominant Needs get their own OPT1..OPTn series and
# are exempt from the 6-10 count.
_MAIN_PREFIX = "PLO"
_OPTIONAL_PREFIX = "OPT"


def format_plo_id(index: int, *, is_optional: bool) -> str:
    """Build the identifier for the `index`-th outcome of its series (1-based)."""
    return f"{_OPTIONAL_PREFIX if is_optional else _MAIN_PREFIX}{index}"


def next_plo_id(existing_ids: Iterable[str], *, is_optional: bool) -> str:
    """Lowest unused number in the relevant series.

    Needed by the designer-driven merge endpoint, which creates one outcome at a
    time and cannot see the whole ordered set. `plo_id` is the table's primary key
    and the repository upserts, so a reused id would silently overwrite an
    existing outcome rather than failing.
    """
    prefix = _OPTIONAL_PREFIX if is_optional else _MAIN_PREFIX
    used = {
        int(pid[len(prefix) :])
        for pid in existing_ids
        if pid.startswith(prefix) and pid[len(prefix) :].isdigit()
    }
    index = 1
    while index in used:
        index += 1
    return format_plo_id(index, is_optional=is_optional)


def synthesis_order(needs: list[Need]) -> list[Need]:
    """Most-demanded first, `need_id` breaking ties so numbering is reproducible."""
    return sorted(needs, key=lambda n: (-n.demand_score, n.need_id))


class _PLODraft(BaseModel):
    """Intermediate schema for LLM output before SMART check is added.

    Carries only what the model is genuinely deciding. Two fields it used to
    declare are facts the code owns, and asking for them invited the model to
    contradict the data:

    - `plo_id`: each Need gets its own call with no knowledge of the others, so a
      model naming its own outcome answers "PLO1" every time — and since `plo_id`
      is the primary key and the repository upserts, a whole set collapsed into
      one row while the run reported success.
    - `source_evidence_ids`: the prompt never showed the model any evidence ids,
      so it invented them and the trail pointed nowhere.

    Keep it that way. A field the code computes does not belong in the contract.
    """

    statement_th: str
    statement_en: str | None = None
    bloom_level: BloomLevel
    action_verb_th: str
    source_need_ids: list[str]
    rationale_th: str
    distinctive_feature_th: str | None = None

    @model_validator(mode="after")
    def _check_needs(self) -> _PLODraft:
        if not self.source_need_ids:
            raise ValueError("source_need_ids must not be empty")
        return self


class _SingleDraftResponse(BaseModel):
    plo: _PLODraft


class _SmartSoftJudge(BaseModel):
    """The light model's soft verdicts. Every field defaults true so a failed judge
    call degrades toward 'not flagged' rather than flagging sound work."""

    specific_object_ok: bool = True
    measurable_ok: bool = True
    achievable_ok: bool = True
    relevant_needs_ok: bool = True
    time_bound_ok: bool = True
    notes_th: str | None = None


class _SmartOutcome(BaseModel):
    draft: _PLODraft
    smart_check: SMARTCheck
    retry_count: int
    escalated: bool
    soft_flags: list[str]


def _build_fix_prompt(draft: _PLODraft, violated: list[HardCriterion]) -> list[dict[str, str]]:
    hints = "\n".join(f"- {CRITERION_FIX_HINTS_TH[c]}" for c in violated)
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE ปรับปรุง PLO ที่ไม่ผ่านเกณฑ์ SMART ข้อที่ระบุ "
                "โดยคงสาระสำคัญเดิม ตอบเป็น JSON object field เหมือน PLO เดิม"
            ),
        },
        {
            "role": "user",
            "content": (
                f"PLO เดิม:\n{draft.statement_th}\n\n"
                f"เกณฑ์ที่ไม่ผ่าน:\n{hints}\n\n"
                f"Bloom level: {draft.bloom_level.value}, action_verb_th: {draft.action_verb_th}\n"
                "เขียน PLO ใหม่ให้ผ่านเกณฑ์ข้างต้นทุกข้อ"
            ),
        },
    ]


async def _ensure_smart(
    draft: _PLODraft,
    known_need_ids: set[str],
    metadata: ProgramMetadata,
    authoritative_need_ids: list[str],
    need_statements_th: list[str],
    plo_id: str,
) -> _SmartOutcome:
    """Hard fails → per-PLO retry (max _MAX_RETRIES) naming the criterion; soft fails → flags.

    `authoritative_need_ids` are the Need ids this PLO actually derives from (the
    ones the caller passed into synthesize_from_needs, not whatever the model
    echoed back). They are pinned onto the draft — and onto every retry's
    replacement draft — before hard_failures runs, so the gate always judges the
    ids that will actually ship. Without this, a model that returns one wrong or
    invented need id would fail R_EVIDENCE, burn all retries against a fix prompt
    that never mentions need ids (so it cannot repair the field), and escalate a
    PLO whose real, shipped evidence trail was correct all along.
    """
    draft.source_need_ids = authoritative_need_ids
    fails = hard_failures(
        draft.statement_th, draft.action_verb_th, draft.source_need_ids, known_need_ids
    )
    retries = 0
    while fails and retries < _MAX_RETRIES:
        retries += 1
        logger.debug(f"  SMART retry {retries} for PLO {plo_id}: {[f.value for f in fails]}")
        try:
            fix = await complete_heavy(
                _SingleDraftResponse, _build_fix_prompt(draft, fails), max_retries=2
            )
            draft = fix.plo
            draft.source_need_ids = authoritative_need_ids
        except Exception as exc:
            logger.warning(f"  SMART fix attempt {retries} failed: {exc}")
        fails = hard_failures(
            draft.statement_th, draft.action_verb_th, draft.source_need_ids, known_need_ids
        )

    escalated = bool(fails)
    if escalated:
        logger.warning(
            f"  PLO {plo_id} escalated after {retries} retries: {[f.value for f in fails]}"
        )

    soft_flags: list[str] = []
    judge = _SmartSoftJudge()
    try:
        judge = await complete_light(
            _SmartSoftJudge,
            build_smart_soft_judge_prompt(
                draft.statement_th,
                metadata.degree_level,
                metadata.duration_years,
                need_statements_th,
            ),
        )
    except Exception as exc:
        # Keep the all-true default: a hiccup must not manufacture soft flags.
        logger.warning(f"  Soft judge failed for PLO {plo_id}: {exc}")

    for ok, flag in (
        (judge.specific_object_ok, "S_object"),
        (judge.measurable_ok, "M_assessable"),
        (judge.achievable_ok, "A_level"),
        (judge.relevant_needs_ok, "R_needs"),
        (judge.time_bound_ok, "T_horizon"),
    ):
        if not ok:
            soft_flags.append(flag)

    # Soft verdicts reach SMARTCheck so `passed` stops reporting success for a
    # flagged outcome. They still do not escalate — that reads `fails` alone.
    smart = SMARTCheck(
        specific=HardCriterion.S_VERB not in fails and judge.specific_object_ok,
        measurable=HardCriterion.M_FORBIDDEN not in fails and judge.measurable_ok,
        achievable=judge.achievable_ok,
        relevant=HardCriterion.R_EVIDENCE not in fails and judge.relevant_needs_ok,
        timely=judge.time_bound_ok,
        notes_th=judge.notes_th,
    )
    return _SmartOutcome(
        draft=draft,
        smart_check=smart,
        retry_count=retries,
        escalated=escalated,
        soft_flags=soft_flags,
    )


async def synthesize_from_needs(
    metadata: ProgramMetadata,
    needs: list[Need],
    program_id: str,
    known_need_ids: set[str],
    plo_id: str,
    *,
    note_th: str | None = None,
) -> PLO | None:
    """Draft one PLO from one or more Needs, then run it through the SMART gate.

    Shared by the 1:1 stage loop and the designer-driven N:1 endpoint, so both
    paths get the same SMART enforcement and the same code-derived evidence
    trail. Returns None when the model call fails outright — the caller decides
    whether that is fatal.

    `note_th` is optional designer guidance on wording. It reaches the draft
    prompt only — never `_build_fix_prompt`, whose job is to repair one named
    SMART criterion while preserving the substance it was handed.
    """
    if not needs:
        raise ValueError("synthesize_from_needs requires at least one Need")

    try:
        response = await complete_heavy(
            _SingleDraftResponse,
            build_plo_from_need_prompt(metadata, needs, note_th=note_th),
            max_retries=_MAX_RETRIES,
        )
    except Exception as exc:
        ids = ", ".join(n.need_id for n in needs)
        logger.warning(f"PLO synthesis failed for Need(s) {ids}: {exc}")
        return None

    authoritative_need_ids = [n.need_id for n in needs]
    outcome = await _ensure_smart(
        response.plo,
        known_need_ids,
        metadata,
        authoritative_need_ids,
        [n.statement_th for n in needs],
        plo_id,
    )
    draft = outcome.draft

    # Evidence ids are never asked of the model (see build_plo_from_need_prompt) —
    # they are derived entirely from the Needs' own verified evidence trail, so
    # there is nothing here for a model to invent.
    evidence_ids = sorted({eid for n in needs for eid in n.source_evidence_ids})

    return PLO(
        plo_id=plo_id,
        program_id=program_id,
        statement_th=draft.statement_th,
        statement_en=draft.statement_en,
        bloom_level=draft.bloom_level,
        action_verb_th=draft.action_verb_th,
        smart_check=outcome.smart_check,
        # draft.source_need_ids was pinned to authoritative_need_ids inside
        # _ensure_smart before the gate ran; reuse it rather than recomputing —
        # recomputing here would just be the same list, and computing it twice
        # invites the two copies drifting apart under future edits.
        source_need_ids=draft.source_need_ids,
        source_evidence_ids=evidence_ids,
        rationale_th=draft.rationale_th,
        distinctive_feature_th=draft.distinctive_feature_th,
        version=1,
        smart_retry_count=outcome.retry_count,
        smart_escalated=outcome.escalated,
        soft_flags=outcome.soft_flags,
        # Optional only when every contributing Need is optional.
        is_optional=all(n.is_optional for n in needs),
    )


async def run(state: AgentState) -> AgentState:
    """Stage 4: one PLO per Need."""
    program_id = state.get("program_id", "unknown")
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run PLO synthesis stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)
    note_th = state.get("designer_note")

    needs = [Need.model_validate(d) for d in state.get("needs", [])]
    if not needs:
        raise ValueError(
            f"Stage 4: no Needs for program '{program_id}' — "
            "run need_combination successfully before PLO synthesis"
        )

    known_need_ids = {n.need_id for n in needs}
    logger.info(f"Stage 4: synthesizing one PLO per Need ({len(needs)} Needs)")

    # Number each series independently, most-demanded first, so PLO1 is the
    # capability the market asked for most and the numbering is reproducible
    # across re-runs on the same Needs.
    plos: list[PLO] = []
    for is_optional in (False, True):
        series = synthesis_order([n for n in needs if n.is_optional is is_optional])
        if not is_optional and len(series) > MAX_CORE_PLOS:
            # Logged, not silent: a designer looking at 22 Needs and 10 PLOs has to
            # be able to find out which twelve lost and why. plo_report shows the
            # same set on the review page.
            dropped = series[MAX_CORE_PLOS:]
            logger.warning(
                f"{len(series)} core Needs exceed the {MAX_CORE_PLOS}-PLO ceiling — "
                f"synthesizing the {MAX_CORE_PLOS} highest-demand ones and leaving "
                f"{len(dropped)} unused: {', '.join(n.need_id for n in dropped)}"
            )
            series = series[:MAX_CORE_PLOS]
        for index, need in enumerate(series, start=1):
            plo_id = format_plo_id(index, is_optional=is_optional)
            plo = await synthesize_from_needs(
                metadata, [need], program_id, known_need_ids, plo_id, note_th=note_th
            )
            if plo is not None:
                plos.append(plo)
            else:
                # Leave the number unused rather than renumbering the rest. A gap
                # says "this Need failed"; renumbering would silently change what
                # PLO4 refers to between runs, and designers cite these ids.
                logger.warning(f"  {plo_id} not produced — its number stays unused")

    core = sum(1 for p in plos if not p.is_optional)
    if core < MIN_NEEDS:
        logger.warning(
            f"Stage 4 produced {core} core PLOs, below the {MIN_NEEDS} minimum policy — "
            "need_combination should have enforced this; review at the checkpoint"
        )

    if not any(
        StakeholderType.INSTITUTIONAL_DIRECTION in n.source_stakeholder_types for n in needs
    ):
        logger.warning(
            "no PLO traces to the institution's own direction — add วิสัยทัศน์/พันธกิจ "
            "evidence at the Stakeholder Needs stage, or accept at the checkpoint"
        )

    # Replace, don't accumulate. plo_id is stable, so the upsert refreshes any
    # PLO this run produced again — but one the run no longer produces (a Need
    # that turned optional, or vanished from need_combination's output) would
    # otherwise survive, citing a Need that no longer exists. The trace endpoint
    # then resolves it to nothing and the UI shows a PLO with "Needs (0)".
    #
    # Skipped when the run produced nothing, matching the guards in
    # skill_extraction and need_combination: a total synthesis failure must not
    # destroy the last good set.
    plo_repo = PLORepository()
    if plos:
        removed = await plo_repo.delete_by_program(program_id)
        if removed:
            logger.info(f"Replaced {removed} PLO row(s) from a previous run")
        await plo_repo.bulk_insert(plos)
    else:
        logger.warning(f"Stage 4 produced no PLOs for '{program_id}' — previous set left untouched")
    state["plos"] = [p.model_dump(mode="json") for p in plos]
    state["current_stage"] = "plo_synthesis"
    return state
