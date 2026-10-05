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

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from curriculum_agent.models import (
    PLO,
    BloomFinding,
    BloomLevel,
    KsecFinding,
    Need,
    PLOSetReview,
    RedundancyFinding,
)

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
