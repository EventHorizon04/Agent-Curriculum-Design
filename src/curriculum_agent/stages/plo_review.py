"""Stage 06: the QA agent's review of the finished PLO set. Advisory only.

Every other check reads one PLO against its own Needs; this reads the set —
redundancy between drafts, a domain that spans KSEC tags, the Bloom
distribution, the important Needs no PLO cites. It runs after the report, which
is why it can read the set the report persisted, and it changes nothing: its
findings are stored per program and shown beside the report. See
docs/superpowers/specs/2026-10-12-plo-qa-agent-design.md.

The review stored is one of three things: the agent's answer, judged entry by
entry in `accept_review` — the agent runs `plo_review_runs` times and the stored
review is the majority of the usable runs (`plo_review_consensus`), or the one
usable run as-is — or the code facts alone (`code_only_review`) when the
agent is switched off, fails, times out, or says nothing usable. The facts —
KSEC coverage, the Bloom histogram, the unused-Need list — come from
`plo_review_facts` on every path, so a review always has them; only the
judgements need the model. `accept_review` also computes in code everything the
model could only claim — a PLO's current KSEC, whether a suggestion agrees, the
declared level.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from loguru import logger

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    NeedRepository,
    PLOReviewRepository,
    ProgramRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.models import (
    PLO,
    BloomFinding,
    BloomLevel,
    KsecFinding,
    Need,
    PLOSetReview,
    RedundancyFinding,
    ReviewToolCall,
    UnusedNeedFinding,
)
from curriculum_agent.prompts.program_context import build_program_context_th
from curriculum_agent.stages.plo_review_agent import (
    ReviewFinish,
    UnusedVerdict,
    run_review_agent,
)
from curriculum_agent.stages.plo_review_consensus import consensus_review
from curriculum_agent.stages.plo_review_facts import (
    ReviewDossier,
    build_dossier,
    current_ksec,
    is_stale,
    need_demands,
    normalize_ksec,
    plo_fingerprint,
)

MAX_REDUNDANCY_GROUP = 3


def _bloom_level(raw: str | None) -> BloomLevel | None:
    if raw is None:
        return None
    try:
        return BloomLevel(raw.strip().lower())
    except ValueError:
        return None


_VERDICTS = {"consider", "ok_to_leave"}


def accept_review(
    answer: ReviewFinish,
    plos: Sequence[PLO],
    needs_by_id: Mapping[str, Need],
    dossier: ReviewDossier,
    *,
    program_id: str,
    fingerprint: str,
    model: str,
    created_at: datetime,
    tool_calls: Sequence[ReviewToolCall] = (),
) -> tuple[PLOSetReview, Counter[str]]:
    """Keep what breaks no rule, entry by entry; count what was dropped.

    The facts (coverage, histogram, the unused-Need facts) come from the dossier;
    the answer contributes only judgements and text.
    """
    by_id = {p.plo_id: p for p in plos}
    drops: Counter[str] = Counter()

    redundancies: list[RedundancyFinding] = []
    seen_groups: set[frozenset[str]] = set()
    for r in answer.redundancies:
        named = list(dict.fromkeys(i.strip() for i in r.plo_ids if i.strip()))
        known = [i for i in named if i in by_id]
        key = frozenset(known)
        # More than three named is dropped whole, not trimmed: which member to
        # cut is the judgement the model was asked for.
        if (
            len(known) < 2
            or len(named) > MAX_REDUNDANCY_GROUP
            or not r.reason_th.strip()
            or key in seen_groups
        ):
            drops["redundancy"] += 1
            continue
        seen_groups.add(key)
        redundancies.append(
            RedundancyFinding(
                plo_ids=known,
                reason_th=r.reason_th.strip(),
                suggestion_th=r.suggestion_th.strip(),
            )
        )

    ksec: list[KsecFinding] = []
    ksec_seen: set[str] = set()
    for k in answer.ksec:
        pid = k.plo_id.strip()
        suggested = normalize_ksec(k.suggested)
        if pid not in by_id or pid in ksec_seen or not suggested:
            drops["ksec"] += 1
            continue
        ksec_seen.add(pid)
        current = current_ksec(by_id[pid], needs_by_id)
        ksec.append(
            KsecFinding(
                plo_id=pid,
                current=current,
                suggested=suggested,
                agrees=set(current) == set(suggested),
                reason_th=k.reason_th.strip(),
            )
        )

    bloom: list[BloomFinding] = []
    bloom_seen: set[str] = set()
    for b in answer.bloom:
        pid = b.plo_id.strip()
        if pid not in by_id or pid in bloom_seen:
            drops["bloom"] += 1
            continue
        declared = by_id[pid].bloom_level
        level = _bloom_level(b.suggested_level)
        if (level is None or level == declared) and not b.reason_th.strip():
            drops["bloom"] += 1
            continue
        bloom_seen.add(pid)
        bloom.append(
            BloomFinding(
                plo_id=pid, declared=declared, suggested_level=level, reason_th=b.reason_th.strip()
            )
        )

    verdicts: dict[str, UnusedVerdict] = {}
    selected = {u.need_id for u in dossier.unused_needs}
    for v in answer.unused_needs:
        nid = v.need_id.strip()
        if nid not in selected or nid in verdicts:
            drops["unused"] += 1
            continue
        verdicts[nid] = v
    unused: list[UnusedNeedFinding] = []
    for u in dossier.unused_needs:
        verdict = verdicts.get(u.need_id)
        if verdict is None:
            unused.append(u)
            continue
        word = verdict.verdict.strip().lower()
        unused.append(
            u.model_copy(
                update={
                    "verdict": word if word in _VERDICTS else None,
                    "reason_th": verdict.reason_th.strip(),
                }
            )
        )

    review = PLOSetReview(
        program_id=program_id,
        plo_fingerprint=fingerprint,
        model=model,
        created_at=created_at,
        redundancies=redundancies,
        ksec=ksec,
        bloom=bloom,
        bloom_distribution_th=answer.bloom_distribution_th.strip(),
        summary_th=answer.summary_th.strip(),
        ksec_coverage=dossier.ksec_coverage,
        bloom_histogram=dossier.bloom_histogram,
        coverage_th=answer.coverage_th.strip(),
        unused_needs=unused,
        reviewed_by="agent",
        code_only_reason=None,
        tool_calls=list(tool_calls),
        dropped_findings={kind: n for kind, n in drops.items() if n > 0},
    )
    return review, drops


def code_only_review(
    dossier: ReviewDossier,
    *,
    program_id: str,
    fingerprint: str,
    created_at: datetime,
    reason: str,
    tool_calls: Sequence[ReviewToolCall] = (),
) -> PLOSetReview:
    """The facts alone. No finding is manufactured for an agent that did not answer."""
    return PLOSetReview(
        program_id=program_id,
        plo_fingerprint=fingerprint,
        model="",
        created_at=created_at,
        ksec_coverage=dossier.ksec_coverage,
        bloom_histogram=dossier.bloom_histogram,
        unused_needs=list(dossier.unused_needs),
        reviewed_by="code_only",
        code_only_reason=reason,
        tool_calls=list(tool_calls),
    )


def has_agent_findings(review: PLOSetReview) -> bool:
    """Did the agent say anything that survived judging?"""
    return bool(
        review.redundancies
        or review.ksec
        or review.bloom
        or review.summary_th
        or review.coverage_th
        or review.bloom_distribution_th
        or any(u.verdict or u.reason_th for u in review.unused_needs)
    )


# Per process, like plo_synthesis._SYNTHESIS_IN_FLIGHT and for the same reason:
# two forced reviews of one program racing to write its single row. The same
# limit applies — a multi-worker deployment needs a DB-level lock.
_REVIEW_IN_FLIGHT: set[str] = set()


class ReviewAlreadyRunning(RuntimeError):
    """Raised by `fresh_review` when the program already has a review in flight."""


async def _review(program_id: str, plos: Sequence[PLO]) -> PLOSetReview:
    """One review: the agent's judged answer, or the code facts. Raises only on a
    read failure — the caller decides whether that fails a job or is swallowed."""
    metadata = await ProgramRepository().get(program_id)
    needs = await NeedRepository().list_by_program(program_id)
    needs_by_id = {n.need_id: n for n in needs}
    dossier = build_dossier(
        plos,
        needs,
        program_context=build_program_context_th(metadata.model_dump(mode="json"))
        if metadata
        else None,
        degree_level=metadata.degree_level if metadata else "",
    )
    fingerprint = plo_fingerprint(plos, need_demands(needs))
    now = datetime.now(UTC).replace(tzinfo=None)
    if not settings.plo_review_provider:
        logger.info("plo_review: slot switched off — storing the code facts only")
        return code_only_review(
            dossier,
            program_id=program_id,
            fingerprint=fingerprint,
            created_at=now,
            reason="disabled",
        )
    # The only gate on need_detail: the agent may open a Need the report lists as
    # unused and no other.
    unused = {u.need_id: needs_by_id[u.need_id] for u in dossier.unused_needs}
    requested = settings.plo_review_runs
    # Several independent reads of one dossier (spec 2026-10-17): the model
    # answers differently from run to run even at temperature 0, and a finding
    # most runs repeat is one the designer can trust. Each run keeps its own
    # budget and timeout; none sees another's answer.
    outcomes = await asyncio.gather(*(run_review_agent(dossier, unused) for _ in range(requested)))
    judged: list[PLOSetReview] = []
    for i, outcome in enumerate(outcomes, start=1):
        if outcome.finish is None:
            logger.warning(f"plo_review: run {i}/{requested} ended {outcome.reason}")
            continue
        review, drops = accept_review(
            outcome.finish,
            plos,
            needs_by_id,
            dossier,
            program_id=program_id,
            fingerprint=fingerprint,
            model=settings.plo_review_model,
            created_at=now,
            tool_calls=outcome.tool_calls,
        )
        logger.info(
            f"plo_review: run {i}/{requested} kept {len(review.redundancies)} redundancy / "
            f"{len(review.ksec)} ksec / {len(review.bloom)} bloom / "
            f"{sum(1 for u in review.unused_needs if u.verdict)} unused verdict(s), "
            f"dropped {dict(drops) or 'nothing'}, {len(review.tool_calls)} tool call(s)"
        )
        if not has_agent_findings(review):
            logger.warning(f"plo_review: run {i}/{requested} held nothing usable")
            continue
        judged.append(review)

    if not judged:
        reason = "timeout" if all(o.reason == "timeout" for o in outcomes) else "failed"
        logger.warning(f"plo_review: no usable run for {program_id} — code facts only")
        return code_only_review(
            dossier,
            program_id=program_id,
            fingerprint=fingerprint,
            created_at=now,
            reason=reason,
            tool_calls=[c for o in outcomes for c in o.tool_calls],
        ).model_copy(update={"runs_requested": requested, "runs_succeeded": 0})
    if len(judged) == 1:
        return judged[0].model_copy(
            update={"runs_requested": requested, "runs_succeeded": 1, "agreement_threshold": 1}
        )
    review = consensus_review(judged, runs_requested=requested, max_group=MAX_REDUNDANCY_GROUP)
    logger.info(
        f"plo_review: {len(judged)}/{requested} runs, threshold {review.agreement_threshold}, "
        f"{sum(1 for r in review.redundancies if r.agreed_runs >= review.agreement_threshold)} "
        f"redundancy finding(s) agreed"
    )
    return review


async def fresh_review(program_id: str, plos: Sequence[PLO]) -> PLOSetReview:
    """Always runs, always stores. Raises ReviewAlreadyRunning or a database error."""
    if program_id in _REVIEW_IN_FLIGHT:
        raise ReviewAlreadyRunning(
            f"กำลังตรวจชุด PLO ของโปรแกรม '{program_id}' อยู่ — รอให้รอบเดิมเสร็จก่อน"
        )
    _REVIEW_IN_FLIGHT.add(program_id)  # no await between the check and the add
    try:
        review = await _review(program_id, plos)
        await PLOReviewRepository().upsert(review)
        return review
    finally:
        _REVIEW_IN_FLIGHT.discard(program_id)


def _worth_reusing(review: PLOSetReview) -> bool:
    """A current review is reused only if running again could not do better: the
    agent's own answer, or a code-only one the switch produced while it is still
    off. An unconfirmed consensus (one run of several), a failed or timed-out run,
    or a `disabled` one with the slot now on, is run fresh — the set did not change but the reason for the gap did."""
    if review.reviewed_by == "agent":
        # One answer out of several asked for is unconfirmed; a fresh run can confirm it.
        return not (review.runs_requested > 1 and review.runs_succeeded == 1)
    return review.code_only_reason == "disabled" and not settings.plo_review_provider


async def review_plo_set(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None:
    """The graph's review: the stored one if the set is unchanged, else a fresh
    one. Never raises — an advisory step must not fail the session."""
    try:
        stored = await PLOReviewRepository().get(program_id)
        needs = await NeedRepository().list_by_program(program_id)
    except Exception as exc:
        logger.warning(f"plo_review: could not read inputs for {program_id}: {exc!r}")
        return None
    if (
        stored is not None
        and not is_stale(stored, plos, need_demands(needs))
        and _worth_reusing(stored)
    ):
        return stored
    try:
        return await fresh_review(program_id, plos)
    except ReviewAlreadyRunning:
        logger.info(
            f"plo_review: a review of {program_id} is already running — keeping the stored one"
        )
        return stored
    except Exception as exc:
        logger.warning(
            f"plo_review: review of {program_id} failed, keeping the stored one: {exc!r}"
        )
        return stored


async def run(state: AgentState) -> AgentState:
    """Graph entry, stage 06: after the report, review the set it persisted."""
    program_id = state.get("program_id", "unknown")
    plos = [PLO.model_validate(d) for d in state.get("plos", [])]
    review = await review_plo_set(program_id, plos) if plos else None
    state["plo_review"] = review.model_dump(mode="json") if review is not None else None
    state["current_stage"] = "plo_review"
    return state
