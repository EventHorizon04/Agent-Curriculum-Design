"""Review the finished PLO set once, before the report. Advisory only.

Every other check reads one PLO against its own Needs; this reads the set —
redundancy between drafts, a domain that spans KSEC tags, the Bloom
distribution. It changes nothing: its findings are stored per program and shown
on the report page. See docs/superpowers/specs/2026-10-04-plo-set-review-design.md.

The response schema is loose on purpose (plain strings, no Literal): a pydantic
failure fails the whole call and loses every good entry with the bad one, the
lesson of `supporting_indices` and `need_dedup.accept_groups`. `accept_review`
judges entry by entry, and computes in code everything the model could only
claim — a PLO's current KSEC, whether a suggestion agrees, the declared level.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    NeedRepository,
    PLOReviewRepository,
    ProgramRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_plo_review
from curriculum_agent.models import (
    PLO,
    BloomFinding,
    BloomLevel,
    KsecFinding,
    Need,
    PLOSetReview,
    RedundancyFinding,
)
from curriculum_agent.prompts.plo_review import ReviewItem, build_plo_review_prompt
from curriculum_agent.prompts.program_context import build_program_context_th

MAX_REDUNDANCY_GROUP = 3
_KSEC_ORDER = ("K", "S", "E", "C")


class _Redundancy(BaseModel):
    plo_ids: list[str] = Field(default_factory=list)
    reason_th: str = ""
    suggestion_th: str = ""


class _KsecVerdict(BaseModel):
    plo_id: str = ""
    suggested: list[str] = Field(default_factory=list)
    reason_th: str = ""


class _BloomVerdict(BaseModel):
    plo_id: str = ""
    suggested_level: str | None = None
    reason_th: str = ""


class ReviewAnswer(BaseModel):
    redundancies: list[_Redundancy] = Field(default_factory=list)
    ksec: list[_KsecVerdict] = Field(default_factory=list)
    bloom: list[_BloomVerdict] = Field(default_factory=list)
    bloom_distribution_th: str = ""
    summary_th: str = ""


def _normalize_ksec(values: Sequence[str]) -> list[str]:
    """K/S/E/C in canonical order; "EC" and "E|C" read as E and C; anything else dropped."""
    found: set[str] = set()
    for raw in values:
        token = raw.strip().upper().replace("|", "")
        if token == "EC":
            found.update({"E", "C"})
        elif token in _KSEC_ORDER:
            found.add(token)
    return [k for k in _KSEC_ORDER if k in found]


def current_ksec(plo: PLO, needs_by_id: Mapping[str, Need]) -> list[str]:
    """The KSEC tags of the Needs behind a PLO, EC expanded, unknown Needs ignored."""
    return _normalize_ksec(
        [needs_by_id[nid].ksec_category.value for nid in plo.source_need_ids if nid in needs_by_id]
    )


def plo_fingerprint(plos: Sequence[PLO]) -> str:
    """What the review was made from. Any edit a designer could act on moves it."""
    parts = [
        "\x1f".join(
            [
                p.plo_id,
                p.statement_th,
                p.bloom_level.value,
                p.action_verb_th,
                "1" if p.is_optional else "0",
                ",".join(sorted(p.source_need_ids)),
            ]
        )
        for p in sorted(plos, key=lambda p: p.plo_id)
    ]
    return hashlib.sha256("\x1e".join(parts).encode()).hexdigest()


def is_stale(review: PLOSetReview, plos: Sequence[PLO]) -> bool:
    return review.plo_fingerprint != plo_fingerprint(plos)


def is_empty(review: PLOSetReview) -> bool:
    """Nothing kept and nothing said: treated as a review that did not happen."""
    return not (review.redundancies or review.ksec or review.bloom or review.summary_th)


def _bloom_level(raw: str | None) -> BloomLevel | None:
    if raw is None:
        return None
    try:
        return BloomLevel(raw.strip().lower())
    except ValueError:
        return None


def accept_review(
    answer: ReviewAnswer,
    plos: Sequence[PLO],
    needs_by_id: Mapping[str, Need],
    *,
    program_id: str,
    fingerprint: str,
    model: str,
    created_at: datetime,
) -> tuple[PLOSetReview, Counter[str]]:
    """Keep what breaks no rule, entry by entry; count what was dropped."""
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
        suggested = _normalize_ksec(k.suggested)
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
    )
    return review, drops


_ATTEMPTS = 2
_MAX_TOKENS = 8192

# Per process, like plo_synthesis._SYNTHESIS_IN_FLIGHT and for the same reason:
# two forced reviews of one program racing to write its single row. The same
# limit applies — a multi-worker deployment needs a DB-level lock.
_REVIEW_IN_FLIGHT: set[str] = set()


class ReviewAlreadyRunning(RuntimeError):
    """Raised by `fresh_review` when the program already has a review in flight."""


def _items(plos: Sequence[PLO], needs_by_id: Mapping[str, Need]) -> list[ReviewItem]:
    return [
        ReviewItem(
            plo_id=p.plo_id,
            is_optional=p.is_optional,
            statement_th=p.statement_th,
            action_verb_th=p.action_verb_th,
            bloom_level=p.bloom_level.value,
            current_ksec=tuple(current_ksec(p, needs_by_id)),
            need_statements_th=tuple(
                needs_by_id[nid].statement_th for nid in p.source_need_ids if nid in needs_by_id
            ),
        )
        for p in sorted(plos, key=lambda p: (p.is_optional, len(p.plo_id), p.plo_id))
    ]


async def _call(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None:
    """One review call, judged. None on every failure — nothing is manufactured."""
    if not settings.plo_review_provider:
        logger.info("plo_review: disabled — the report goes out without a set review")
        return None
    try:
        metadata = await ProgramRepository().get(program_id)
        needs = await NeedRepository().list_by_program(program_id)
    except Exception as exc:
        logger.warning(f"plo_review: could not load inputs for {program_id}, no call made: {exc!r}")
        return None
    needs_by_id = {n.need_id: n for n in needs}
    messages = build_plo_review_prompt(
        _items(plos, needs_by_id),
        program_context=build_program_context_th(metadata.model_dump(mode="json"))
        if metadata
        else None,
    )
    try:
        async with asyncio.timeout(settings.plo_review_timeout_seconds):
            answer = await complete_plo_review(
                ReviewAnswer,
                messages,
                max_retries=_ATTEMPTS,
                temperature=0,
                max_tokens=_MAX_TOKENS,
            )
    except Exception as exc:  # provider error, timeout, truncation, schema failure
        logger.warning(f"plo_review: call failed for {program_id}, nothing stored: {exc!r}")
        return None
    review, drops = accept_review(
        answer,
        plos,
        needs_by_id,
        program_id=program_id,
        fingerprint=plo_fingerprint(plos),
        model=settings.plo_review_model,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    logger.info(
        f"plo_review: kept {len(review.redundancies)} redundancy / {len(review.ksec)} ksec / "
        f"{len(review.bloom)} bloom, dropped {dict(drops) or 'nothing'}"
    )
    if is_empty(review):
        logger.warning(
            f"plo_review: the answer for {program_id} held nothing usable, nothing stored"
        )
        return None
    return review


async def fresh_review(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None:
    """Always calls. Stores and returns the review, or None if it did not happen."""
    if program_id in _REVIEW_IN_FLIGHT:
        raise ReviewAlreadyRunning(
            f"กำลังตรวจชุด PLO ของโปรแกรม '{program_id}' อยู่ — รอให้รอบเดิมเสร็จก่อน"
        )
    _REVIEW_IN_FLIGHT.add(program_id)  # no await between the check and the add
    try:
        review = await _call(program_id, plos)
        if review is None:
            return None
        try:
            await PLOReviewRepository().upsert(review)
        except Exception as exc:
            logger.warning(f"plo_review: could not store the review for {program_id}: {exc!r}")
            return None
        return review
    finally:
        _REVIEW_IN_FLIGHT.discard(program_id)


async def review_plo_set(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None:
    """The review the report should show: reused if the set is unchanged."""
    try:
        stored = await PLOReviewRepository().get(program_id)
    except Exception as exc:
        logger.warning(f"plo_review: could not read the stored review for {program_id}: {exc!r}")
        stored = None
    if stored is not None and not is_stale(stored, plos):
        return stored
    try:
        fresh = await fresh_review(program_id, plos)
    except ReviewAlreadyRunning:
        logger.info(
            f"plo_review: a review of {program_id} is already running — showing the stored one"
        )
        return stored
    return fresh if fresh is not None else stored


async def run(state: AgentState) -> AgentState:
    """Graph and report-route entry: put the set review on the state for plo_report."""
    program_id = state.get("program_id", "unknown")
    plos = [PLO.model_validate(d) for d in state.get("plos", [])]
    review = await review_plo_set(program_id, plos) if plos else None
    state["plo_review"] = review.model_dump(mode="json") if review is not None else None
    return state
