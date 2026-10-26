from __future__ import annotations

import uuid
from typing import Any, Literal

from instructor.core.exceptions import ValidationError as InstructorValidationError
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from pydantic import ValidationError as PydanticValidationError

from curriculum_agent.data.repositories import NeedRepository, SkillRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_need_combination
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    StakeholderType,
)
from curriculum_agent.prompts.program_context import build_program_context_th
from curriculum_agent.prompts.summarize_need import (
    MAX_LISTED_SKILLS,
    MAX_RATIONALE_CHARS,
    MIN_RATIONALE_CHARS,
    MIN_STATEMENT_CHARS,
    build_summarize_need_prompt,
)
from curriculum_agent.stages.demand import (
    build_scoring_corpus,
    classification_coverage,
    compute_demand_score,
    is_optional_group,
)
from curriculum_agent.stages.llm_clustering import cluster_skill_names, validate_assignments
from curriculum_agent.stages.need_grouping import (
    MIN_NEEDS,
    PROVIDER_MARKER_TH,
    REVIEW_MARKER_TH,
    allocate_cluster_targets,
    bucket_by_ksec,
    dedupe_with_bloom_max,
    find_code_identifier,
    find_vague_phrase,
    group_bloom,
    looks_like_a_skill_list,
    normalize_need_name,
    resolve_need_ksec,
    supporting_coverage,
)

# Instructor re-asks the model when _NeedStatement's validator raises, quoting
# the error back. Three attempts: the leak is sporadic, so a retry almost always
# clears it, and a group that still fails falls back to its skill names.
_STATEMENT_ATTEMPTS = 3

# Prefixes on a Need whose sentence never got written, both visible in the UI's
# Need list — which is where the designer decides what to do about it, and the
# two failures need opposite responses. A rejected sentence is a content problem
# only a human can settle; a call that never completed is infrastructure, and
# re-running the stage is very likely all it takes. One marker for both left the
# designer rewriting Needs by hand that a retry would have produced.
#
# Defined in need_grouping now (plo_synthesis and the merge route need the
# predicate built on them without pulling in this module's LLM client and
# prompt builder); aliased here under the old underscore spelling so this
# module's own code below, and callers like `nc._REVIEW_MARKER_TH` in the test
# suite, don't have to change.
_REVIEW_MARKER_TH = REVIEW_MARKER_TH
_PROVIDER_MARKER_TH = PROVIDER_MARKER_TH


# The three reasons a shown member can be left out of the sentence. Checked
# against the raw answer in the never-fail validator below — an entry naming
# anything else is dropped rather than raised, the same discipline as
# supporting_indices.
_NOT_COVERED_REASONS = {"low_freq", "not_graduate", "off_task"}


class _NotCovered(BaseModel):
    """One shown member the sentence does not speak for, and why.

    A measurement, like supporting_indices — it is read by `_log_coverage` and
    never stored, so nothing here can turn a well-written sentence into a
    `[ต้องทบทวน]` fallback.
    """

    index: int
    reason_code: Literal["low_freq", "not_graduate", "off_task"]
    note_th: str = ""


class _DesignerInputUse(BaseModel):
    """Whether the optional designer note changed a word choice, and how.

    Logged once per run (`need_combination.run`), not stored — there is no
    threshold yet, only a first distribution to look at, the same reasoning
    ticket 18 gives for supporting_indices.
    """

    used: bool
    detail_th: str = ""


def _model_answered_but_was_rejected(exc: BaseException) -> bool:
    """True when the sentence came back and _NeedStatement refused it.

    Instructor raises the same InstructorRetryException whether it ran out of
    re-asks over a validator or the provider never answered, wrapping the last
    exception rather than distinguishing them — so the wrapped chain is what has
    to be read. A ValidationError anywhere in it means the model produced text
    and our own guards rejected it.

    Walks args as well as __cause__/__context__ because Instructor passes the
    wrapped exception positionally, where neither chaining attribute is set.
    """
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, PydanticValidationError | InstructorValidationError):
            return True
        stack.extend(a for a in getattr(current, "args", ()) if isinstance(a, BaseException))
        stack.extend(nxt for nxt in (current.__cause__, current.__context__) if nxt is not None)
    return False


class _NeedStatement(BaseModel):
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None
    rationale_th: str = Field(min_length=1)
    # Positions into the listed names that the sentence says it speaks for.
    # Deliberately unvalidated: it is a measurement, and a validator that raised
    # here would send Instructor round again and, three misses later, turn a
    # well-written sentence into a `[ต้องทบทวน]` fallback. `supporting_coverage`
    # discards what it cannot use instead. None — the model sent no list — is kept
    # apart from [] so a dropped field cannot read as "covers nothing".
    supporting_indices: list[int] | None = None
    # Shown members the sentence does not speak for, and why. Same measurement
    # discipline as supporting_indices: never-fail, logged, never stored.
    not_covered_indices: list[_NotCovered] | None = None
    # Whether the designer's optional note changed a word choice. Logged once
    # per run, not stored — see the class docstring.
    designer_input_used: _DesignerInputUse | None = None

    @field_validator("supporting_indices", mode="before")
    @classmethod
    def _never_fail_on_the_measurement(cls, value: Any) -> list[int] | None:
        """Reduce whatever arrived to its integers, or to None if it is not a list.

        Leaving the field unvalidated is not enough: pydantic still type-checks
        `list[int]`, so an answer of "0,1,2" would fail the call over a number
        the stage only logs.
        """
        if not isinstance(value, list):
            return None
        kept: list[int] = []
        for item in value:
            if isinstance(item, bool):
                continue
            if isinstance(item, int) or (isinstance(item, float) and item.is_integer()):
                kept.append(int(item))
            elif isinstance(item, str) and item.strip().isdigit():
                kept.append(int(item.strip()))
        return list(dict.fromkeys(kept))

    @field_validator("not_covered_indices", mode="before")
    @classmethod
    def _never_fail_on_not_covered(cls, value: Any) -> list[dict[str, Any]] | None:
        """Drop a malformed entry instead of failing the whole call.

        Not a list at all -> None. Within a list, an entry with a non-int index
        or an unrecognised reason_code is dropped rather than raised — the same
        reasoning as supporting_indices: this is read by a log line, and three
        retries over a field nobody stores would turn a good sentence into a
        `[ต้องทบทวน]` fallback.
        """
        if isinstance(value, _NotCovered):
            return [value.model_dump()]
        if not isinstance(value, list):
            return None
        kept: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, _NotCovered):
                kept.append(item.model_dump())
                continue
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if isinstance(index, bool):
                continue
            if isinstance(index, float) and index.is_integer():
                index = int(index)
            if not isinstance(index, int):
                continue
            reason_code = item.get("reason_code")
            if reason_code not in _NOT_COVERED_REASONS:
                continue
            note_th = item.get("note_th", "")
            if not isinstance(note_th, str):
                note_th = ""
            kept.append({"index": index, "reason_code": reason_code, "note_th": note_th})
        return kept

    @field_validator("designer_input_used", mode="before")
    @classmethod
    def _never_fail_on_designer_input_used(cls, value: Any) -> dict[str, Any] | None:
        """A malformed answer loses the whole field rather than failing the call.

        Unlike not_covered_indices this is a single object, not a list, so there
        is no per-entry salvage to do: either it names a real bool `used` or the
        field becomes None, the same way a non-list supporting_indices does.
        """
        if isinstance(value, _DesignerInputUse):
            return value.model_dump()
        if not isinstance(value, dict):
            return None
        used = value.get("used")
        if not isinstance(used, bool):
            return None
        detail_th = value.get("detail_th", "")
        if not isinstance(detail_th, str):
            detail_th = ""
        return {"used": used, "detail_th": detail_th}

    @field_validator("rationale_th")
    @classmethod
    def _reject_an_empty_reason(cls, rationale: str) -> str:
        """A reason that says nothing is worse than no reason at all.

        It renders beside the sentence it explains and will be read as the
        justification for that Need, so "เป็นทักษะที่เกี่ยวข้องกัน" is not a weak
        answer — it is a claim with nothing behind it in the place a reader looks
        for one. The vagueness scan is the one `statement_th` already uses, since
        the failure is the same failure and two vocabularies for it is how they
        come to disagree.

        The upper bound is not cosmetic either: this field rides on every Need
        row and inside a card, and it is the one place in the response where a
        model can spend arbitrary tokens without any rule pushing back.
        """
        trimmed = rationale.strip()
        if len(trimmed) < MIN_RATIONALE_CHARS:
            raise ValueError(
                f"rationale_th สั้นเกินไป ({len(trimmed)} ตัวอักษร) ต้องยาวอย่างน้อย "
                f"{MIN_RATIONALE_CHARS} ตัวอักษร และบอกว่าทักษะกลุ่มนี้ใช้ทำหน้าที่หรืองานร่วมอะไร"
            )
        if len(trimmed) > MAX_RATIONALE_CHARS:
            raise ValueError(
                f"rationale_th ยาวเกินไป ({len(trimmed)} ตัวอักษร) ต้องไม่เกิน "
                f"{MAX_RATIONALE_CHARS} ตัวอักษร ให้สรุปเหตุผลให้สั้นลง"
            )
        vague = find_vague_phrase(trimmed)
        if vague:
            raise ValueError(
                f"rationale_th กว้างเกินไปจนไม่ได้บอกเหตุผล: '{vague}' "
                "ให้ระบุหน้าที่หรืองานร่วมที่ทักษะในกลุ่มนี้ใช้ทำแทน"
            )
        return rationale

    @field_validator("statement_th")
    @classmethod
    def _reject_code_tokens(cls, statement: str) -> str:
        """Bounce a sentence carrying a code identifier back to the model.

        A small model tokenising Thai byte-by-byte occasionally emits a token
        from its code training instead of the Thai it was asked for — one stored
        Need read "...เป็นผู้ประกอบการ หน.getDefault รับฟังผู้บริหาร...", built
        from two clean skill names. Raising here is what makes Instructor retry
        with the failure quoted back, the same shape as the SMART retry loop.
        """
        found = find_code_identifier(statement)
        if found:
            raise ValueError(
                f"statement_th ต้องเป็นภาษาไทยล้วน พบข้อความที่เป็นโค้ด: '{found}' "
                "ห้ามใส่ชื่อฟังก์ชัน ชื่อตัวแปร หรือโค้ดในประโยค"
            )
        return statement

    @field_validator("statement_th")
    @classmethod
    def _require_plo_ready(cls, statement: str) -> str:
        """Reject the two shapes a Need cannot become a PLO from.

        plo_synthesis drafts exactly one PLO per Need and is handed nothing but
        this sentence. A placeholder ("ทักษะที่จำเป็นต่อการทำงาน") or a joined
        skill list therefore does not merely weaken the PLO — it makes the
        synthesis model invent the capability, with no evidence behind what it
        invents. Raising here sends the group back through Instructor with the
        reason quoted, the same shape as the code-token guard above.
        """
        trimmed = statement.strip()
        if len(trimmed) < MIN_STATEMENT_CHARS:
            raise ValueError(
                f"statement_th สั้นเกินไป ({len(trimmed)} ตัวอักษร) ต้องยาวอย่างน้อย "
                f"{MIN_STATEMENT_CHARS} ตัวอักษร และระบุความสามารถ วัตถุของงาน "
                "และบริบทการทำงานให้ครบ"
            )
        if looks_like_a_skill_list(trimmed):
            raise ValueError(
                "statement_th เป็นการนำชื่อทักษะมาต่อกัน (ด้วยจุลภาค หรือด้วยการเว้นวรรคแล้วปิดท้ายด้วย 'และ') "
                "ให้เขียนเป็นประโยคความต้องการหนึ่งประโยคที่ระบุความสามารถเดียว"
            )
        vague = find_vague_phrase(trimmed)
        if vague:
            raise ValueError(
                f"statement_th มีคำกว้างที่ไม่บอกเนื้อหา: '{vague}' ให้ระบุความสามารถและวัตถุของงานที่เจาะจงแทน"
            )
        return statement


class _Group(BaseModel):
    """A candidate Need before its sentence is written."""

    ksec: KSECCategory
    skill_ids: list[str]
    evidence_ids: list[str]
    # Most-mentioned first, and skill_frequencies[i] is how many member rows
    # collapsed into skill_names[i]. The order is what the summarize prompt's
    # listing cap cuts from the end of, and the counts are what coverage weighs.
    skill_names: list[str]
    skill_frequencies: list[int]
    bloom_level: BloomLevel
    demand_score: float
    is_optional: bool
    classification_coverage: dict[str, int]
    stakeholder_coverage: dict[StakeholderType, int]
    stakeholder_types: list[StakeholderType]
    in_field_skill_count: int
    graduate_capability_skill_count: int


def _coverage_breakdown(
    shown: int, claimed: set[int] | None, not_covered: list[_NotCovered] | None
) -> tuple[dict[str, int], int]:
    """How many shown members fall under each not_covered reason, and how many
    are claimed by neither supporting_indices nor not_covered_indices.

    Pure and separate from the logging call so it can be tested without loguru.
    An index past `shown` was never on the page — a model citing one is
    guessing — so it is dropped here exactly the way `_log_coverage` already
    drops an out-of-range supporting index.
    """
    reasons_by_index: dict[int, str] = {}
    for entry in not_covered or []:
        if 0 <= entry.index < shown:
            reasons_by_index[entry.index] = entry.reason_code
    reason_counts: dict[str, int] = {}
    for reason in reasons_by_index.values():
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    accounted = (claimed or set()) | set(reasons_by_index)
    return reason_counts, shown - len(accounted)


def _log_coverage(group: _Group, written: _NeedStatement) -> None:
    """One line per written Need: how much of its group the sentence claims.

    Logged, not stored, and no threshold. Ticket 18 says not to set a number
    before there is a reason for it, and a first run's distribution is that
    reason; a column and a checkpoint flag can follow once the figure has shown
    it means something. Fallback Needs are skipped — nobody wrote their sentence.

    Extended with not_covered_indices and an "unaccounted" count under the same
    discipline: shown members the model neither claimed nor explained are the
    gap between the two fields, and are only worth watching, not acting on yet.
    """
    names = len(group.skill_names)
    shown = min(names, MAX_LISTED_SKILLS)
    mentions = sum(group.skill_frequencies)
    # A position past the cap was never on the page, so a model citing one is
    # guessing; it counts for nothing even though the name exists.
    claimed = (
        None
        if written.supporting_indices is None
        else sorted({i for i in written.supporting_indices if 0 <= i < shown})
    )
    reason_counts, unaccounted = _coverage_breakdown(
        shown, set(claimed) if claimed is not None else None, written.not_covered_indices
    )
    not_covered_part = (
        ", not_covered " + ", ".join(f"{r}={c}" for r, c in sorted(reason_counts.items()))
        if reason_counts
        else ""
    )
    unaccounted_part = f", unaccounted {unaccounted}/{shown}"
    coverage = supporting_coverage(claimed, group.skill_frequencies)
    if coverage is None or claimed is None:
        logger.info(
            f"Need coverage {group.ksec.value}: not reported ({names} names, {mentions} mentions)"
            f"{not_covered_part}{unaccounted_part}"
        )
        return
    capped = f" ({names - shown} past the listing cap)" if shown < names else ""
    logger.info(
        f"Need coverage {group.ksec.value}: {coverage:.0%} of {mentions} mentions, "
        f"{len(claimed)}/{names} names{capped}{not_covered_part}{unaccounted_part}"
    )


async def _build_groups(
    skills: list[ExtractedSkill],
    stakeholder_type_by_evidence: dict[str, str],
    program_context: str | None = None,
) -> list[_Group]:
    """Cluster within each KSEC bucket and score every resulting group.

    Bucketing before clustering is what guarantees a group never mixes tags; E and
    C share the EC bucket, and resolve_need_ksec hands back E or C when a group
    turns out to be purely one of them.

    `stakeholder_type_by_evidence` is built from the skills by the caller, so
    scoring stays inside what extraction produced.

    `program_context` is the program's field and degree level. It settles what an
    ambiguous skill name means before the names are grouped by it — it is intake
    metadata, not evidence, so nothing about a Need's evidence trail changes.

    Each bucket is clustered as **two populations**, split by whether the name is
    a graduate capability. Measured cause, not a guess: on the stored corpus the
    S bucket returned 17-21 groups against a target of 8, and the extra ones were
    not the model's judgement — it covered only part of the index list and
    `validate_assignments` filled the rest with one singleton per unassigned
    name, twelve and thirteen of them. Holding out the eleven rows extraction
    flagged `is_graduate_capability=False` dropped the mean group count from 15.7
    to 9.3 across three runs; a control of the same *length* that kept those
    eleven stayed at 15.0, so it is the content and not the list length. All
    eleven were administrator, faculty or institutional_direction rows, and
    extraction had judged every one correctly: designing the curriculum and
    raising the graduate employment rate are not things a graduate does. They do
    not belong to any competency the other names form, the model cannot place
    them, and the groups around them fragment. Ticket 16 has the numbers.

    **Nothing is dropped, and that distinction is the whole point.** Both
    populations are clustered and both become Needs, traceable as before; the
    scope guard still decides at `plo_synthesis` which ones can be drafted from.
    This is not the rule `cluster_skills` states against setting a skill aside —
    that one is about `is_field_relevant`, where off-field means market demand
    the program did not expect, which is real demand and must stay in the pool.
    `is_graduate_capability` is the other axis and says something different: not
    a thing a graduate does at all. Don't collapse the two axes here.

    The graduate flag is OR-ed across rows sharing a normalised name before the
    split, the same direction `classify_skills` reads `is_field_relevant`: one
    extraction call calling a name institutional does not outvote another that
    did not, and a name must land in exactly one population or dedupe would emit
    it twice.
    """
    groups: list[_Group] = []
    buckets = bucket_by_ksec(skills)

    graduate_names = {
        normalize_need_name(s.skill_name_th) for s in skills if s.is_graduate_capability
    }

    def _split(bucket: list[ExtractedSkill]) -> tuple[list[ExtractedSkill], list[ExtractedSkill]]:
        grad = [s for s in bucket if normalize_need_name(s.skill_name_th) in graduate_names]
        return grad, [
            s for s in bucket if normalize_need_name(s.skill_name_th) not in graduate_names
        ]

    populations = {ksec: _split(bucket) for ksec, bucket in buckets.items()}
    deduped = {
        (ksec, is_grad): dedupe_with_bloom_max(pop)
        for ksec, pair in populations.items()
        for is_grad, pop in ((True, pair[0]), (False, pair[1]))
    }

    # Two allocations, and only the first is a budget. `MAX_CORE_PLOS` is a
    # ceiling on outcomes, and only a graduate capability can become one, so the
    # institutional side must not spend it — that is what let eleven names eat
    # the S bucket's eight slots.
    graduate_sizes = {ksec: len(deduped[(ksec, True)][0]) for ksec in buckets}
    institutional_sizes = {ksec: len(deduped[(ksec, False)][0]) for ksec in buckets}
    graduate_targets = allocate_cluster_targets(graduate_sizes)

    # The institutional side needs a number — without one the prompt falls back
    # to "typically 4-12 groups" — but it must not be a budget, and the first
    # version made it one by handing it `MAX_CORE_PLOS` too. Fourteen
    # institutional names were then asked for nine groups: no PLO slot was
    # spent, but the prompt was told to fragment, which is the very thing this
    # split exists to stop, just moved to the other population.
    #
    # Nothing downstream counts these groups, so the only thing their number has
    # to serve is the designer reading them at the checkpoint — and three themes
    # read better than nine near-singletons. So they are clustered to the same
    # GRANULARITY the graduate side is being asked for: names per group, carried
    # across. With no graduate names to take a ratio from there is nothing to
    # match, and the old behaviour is the honest fallback.
    granularity = (
        sum(graduate_sizes.values()) / sum(graduate_targets.values())
        if sum(graduate_targets.values())
        else 0.0
    )
    institutional_total = (
        max(1, round(sum(institutional_sizes.values()) / granularity)) if granularity else None
    )
    targets = {
        True: graduate_targets,
        False: allocate_cluster_targets(institutional_sizes, total=institutional_total)
        if institutional_total
        else allocate_cluster_targets(institutional_sizes),
    }
    if targets[True]:
        logger.info(
            "Need budget by competency domain: "
            + ", ".join(
                f"{k.value}={n}"
                for k, n in sorted(targets[True].items(), key=lambda kv: kv[0].value)
            )
        )

    for ksec, pair in populations.items():
        for is_grad, bucket in ((True, pair[0]), (False, pair[1])):
            names, index_groups, bloom_by_name = deduped[(ksec, is_grad)]
            if not names:
                continue
            target = targets[is_grad].get(ksec)
            side = "graduate" if is_grad else "institutional"
            logger.info(
                f"Clustering {len(names)} unique {ksec.value} {side} skills into about {target}"
            )
            name_clusters = validate_assignments(
                [("", g) for g in await cluster_skill_names(names, target, program_context)],
                names,
            )
            for _, name_indices in name_clusters:
                member_positions = sorted({p for ni in name_indices for p in index_groups[ni]})
                members = [bucket[p] for p in member_positions]
                evidence_ids = sorted({m.source_evidence_id for m in members})
                cls_coverage = classification_coverage([m.classification for m in members])
                stk_coverage: dict[StakeholderType, int] = {}
                for m in members:
                    key = m.source_stakeholder_type
                    stk_coverage[key] = stk_coverage.get(key, 0) + 1
                # Enum declaration order puts external groups before internal ones,
                # which is the order the report shows them in.
                present = {m.source_stakeholder_type for m in members}
                # Stable, so names mentioned equally often keep clustering's order.
                ranked = sorted(name_indices, key=lambda ni: -len(index_groups[ni]))
                groups.append(
                    _Group(
                        ksec=resolve_need_ksec(members),
                        skill_ids=[m.skill_id for m in members],
                        evidence_ids=evidence_ids,
                        skill_names=[names[ni] for ni in ranked],
                        skill_frequencies=[len(index_groups[ni]) for ni in ranked],
                        # What most of the group asks for, not its top member —
                        # see group_bloom for how the maximum inflated five PLOs.
                        bloom_level=group_bloom(
                            [bloom_by_name[names[ni]] for ni in ranked],
                            [len(index_groups[ni]) for ni in ranked],
                        ),
                        demand_score=compute_demand_score(
                            evidence_ids, stakeholder_type_by_evidence
                        ),
                        # Distinct evidence items, not member rows: "how many
                        # stakeholders asked for this" is a count of documents,
                        # and one document naming a capability three ways is one
                        # stakeholder asking once.
                        is_optional=is_optional_group(cls_coverage, len(evidence_ids)),
                        classification_coverage=cls_coverage,
                        stakeholder_coverage=stk_coverage,
                        # Member rows, not distinct names. classify_skills already
                        # ORs the field flag across every row sharing a name, and
                        # counting that way here would push the number to the total
                        # whenever a name recurs, leaving the designer a ratio that is
                        # always 8/8. The any rule these feed reads the same either
                        # way; only the fraction shown at the checkpoint differs.
                        in_field_skill_count=sum(1 for m in members if m.is_field_relevant),
                        graduate_capability_skill_count=sum(
                            1 for m in members if m.is_graduate_capability
                        ),
                        stakeholder_types=[t for t in StakeholderType if t in present],
                    )
                )
    return groups


async def run(state: AgentState) -> AgentState:
    """Stage 3b: distil extracted skills into at least 6 market-demand Needs."""
    program_id = state.get("program_id", "unknown")
    # Optional designer guidance for this run; absent on a plain re-run.
    note_th = state.get("designer_note")
    # None for a program stored before intake collected a field, which is exactly
    # the pre-context behaviour: say nothing rather than a stub line.
    program_context = build_program_context_th(state.get("metadata") or {})
    skill_dicts = state.get("extracted_skills")
    if skill_dicts is None:
        # Re-clustering the skills already on record, which is what
        # POST /needs/combine/run does and what a graph session entering here
        # after hand-run stages needs too. The expensive per-evidence extraction
        # is deliberately not repeated.
        stored = await SkillRepository().list_by_program(program_id)
        skill_dicts = [sk.model_dump(mode="json") for sk in stored]
        logger.info(f"Stage 3b: loaded {len(skill_dicts)} skills from storage")
    skills = [ExtractedSkill.model_validate(d) for d in skill_dicts]
    logger.info(f"Stage 3b: need_combination from {len(skills)} skills")

    if not skills:
        # Raised rather than returned empty, and before delete_by_program so a
        # previous run's Needs survive — the reasoning behind that guard is
        # unchanged, only what happens next is: returning an empty list let the
        # run walk on to plo_synthesis, which then blamed this stage for a state
        # it had reported honestly. An empty list here is also never answered by
        # loading the stored skills: extraction having produced nothing must not
        # be papered over with the previous run's rows.
        raise ValueError(
            "ยังไม่มีทักษะที่สกัดไว้สำหรับโปรแกรมนี้ กรุณารัน skill_extraction "
            "ให้ได้ทักษะก่อนรวมเป็น Need (Need ที่บันทึกไว้เดิมยังอยู่)"
        )

    # Read off the skills, not off the evidence rows: this stage sees only what
    # extraction produced, and the same corpus skill_extraction scored its
    # importance_score against — see build_scoring_corpus for why both go through
    # one function.
    scoring_corpus = build_scoring_corpus(
        (s.source_evidence_id, s.source_stakeholder_type.value) for s in skills
    )

    groups = await _build_groups(skills, scoring_corpus, program_context)

    needs: list[Need] = []
    # Across the whole run, not stored: how many written (non-fallback) Needs
    # exist, and how many of those report the designer note changed a word
    # choice. Printed once below, only when a note was actually given.
    written_count = 0
    note_used_count = 0
    for group in groups:
        is_fallback = False
        try:
            written = await complete_need_combination(
                _NeedStatement,
                build_summarize_need_prompt(
                    group.skill_names,
                    group.ksec.value,
                    group.bloom_level.value,
                    note_th=note_th,
                    program_context=program_context,
                    skill_frequencies=group.skill_frequencies,
                ),
                max_retries=_STATEMENT_ATTEMPTS,
            )
            _log_coverage(group, written)
        except Exception as exc:
            rejected = _model_answered_but_was_rejected(exc)
            if rejected:
                logger.warning(
                    f"Need statement rejected after {_STATEMENT_ATTEMPTS} attempts for the "
                    f"{group.ksec.value} group — the designer has to write this one: {exc}"
                )
            else:
                # ERROR, not WARNING: nothing is wrong with the data, the stage
                # simply could not reach the model, and the degraded Need it
                # writes instead is an operational fault someone should see.
                logger.error(
                    f"Need statement call failed for the {group.ksec.value} group — "
                    f"re-running the stage should produce it: {exc}"
                )
            # Skill names the extractor already validated, minus any that a
            # manual entry could still have carried a code token into.
            names = [n for n in group.skill_names[:5] if not find_code_identifier(n)]
            if len(names) < len(group.skill_names[:5]):
                logger.warning("Dropped skill name(s) carrying a code token from the fallback")
            # A joined list is exactly what _require_plo_ready rejects, so the
            # fallback cannot pretend to be a usable Need. Marking it is what puts
            # it in front of the designer at the checkpoint instead of letting
            # plo_synthesis invent a PLO from a list of words.
            marker = _REVIEW_MARKER_TH if rejected else _PROVIDER_MARKER_TH
            # model_construct skips the validators, which is what lets the
            # fallback carry a rationale that says there is no rationale. Writing
            # a plausible one here would put an unearned justification under a
            # Need nobody wrote — the exact thing the field must not become.
            written = _NeedStatement.model_construct(
                statement_th=f"{marker} {', '.join(names) or group.ksec.value}",
                rationale_th=(
                    f"{marker} ไม่มีเหตุผลประกอบ เพราะขั้นเขียนประโยคไม่สำเร็จ "
                    "ผู้ออกแบบหลักสูตรต้องเขียนทั้งประโยคและเหตุผลเอง"
                ),
            )
            is_fallback = True

        if not is_fallback:
            written_count += 1
            if written.designer_input_used is not None and written.designer_input_used.used:
                note_used_count += 1

        needs.append(
            Need(
                need_id=str(uuid.uuid4()),
                program_id=program_id,
                statement_th=written.statement_th,
                statement_en=written.statement_en,
                rationale_th=written.rationale_th,
                ksec_categories=[group.ksec],
                bloom_level=group.bloom_level,
                member_skill_ids=group.skill_ids,
                source_evidence_ids=group.evidence_ids,
                stakeholder_coverage=group.stakeholder_coverage,
                source_stakeholder_types=group.stakeholder_types,
                freq=len(group.skill_ids),
                demand_score=group.demand_score,
                is_optional=group.is_optional,
                classification_coverage=group.classification_coverage,
                in_field_skill_count=group.in_field_skill_count,
                graduate_capability_skill_count=group.graduate_capability_skill_count,
            )
        )

    if note_th:
        logger.info(
            f"need_combination: designer note used in {note_used_count}/{written_count} "
            "written Needs"
        )

    core_count = sum(1 for n in needs if not n.is_optional)
    if core_count < MIN_NEEDS:
        logger.warning(
            f"need_combination produced only {core_count} core Needs (policy is at least "
            f"{MIN_NEEDS}) — the designer must add more at the review checkpoint"
        )

    # Replace, don't accumulate — need_id is a fresh uuid per run and the
    # repository upserts by it. Also keeps member_skill_ids honest: the extraction
    # re-run just replaced the skill rows an old Need would point at.
    need_repo = NeedRepository()
    removed = await need_repo.delete_by_program(program_id)
    if removed:
        logger.info(f"Replaced {removed} Need row(s) from a previous run")
    await need_repo.bulk_insert(needs)
    state["needs"] = [n.model_dump(mode="json") for n in needs]
    state["current_stage"] = "need_combination"
    return state
