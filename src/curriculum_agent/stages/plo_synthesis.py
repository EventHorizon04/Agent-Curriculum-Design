from __future__ import annotations

from collections.abc import Iterable, Sequence

from loguru import logger
from pydantic import BaseModel, ValidationError, model_validator

from curriculum_agent.concurrency import gather_bounded
from curriculum_agent.config import settings
from curriculum_agent.data.repositories import NeedRepository, PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_plo_synthesis
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    Need,
    ProgramMetadata,
    SMARTCheck,
    StakeholderType,
)
from curriculum_agent.prompts.stage_3_plo import build_plo_from_need_prompt
from curriculum_agent.stages.need_grouping import (
    MAX_CORE_PLOS,
    MIN_NEEDS,
    SCOPE_PASS_RATIO,
    is_in_scope,
    is_unwritten_need,
)
from curriculum_agent.stages.smart_agent import (
    PLO_MAX_TOKENS,
    PLO_REASONING_MAX_TOKENS,
    ValidationReason,
    hard_findings_for,
    run_smart_agent,
)
from curriculum_agent.stages.smart_agent_tools import (
    EvidenceIndex,
    SiblingSummary,
    ToolBudget,
    ValidationContext,
)
from curriculum_agent.stages.smart_rules import (
    CRITERION_FIX_HINTS_TH,
    HardCriterion,
    hard_failures,
    strip_outcome_prefix,
)

# Re-exported: SiblingSummary lives with the tools that return it, but callers
# (the stage, the merge route) reach for it here.
__all__ = ["SiblingSummary"]

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
    time and cannot see the whole ordered set. A PLO's identity is
    (program_id, plo_id) and the repository upserts on it, so a reused id within
    this program would silently overwrite an existing outcome rather than
    failing.
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


def cited_need_ids(plos: Iterable[PLO]) -> set[str]:
    """Every Need id the given outcomes trace to.

    The one definition of "this Need has been used". A Need is behind at most one
    PLO, so its absence here is what puts it back in the pool a designer can
    merge from — derived rather than stored, so deleting a PLO returns its Needs
    on its own and no flag can outlive the outcome that set it.
    """
    return {need_id for plo in plos for need_id in plo.source_need_ids}


def plos_citing(plos: Iterable[PLO], need_ids: Iterable[str]) -> list[PLO]:
    """The outcomes a merge over `need_ids` would supersede.

    Every PLO that cites any of the Needs, not only ones citing all of them: the
    invariant is one outcome per Need, so an outcome sharing a single Need with
    the merge cannot survive it.
    """
    wanted = set(need_ids)
    return [plo for plo in plos if wanted & set(plo.source_need_ids)]


def synthesis_order(needs: list[Need]) -> list[Need]:
    """Most-demanded first, `need_id` breaking ties so numbering is reproducible."""
    return sorted(needs, key=lambda n: (-n.demand_score, n.need_id))


def _unit_is_optional(unit: list[Need]) -> bool:
    # The same rule validate_and_build applies to the PLO the unit becomes.
    return all(n.is_optional for n in unit)


def _select_slots(units: list[list[Need]]) -> list[_Slot]:
    """Number the units, most-demanded first, capping the core series.

    Pure code, and no awaits: the ceiling and the id scheme are decided before a
    single draft goes out, so PLO1 is the capability the market asked for most.
    Every unit is one Need: duplicate Needs were merged upstream by
    need_combination's Agent 2, so numbering is reproducible on the same Needs.
    """
    slots: list[_Slot] = []
    for is_optional in (False, True):
        series = sorted(
            (u for u in units if _unit_is_optional(u) is is_optional),
            key=lambda u: (-u[0].demand_score, u[0].need_id),
        )
        if not is_optional and len(series) > MAX_CORE_PLOS:
            # Logged, not silent: a designer looking at 22 Needs and 10 PLOs has to
            # be able to find out which lost and why. plo_report shows the same
            # set on the review page.
            dropped = [n.need_id for u in series[MAX_CORE_PLOS:] for n in u]
            logger.warning(
                f"{len(series)} core PLO candidates exceed the {MAX_CORE_PLOS}-PLO "
                f"ceiling — synthesizing the {MAX_CORE_PLOS} highest-demand ones and "
                f"leaving {len(dropped)} Need(s) unused: {', '.join(dropped)}"
            )
            series = series[:MAX_CORE_PLOS]
        slots += [
            _Slot(
                plo_id=format_plo_id(index, is_optional=is_optional),
                needs=unit,
                is_optional=is_optional,
            )
            for index, unit in enumerate(series, start=1)
        ]
    return slots


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


class _Slot(BaseModel):
    """A numbered position and the Needs that will fill it.

    Decided before any LLM call, so the MAX_CORE_PLOS ceiling and the id scheme
    stay pure code — and so the numbering comes from demand_score rather than
    from whichever draft happens to finish first.
    """

    plo_id: str
    needs: list[Need]
    is_optional: bool


def _adopt(draft: _PLODraft, authoritative_need_ids: list[str]) -> _PLODraft:
    """Pin the evidence trail onto a draft. Every draft enters through here.

    One pin site, three callers — the initial draft, each hard-loop fix, and
    each validator-requested repair. Pinning the ids in three places is exactly
    the "two copies drifting apart under future edits" this module already warns
    about, and it is the invariant
    `test_gate_judges_authoritative_need_ids_not_the_models_echo` exists to
    protect: the gate must judge the ids that will actually ship, not whatever
    the model echoed back.

    A copy, not an alias. Pinning the caller's own list onto several drafts was
    harmless while synthesis was sequential; it is a shared-mutable footgun now
    that PLOs are validated concurrently.

    The subject prefix ("บัณฑิตสามารถ...") is stripped here for the same reason
    the ids are pinned here: this is the one door every shippable statement
    comes through, so a repair that writes the prefix back loses it again.
    """
    draft.source_need_ids = list(authoritative_need_ids)
    draft.statement_th = strip_outcome_prefix(draft.statement_th)
    return draft


async def draft_from_needs(
    metadata: ProgramMetadata,
    needs: list[Need],
    plo_id: str,
    *,
    note_th: str | None = None,
) -> _PLODraft | None:
    """One synthesis call: Need(s) in, an unvalidated draft out.

    Split from validation so the stage can draft every PLO before judging any
    of them — the validator has to be able to see the whole set (is this one
    just another PLO restated?), and that is impossible while drafting and
    judging are fused in one sequential loop.

    The evidence trail is pinned here, before the draft leaves. It used to be
    pinned inside the gate, which was the only thing between the model's echo
    and the database; after the split it is not, so the pin moves to where the
    draft is created.

    Returns None when the model call fails outright — the caller decides whether
    that is fatal.

    `note_th` is optional designer guidance on wording. It reaches this prompt
    only, never a repair prompt, whose job is to fix one named criterion while
    preserving the substance it was handed.
    """
    if not needs:
        raise ValueError("draft_from_needs requires at least one Need")

    try:
        response = await complete_plo_synthesis(
            _SingleDraftResponse,
            build_plo_from_need_prompt(metadata, needs, note_th=note_th),
            max_retries=_MAX_RETRIES,
            max_tokens=PLO_MAX_TOKENS,
            reasoning_max_tokens=PLO_REASONING_MAX_TOKENS,
        )
    except Exception as exc:
        ids = ", ".join(n.need_id for n in needs)
        logger.warning(f"PLO synthesis failed for Need(s) {ids} ({plo_id}): {exc}")
        return None

    return _adopt(response.plo, [n.need_id for n in needs])


async def validate_and_build(
    draft: _PLODraft,
    *,
    metadata: ProgramMetadata,
    needs: list[Need],
    program_id: str,
    plo_id: str,
    known_need_ids: set[str],
    siblings: Sequence[SiblingSummary] = (),
    pending_need_statements_th: Sequence[str] = (),
    evidence_index: EvidenceIndex | None = None,
    run_validation: bool = True,
    allow_repair: bool = True,
) -> PLO | None:
    """Run one draft past the validation agent, then judge it in pure code.

    `run_validation=False` is the per-run switch (`POST /plos/run`): it skips
    the agent for this run only. The pure-code gate below still runs either way.
    `allow_repair=False` lets the agent judge but never rewrite the sentence (a
    designer-edited PLO being revalidated); the gate is unchanged.

    **The last word is the code gate, always.** `hard_failures` runs on the
    final statement whatever way the agent exited — finished, out of budget,
    endpoint down — and that call alone sets `smart_escalated`. The agent's only
    route to the outcome is getting `complete_plo_synthesis` to write a better
    sentence, which this function then re-judges, so its influence is monotone:
    it can shrink the failure list and never declare it empty. That is immutable
    rule 5 held by construction rather than by the agent's good manners.

    Never returns None for a *failed verdict*: an escalated PLO is kept for
    human repair, never dropped. None means the outcome could not be
    constructed at all — see the ValidationError guard below.
    """
    authoritative_need_ids = [n.need_id for n in needs]
    ctx = ValidationContext(
        program_id=program_id,
        plo_id=plo_id,
        draft=draft,
        authoritative_need_ids=tuple(authoritative_need_ids),
        known_need_ids=frozenset(known_need_ids),
        needs_by_id={n.need_id: n for n in needs},
        cited_evidence_ids=frozenset(eid for n in needs for eid in n.source_evidence_ids),
        siblings=list(siblings),
        pending_need_statements_th=list(pending_need_statements_th),
        evidence_index=evidence_index,
        budget=ToolBudget(),
    )
    result = await run_smart_agent(
        draft, ctx, metadata, enabled=run_validation, allow_repair=allow_repair
    )

    # The authoritative gate. Not the agent's reading of it — the same pure
    # function, on the statement that will actually ship.
    fails = hard_failures(
        result.statement_th,
        result.action_verb_th,
        list(authoritative_need_ids),
        known_need_ids,
    )
    escalated = bool(fails)
    if escalated:
        logger.warning(
            f"  PLO {plo_id} escalated after {result.repair_count} repair(s): "
            f"{[f.value for f in fails]}"
        )
    logger.info(
        f"  {plo_id} code gate (authoritative): {[f.value for f in fails]} — "
        f"{'escalated' if escalated else 'not escalated'}"
    )

    verdicts = result.soft_verdicts
    # Soft verdicts reach SMARTCheck so `passed` stops reporting success for a
    # flagged outcome. They still never escalate — that reads `fails` alone.
    smart_check = SMARTCheck(
        specific=HardCriterion.S_VERB not in fails and verdicts["specific_object_ok"],
        measurable=HardCriterion.M_FORBIDDEN not in fails and verdicts["measurable_ok"],
        # A asks whether this is the graduate's to achieve. The Bloom level is one
        # way the answer is no; an outcome whose doer is the institution, or whose
        # work belongs to another profession, are the other two.
        achievable=verdicts["achievable_ok"] and verdicts["actor_ok"] and verdicts["scope_ok"],
        relevant=HardCriterion.R_EVIDENCE not in fails and verdicts["relevant_needs_ok"],
        timely=verdicts["time_bound_ok"],
        notes_th=result.diagnosis_th,
        # The hard failures are recorded, not just logged. This is the gap the
        # old gate left: a designer could see that a PLO escalated and never
        # which criterion did it.
        findings=hard_findings_for(fails, [CRITERION_FIX_HINTS_TH[f] for f in fails])
        + result.soft_findings,
    )

    # Evidence ids are never asked of the model (see build_plo_from_need_prompt) —
    # they are derived entirely from the Needs' own verified evidence trail, so
    # there is nothing here for a model to invent.
    evidence_ids = sorted({eid for n in needs for eid in n.source_evidence_ids})
    diagnosis = result.diagnosis_th
    if escalated and result.reason in (
        ValidationReason.FINISHED,
        ValidationReason.FINISHED_AT_BUDGET,
        ValidationReason.FINISHED_AFTER_MALFORMED,
    ):
        # The agent signed off and code disagreed. Say so, or the diagnosis
        # reads as an explanation of a PLO that passed.
        named = ", ".join(f.value for f in fails)
        diagnosis = f"โค้ดตรวจประโยคสุดท้ายแล้วยังไม่ผ่าน ({named}) · {diagnosis or ''}".strip(" ·")

    try:
        return PLO(
            plo_id=plo_id,
            program_id=program_id,
            statement_th=result.statement_th,
            statement_en=result.statement_en,
            bloom_level=result.bloom_level,
            action_verb_th=result.action_verb_th,
            smart_check=smart_check,
            # Pinned by _adopt before the gate ran; reuse rather than recomputing.
            source_need_ids=result.source_need_ids,
            source_evidence_ids=evidence_ids,
            rationale_th=result.rationale_th,
            distinctive_feature_th=result.distinctive_feature_th,
            version=1,
            smart_retry_count=result.repair_count,
            smart_escalated=escalated,
            soft_flags=result.soft_flags,
            smart_validated_by="agent" if result.ran else "code_only",
            smart_diagnosis_th=diagnosis,
            # Optional only when every contributing Need is optional.
            is_optional=all(n.is_optional for n in needs),
        )
    except ValidationError as exc:
        # PLO's own validators can still refuse what the gate accepted —
        # check_evidence is not gated on escalation, so a Need with an empty
        # evidence trail lands here. Now that PLOs are built concurrently, an
        # exception escaping this frame would take out every other outcome in
        # the same gather; a gap is the same failure mode as a failed draft and
        # is already handled. Not gather(return_exceptions=True): that loses
        # which slot failed.
        logger.warning(f"  {plo_id} could not be built from its verdict: {exc}")
        return None


async def synthesize_from_needs(
    metadata: ProgramMetadata,
    needs: list[Need],
    program_id: str,
    known_need_ids: set[str],
    plo_id: str,
    *,
    note_th: str | None = None,
    siblings: Sequence[SiblingSummary] = (),
    evidence_index: EvidenceIndex | None = None,
) -> PLO | None:
    """Draft one PLO from one or more Needs, then run it through the SMART gate.

    The two halves in sequence, kept as one entry point for the designer-driven
    N:1 merge endpoint, which creates a single outcome and has no set to draft
    first. The stage calls the halves directly so it can draft all of them
    before judging any.
    """
    drafted = await draft_from_needs(metadata, needs, plo_id, note_th=note_th)
    if drafted is None:
        return None
    return await validate_and_build(
        drafted,
        metadata=metadata,
        needs=needs,
        program_id=program_id,
        plo_id=plo_id,
        known_need_ids=known_need_ids,
        siblings=siblings,
        evidence_index=evidence_index,
    )


# Program ids with a synthesis run currently in flight. Module-level and
# per-process: a second run for the same program used to start while the first
# was still mid-flight (minutes of LLM calls), and the second request's HTTP
# response did not match what ended up in the database — the delete/insert at
# the end of this stage ran twice, so a PLO card could read "2 needs" while its
# trace panel, which reads the DB fresh, showed the other run's 1. Overlapping
# runs can also interleave their delete and insert and leave a mixed set behind.
# This guard refuses the second run outright rather than letting that race
# happen. It is a per-process set, so it only covers the single-process
# deployment this PoC runs (`python -m curriculum_agent.api`); a multi-worker
# deployment would need a DB-level lock instead, since each worker would have
# its own copy of this set.
_SYNTHESIS_IN_FLIGHT: set[str] = set()


class SynthesisAlreadyRunning(RuntimeError):
    """Raised by `run` when a program already has a synthesis run in flight."""


async def run(state: AgentState) -> AgentState:
    """Single-flight guard around `_run`: refuse a second concurrent run.

    The check-and-add is a plain `in` test followed by a `set.add`, with no
    `await` between them — asyncio is single-threaded and only switches tasks at
    an `await`, so nothing can interleave between the check and the add within
    one event loop, making this atomic in practice despite not being a lock.
    The slot is freed in `finally` so a run that raises (empty Needs, a dead
    endpoint) or is cancelled does not strand the program unable to retry.
    """
    program_id = state.get("program_id", "unknown")
    if program_id in _SYNTHESIS_IN_FLIGHT:
        raise SynthesisAlreadyRunning(
            f"กำลังสังเคราะห์ PLO ของโปรแกรม '{program_id}' อยู่ — รอให้รอบเดิมเสร็จก่อน"
        )
    _SYNTHESIS_IN_FLIGHT.add(program_id)
    try:
        return await _run(state)
    finally:
        _SYNTHESIS_IN_FLIGHT.discard(program_id)


async def _run(state: AgentState) -> AgentState:
    """Stage 4: one PLO per active Need."""
    program_id = state.get("program_id", "unknown")
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run PLO synthesis stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)
    note_th = state.get("designer_note")
    run_validation = state.get("run_validation", True)
    if not run_validation:
        logger.info("plo_synthesis: validation agent skipped for this run (run_validation=false)")

    need_dicts = state.get("needs")
    if need_dicts is None:
        # Same input whichever way this stage was reached: POST /plos/run loads
        # the Needs and hands them over, and a graph session that gets here
        # without need_combination in the same run reads the stored set rather
        # than synthesising from nothing.
        stored = await NeedRepository().list_active_by_program(program_id)
        need_dicts = [n.model_dump(mode="json") for n in stored]
        logger.info(f"Stage 4: loaded {len(need_dicts)} Needs from storage")
        if not need_dicts:
            raise ValueError(
                f"ยังไม่มี Need สำหรับโปรแกรม '{program_id}' กรุณารันขั้นรวมทักษะเป็น Need ก่อนสังเคราะห์ PLO"
            )
    needs = [Need.model_validate(d) for d in need_dicts]
    if not needs:
        # An empty list, not a missing key: need_combination ran in this session
        # and returned no groups. It did not fail, so the message must not send
        # the designer to re-run it and wait for a different answer — the thing
        # to look at is what it was given.
        raise ValueError(
            f"need_combination รันแล้วแต่ไม่ได้ Need เลยสำหรับโปรแกรม '{program_id}' "
            "— ตรวจทักษะที่สกัดได้ที่ขั้น Skill Extraction ก่อน"
        )

    # Every id it was given, merged-away originals included: this is the check
    # that a PLO cites a Need that exists, not a second selection step.
    known_need_ids = {n.need_id for n in needs}

    # A Need merged into another is represented by the merged Need; drafting from
    # the original would put one demand behind two PLOs. The graph path hands over
    # need_combination's whole output, originals included, so filter here whatever
    # the source of the list.
    merged_away = [n for n in needs if n.merged_into is not None]
    if merged_away:
        logger.info(
            f"Stage 4: ข้าม Need ที่ถูกรวมแล้ว {len(merged_away)} ใบ: "
            f"{', '.join(n.need_id for n in merged_away)}"
        )
        needs = [n for n in needs if n.merged_into is None]

    # Before the series split, so it covers optional PLOs too — off-field is
    # off-field whether the outcome is core or supplementary — and before the
    # ceiling below, which is the part that actually matters: filtering after the
    # ceiling would let out-of-scope Needs occupy slots in the top ten and then
    # be dropped, yielding seven PLOs while in-scope Needs waited further down
    # the queue. A filtered Need is not deleted: it stays stored, still traceable,
    # and the report lists it.
    filtered = [n for n in needs if not is_in_scope(n)]
    if filtered:
        off_field = sum(1 for n in filtered if n.in_field_ratio < SCOPE_PASS_RATIO)
        off_grad = sum(1 for n in filtered if n.graduate_capability_ratio < SCOPE_PASS_RATIO)
        # The two figures stay separate even though they will usually be equal.
        # The day they disagree is the day the two axes have started to measure
        # different things, and this line is where that shows up without an eval.
        logger.warning(
            f"Stage 4: กรอง Need นอกขอบเขตออก {len(filtered)} ใบ "
            f"(นอกสาขา {off_field}, ไม่ใช่สมรรถนะบัณฑิต {off_grad}): "
            f"{', '.join(n.need_id for n in filtered)}"
        )
        needs = [n for n in needs if is_in_scope(n)]

    # A fallback Need's statement is a marker plus a comma-joined list of skill
    # names, not a requirement — need_combination writes it when the sentence
    # call was rejected or never reached the model, precisely so the designer
    # sees it at the checkpoint instead of a PLO getting drafted from a word
    # list. Nothing downstream of need_combination used to check for it: on the
    # tourism program a `[ต้องทบทวน] การบูรณาการความรู้ด้านสุขภาพ…` Need was
    # synthesised straight into PLO2, a capability invented from skill names
    # rather than traced to anything a stakeholder asked for. Dropped the same
    # way as an out-of-scope Need — stays stored and traceable, is not offered
    # to the duplicate check, and does not take a slot, so the slot goes to the
    # next Need below the cut. known_need_ids above already covers these ids,
    # since it is computed before either filter.
    unwritten = [n for n in needs if is_unwritten_need(n)]
    if unwritten:
        logger.warning(
            f"Stage 4: ข้าม Need ที่ยังไม่ได้เขียนประโยค {len(unwritten)} ใบ "
            "(ผู้ออกแบบหลักสูตรต้องเขียนเอง หรือรันขั้นรวมทักษะเป็น Need ใหม่): "
            f"{', '.join(n.need_id for n in unwritten)}"
        )
        needs = [n for n in needs if not is_unwritten_need(n)]

    logger.info(f"Stage 4: synthesizing PLOs from {len(needs)} Needs")

    # One Need per slot. Duplicates were already merged into one Need by
    # need_combination (Agent 2), so nothing is folded here.
    units = [[n] for n in synthesis_order(needs)]
    slots = _select_slots(units)

    # One index per stage run, shared by every validation: EvidenceRepository
    # has no get_by_id, so ten validators reading overlapping evidence would
    # otherwise be ten full-table reads.
    evidence_index = EvidenceIndex(program_id)

    # Phase A: draft every slot. One provider call each, so the per-call ceiling
    # is the right bound here.
    drafts = await gather_bounded(
        settings.llm_max_concurrency,
        [
            (
                lambda slot=slot: draft_from_needs(  # type: ignore[misc]
                    metadata, slot.needs, slot.plo_id, note_th=note_th
                )
            )
            for slot in slots
        ],
    )
    for slot, drafted in zip(slots, drafts, strict=True):
        if drafted is None:
            # Leave the number unused rather than renumbering the rest. A gap
            # says "this Need failed"; renumbering would silently change what
            # PLO4 refers to between runs, and designers cite these ids.
            logger.warning(f"  {slot.plo_id} not produced — its number stays unused")
    produced = [(slot, d) for slot, d in zip(slots, drafts, strict=True) if d is not None]

    # Phase B: validate each draft against the whole drafted set.
    #
    # The siblings are the *drafts*, not the repaired statements. A repaired PLO1
    # may no longer overlap PLO2 the way its draft did — but validating against
    # post-repair siblings is a second full pass at N times the cost with no
    # fixed point, and sibling context is advisory input to a diagnosis rather
    # than a verdict of its own. Say so, because "the validator said PLO3
    # duplicates PLO7" reads oddly once the shipped PLO7 has moved.
    #
    # A slot whose draft failed contributes no sibling: the validator sees nine,
    # not a hole, which matches the gap-preserving id policy.
    all_siblings = [
        SiblingSummary.from_draft(slot.plo_id, d, is_optional=slot.is_optional)
        for slot, d in produced
    ]

    # A different ceiling from phase A, on purpose. Validation is a loop of
    # several serial calls per PLO, so the number that bounds it is how many
    # loops run at once, not how many calls are in flight.
    results = await gather_bounded(
        settings.validation_max_concurrent_plos,
        [
            (
                lambda slot=slot, d=d: validate_and_build(  # type: ignore[misc]
                    d,
                    metadata=metadata,
                    needs=slot.needs,
                    program_id=program_id,
                    plo_id=slot.plo_id,
                    known_need_ids=known_need_ids,
                    # Never itself: an outcome in its own sibling list is a
                    # duplicate the validator will faithfully discover.
                    siblings=[s for s in all_siblings if s.plo_id != slot.plo_id],
                    evidence_index=evidence_index,
                    run_validation=run_validation,
                )
            )
            for slot, d in produced
        ],
    )
    # gather preserves *input* order, so this stays PLO1..PLOn then OPT1..OPTn
    # exactly as the sequential loop produced. Do not switch to as_completed for
    # a progress bar: PLO4 would start meaning a different outcome between runs.
    plos: list[PLO] = [p for p in results if p is not None]

    core = sum(1 for p in plos if not p.is_optional)
    if core < MIN_NEEDS:
        # Naming the cause on this line, not on a separate one: a designer has to
        # tell "not enough in-scope evidence" apart from "too few Needs to begin
        # with" (which need_combination warns about), and two warnings in
        # different parts of the log leave them to join it up themselves.
        causes = []
        if filtered:
            causes.append(f"กรอง Need นอกขอบเขตออก {len(filtered)} ใบก่อนร่าง (หลักฐานในขอบเขตไม่พอ)")
        cause = " · ".join(causes) or "need_combination should have enforced this"
        logger.warning(
            f"Stage 4 produced {core} core PLOs, below the {MIN_NEEDS} minimum policy — "
            f"{cause}; review at the checkpoint"
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
