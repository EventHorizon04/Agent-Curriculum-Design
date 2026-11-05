"""Pure code behind the PLO QA agent: the facts it is handed, and the fingerprint.

Everything here is a number or a selection the reviewer could only claim, so it
is computed once in code and stored as such (spec 2026-10-12, sections 2-3).
The dossier is deliberately small: the set, the Need sentences behind it, and
these facts. Evidence text, member skill names and earlier verdicts are left out
on purpose — the more upstream detail a reviewer reads, the more it anchors on it
instead of judging the set as written.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from curriculum_agent.models import (
    PLO,
    BloomHistogram,
    BloomLevel,
    KsecCoverage,
    Need,
    PLOSetReview,
    StakeholderType,
    UnusedNeedFinding,
)
from curriculum_agent.prompts.plo_review import (
    UNWRITTEN_CITED_PLACEHOLDER_TH,
    CitedNeed,
    ReviewItem,
)
from curriculum_agent.stages.need_grouping import is_in_scope, is_unwritten_need

KSEC_ORDER: tuple[str, ...] = ("K", "S", "E", "C")
UNUSED_TOP = 5
_BELOW_APPLY = {BloomLevel.REMEMBER, BloomLevel.UNDERSTAND}


def normalize_ksec(values: Sequence[str]) -> list[str]:
    """K/S/E/C in canonical order; "EC" and "E|C" read as E and C; anything else dropped."""
    found: set[str] = set()
    for raw in values:
        token = raw.strip().upper().replace("|", "")
        if token == "EC":
            found.update({"E", "C"})
        elif token in KSEC_ORDER:
            found.add(token)
    return [k for k in KSEC_ORDER if k in found]


def current_ksec(plo: PLO, needs_by_id: Mapping[str, Need]) -> list[str]:
    """The KSEC tags of the Needs behind a PLO, EC expanded, unknown Needs ignored."""
    return normalize_ksec(
        [
            tag.value
            for nid in plo.source_need_ids
            if nid in needs_by_id
            for tag in needs_by_id[nid].ksec_categories
        ]
    )


def ksec_coverage(plos: Sequence[PLO], needs_by_id: Mapping[str, Need]) -> KsecCoverage:
    """PLOs per domain, optional ones included (the designer's call, 2026-10-12).
    A PLO counts once in every domain its Needs give it."""
    counts = dict.fromkeys(KSEC_ORDER, 0)
    for plo in plos:
        for tag in current_ksec(plo, needs_by_id):
            counts[tag] += 1
    flags: list[str] = []
    if plos:
        if counts["K"] > 0 and counts["S"] == counts["E"] == counts["C"] == 0:
            flags.append("all_k")
        if counts["E"] == 0 and counts["C"] == 0:
            flags.append("no_e_or_c")
    return KsecCoverage(
        counts=counts, missing=[k for k in KSEC_ORDER if counts[k] == 0], flags=flags
    )


def bloom_histogram(plos: Sequence[PLO], degree_level: str) -> BloomHistogram:
    """PLOs per level (optional included), in level order. The only flag is one the
    skill sources: PLOs sit mostly at Apply and above, so more than half below Apply
    is flagged. There is no numeric ceiling on Create — nothing sources one."""
    counts = {level.value: 0 for level in BloomLevel}
    for plo in plos:
        counts[plo.bloom_level.value] += 1
    below = sum(1 for p in plos if p.bloom_level in _BELOW_APPLY)
    flags = ["below_apply_majority"] if plos and below * 2 > len(plos) else []
    return BloomHistogram(counts=counts, degree_level=degree_level, flags=flags)


def need_voices(need: Need, stakeholder_by_evidence: Mapping[str, str]) -> dict[str, int]:
    """Distinct evidence items behind a Need, per stakeholder type (decision 21).

    Counts documents, not skills: one employer document yielding three skills is
    one employer voice. An evidence id the map does not know is ignored.
    """
    counts: dict[str, int] = {}
    for eid in dict.fromkeys(need.source_evidence_ids):
        kind = stakeholder_by_evidence.get(eid)
        if kind is not None:
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def exclusion_reason(need: Need) -> str:
    """Why an uncited Need is unused, in the order plo_synthesis filters them."""
    if not is_in_scope(need):
        return "out_of_scope"
    if is_unwritten_need(need):
        return "unwritten"
    return "lost_on_demand"


def select_unused_needs(
    plos: Sequence[PLO], needs: Sequence[Need], *, top: int = UNUSED_TOP
) -> list[UnusedNeedFinding]:
    """The uncited Needs worth a reviewer's look: the `top` by demand, plus every
    one a professional council asked for, however low its demand."""
    from curriculum_agent.stages.plo_synthesis import cited_need_ids  # noqa: PLC0415

    cited = cited_need_ids(plos)
    ordered = sorted(
        (n for n in needs if n.need_id not in cited),
        key=lambda n: (-n.demand_score, n.need_id),
    )
    top_ids = {n.need_id for n in ordered[:top]}
    picked = [
        n
        for n in ordered
        if n.need_id in top_ids
        or StakeholderType.PROFESSIONAL_COUNCIL in n.source_stakeholder_types
    ]
    return [
        UnusedNeedFinding(
            need_id=n.need_id,
            statement_th=n.statement_th,
            demand_score=n.demand_score,
            ksec_categories=[t.value for t in n.ksec_categories],
            stakeholder_types=[t.value for t in n.source_stakeholder_types],
            exclusion=exclusion_reason(n),
            unwritten=is_unwritten_need(n),
        )
        for n in picked
    ]


@dataclass(frozen=True)
class ReviewDossier:
    """Everything the QA agent is handed at the start, and nothing else."""

    program_context: str | None
    degree_level: str
    items: tuple[ReviewItem, ...]
    ksec_coverage: KsecCoverage
    bloom_histogram: BloomHistogram
    core_count: int
    unused_needs: tuple[UnusedNeedFinding, ...]


def build_dossier(
    plos: Sequence[PLO],
    needs: Sequence[Need],
    *,
    program_context: str | None,
    degree_level: str,
    stakeholder_by_evidence: Mapping[str, str] = {},  # noqa: B006 - read-only
) -> ReviewDossier:
    needs_by_id = {n.need_id: n for n in needs}
    items = tuple(
        ReviewItem(
            plo_id=p.plo_id,
            is_optional=p.is_optional,
            statement_th=p.statement_th,
            action_verb_th=p.action_verb_th,
            bloom_level=p.bloom_level.value,
            current_ksec=tuple(current_ksec(p, needs_by_id)),
            cited_needs=tuple(
                CitedNeed(
                    statement_th=UNWRITTEN_CITED_PLACEHOLDER_TH
                    if is_unwritten_need(needs_by_id[nid])
                    else needs_by_id[nid].statement_th,
                    voices=tuple(
                        sorted(
                            need_voices(needs_by_id[nid], stakeholder_by_evidence).items(),
                            key=lambda kv: (-kv[1], kv[0]),
                        )
                    ),
                )
                for nid in p.source_need_ids
                if nid in needs_by_id
            ),
        )
        for p in sorted(plos, key=lambda p: (p.is_optional, len(p.plo_id), p.plo_id))
    )
    return ReviewDossier(
        program_context=program_context,
        degree_level=degree_level,
        items=items,
        ksec_coverage=ksec_coverage(plos, needs_by_id),
        bloom_histogram=bloom_histogram(plos, degree_level),
        core_count=sum(1 for p in plos if not p.is_optional),
        unused_needs=tuple(select_unused_needs(plos, needs)),
    )


def need_demands(needs: Sequence[Need]) -> dict[str, float]:
    return {n.need_id: n.demand_score for n in needs}


def plo_fingerprint(plos: Sequence[PLO], demands: Mapping[str, float]) -> str:
    """What the review was made from: the PLO set and the program's Needs.

    The Needs are in it because the unused-Need answer depends on them: re-running
    need_combination without touching the PLOs must read as a changed set.
    """
    plo_parts = [
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
    need_parts = [f"{nid}:{demands[nid]:.6f}" for nid in sorted(demands)]
    body = "\x1e".join(plo_parts) + "\x1d" + "\x1e".join(need_parts)
    return hashlib.sha256(body.encode()).hexdigest()


def is_stale(review: PLOSetReview, plos: Sequence[PLO], demands: Mapping[str, float]) -> bool:
    return review.plo_fingerprint != plo_fingerprint(plos, demands)
