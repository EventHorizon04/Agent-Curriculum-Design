"""What a majority of QA agent runs agrees on. Pure code, no LLM call.

The QA agent answers differently from run to run even at temperature 0, so
stage 06 runs it several times on one dossier and keeps what most runs say
(spec 2026-10-17). Each run arrives already judged by `accept_review`; this
module only votes. A finding below the threshold is kept with its count, never
deleted — the page sets it apart instead.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from itertools import combinations

from curriculum_agent.models import (
    AlignmentFinding,
    BloomFinding,
    BloomLevel,
    KsecFinding,
    PLOSetReview,
    RedundancyFinding,
    UnusedNeedFinding,
)

_BLOOM_ORDER = list(BloomLevel)

Pair = frozenset[str]


def agreement_threshold(runs_succeeded: int) -> int:
    """More than half of the runs that produced an answer."""
    return runs_succeeded // 2 + 1


def review_key(review: PLOSetReview) -> tuple[object, ...]:
    """Everything the vote decides, as a hashable value: two runs with equal keys
    cast the same vote on every question, whatever their order or free text."""
    redundancy: set[Pair] = set()
    for f in review.redundancies:
        redundancy |= _pairs(f.plo_ids)
    return (
        frozenset(redundancy),
        frozenset(a.plo_id for a in review.alignment),
        frozenset(
            (b.plo_id, b.suggested_level or b.declared, b.suggested_verb_th) for b in review.bloom
        ),
        frozenset((u.need_id, u.verdict) for u in review.unused_needs if u.verdict),
        frozenset((k.plo_id, frozenset(k.suggested)) for k in review.ksec),
    )


def _plo_order(plo_id: str) -> tuple[int, str]:
    # Length before value, or PLO10 sorts between PLO1 and PLO2.
    return (len(plo_id), plo_id)


def _pairs(plo_ids: Sequence[str]) -> set[Pair]:
    return {frozenset(p) for p in combinations(plo_ids, 2)}


def _sorted_ids(group: frozenset[str]) -> list[str]:
    return sorted(group, key=_plo_order)


def _pair_order(pair: frozenset[str]) -> list[tuple[int, str]]:
    return [_plo_order(i) for i in _sorted_ids(pair)]


def _redundancy_text(group: frozenset[str], runs: Sequence[PLOSetReview]) -> RedundancyFinding:
    """The finding of the run whose group overlaps this one most: most shared PLOs,
    then fewest PLOs outside it, then the earlier run."""
    best: RedundancyFinding | None = None
    best_key = (0, 0)
    for run in runs:
        for f in run.redundancies:
            named = set(f.plo_ids)
            key = (len(group & named), -len(named - group))
            if key[0] > 0 and (best is None or key > best_key):
                best, best_key = f, key
    assert best is not None  # every group was built from some run's pairs
    return best


def _redundancies(
    runs: Sequence[PLOSetReview], threshold: int, max_group: int
) -> list[RedundancyFinding]:
    support: Counter[Pair] = Counter()
    for run in runs:
        named: set[Pair] = set()
        for f in run.redundancies:
            named |= _pairs(f.plo_ids)
        support.update(named)  # a pair counts once per run
    passing = {p for p, n in support.items() if n >= threshold}

    neighbours: dict[str, set[str]] = {}
    for pair in passing:
        a, b = sorted(pair)
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)

    groups: list[frozenset[str]] = []
    placed: set[str] = set()
    for start in sorted(neighbours, key=_plo_order):
        if start in placed:
            continue
        component: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node not in component:
                component.add(node)
                stack.extend(neighbours[node] - component)
        placed |= component
        inner = _pairs(_sorted_ids(frozenset(component)))
        # One finding only when no pair inside it lacks a majority: joining
        # PLO4-PLO9 and PLO6-PLO9 into one group would assert PLO4-PLO6.
        if len(component) <= max_group and inner <= passing:
            groups.append(frozenset(component))
        else:
            groups.extend(sorted((p for p in inner if p in passing), key=_pair_order))

    findings: list[RedundancyFinding] = []
    for group in groups:
        src = _redundancy_text(group, runs)
        agreed = min(support[p] for p in _pairs(_sorted_ids(group)))
        findings.append(
            RedundancyFinding(
                plo_ids=_sorted_ids(group),
                reason_th=src.reason_th,
                suggestion_th=src.suggestion_th,
                agreed_runs=agreed,
            )
        )
    for pair in sorted((p for p in support if p not in passing), key=_pair_order):
        src = _redundancy_text(pair, runs)
        findings.append(
            RedundancyFinding(
                plo_ids=_sorted_ids(pair),
                reason_th=src.reason_th,
                suggestion_th=src.suggestion_th,
                agreed_runs=support[pair],
            )
        )
    return findings


def _ksec(runs: Sequence[PLOSetReview]) -> list[KsecFinding]:
    by_plo: dict[str, list[KsecFinding]] = {}
    for run in runs:
        for k in run.ksec:
            by_plo.setdefault(k.plo_id, []).append(k)
    out: list[KsecFinding] = []
    for entries in by_plo.values():
        counts = Counter(frozenset(e.suggested) for e in entries)  # first-seen order
        top = max(counts.values())
        tied = [s for s, n in counts.items() if n == top]
        current = frozenset(entries[0].current)
        chosen = current if current in tied else tied[0]
        src = next(e for e in entries if frozenset(e.suggested) == chosen)
        out.append(src.model_copy(update={"agreed_runs": top}))
    return out


def _bloom(runs: Sequence[PLOSetReview]) -> list[BloomFinding]:
    by_plo: dict[str, list[BloomFinding]] = {}
    for run in runs:
        for b in run.bloom:
            # A comment that proposes neither a level change nor a verb is not a vote.
            changes_level = b.suggested_level is not None and b.suggested_level != b.declared
            if changes_level or b.suggested_verb_th:
                by_plo.setdefault(b.plo_id, []).append(b)
    out: list[BloomFinding] = []
    for entries in by_plo.values():
        declared_level = entries[0].declared
        # An entry with no level change votes for the declared level.
        levels = [e.suggested_level or declared_level for e in entries]
        counts = Counter(levels)
        top = max(counts.values())
        tied = [lv for lv, n in counts.items() if n == top]
        declared = _BLOOM_ORDER.index(declared_level)

        def distance(level: BloomLevel, declared: int = declared) -> tuple[int, int]:
            i = _BLOOM_ORDER.index(level)
            return (abs(i - declared), i)

        level = min(tied, key=distance)
        verbs = Counter(e.suggested_verb_th for e in entries if e.suggested_verb_th)
        verb = verbs.most_common(1)[0][0] if verbs else None  # a tie keeps the first seen
        src = next(
            (
                e
                for e in entries
                if (e.suggested_level or declared_level) == level and e.suggested_verb_th == verb
            ),
            None,
        ) or next(e for e in entries if (e.suggested_level or declared_level) == level)
        out.append(
            src.model_copy(
                update={
                    "suggested_level": None if level == declared_level else level,
                    "suggested_verb_th": verb,
                    "agreed_runs": len(entries),
                }
            )
        )
    return out


def _alignment_counts(runs: Sequence[PLOSetReview]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for run in runs:
        counts.update({a.plo_id for a in run.alignment})  # once per run
    return counts


def _alignment(
    runs: Sequence[PLOSetReview], counts: Counter[str], rep: PLOSetReview
) -> list[AlignmentFinding]:
    """Per PLO: the count, and the text of the representative run when it names
    the PLO, else the first run that does."""
    out: list[AlignmentFinding] = []
    for plo_id in sorted(counts, key=_plo_order):
        src = next((a for a in rep.alignment if a.plo_id == plo_id), None) or next(
            a for run in runs for a in run.alignment if a.plo_id == plo_id
        )
        out.append(src.model_copy(update={"agreed_runs": counts[plo_id]}))
    return out


def _unused(runs: Sequence[PLOSetReview]) -> list[UnusedNeedFinding]:
    out: list[UnusedNeedFinding] = []
    for base in runs[0].unused_needs:  # the code facts are the dossier's, same in every run
        answers = [
            u for run in runs for u in run.unused_needs if u.need_id == base.need_id and u.verdict
        ]
        counts = Counter(u.verdict for u in answers)
        if not counts:
            out.append(base.model_copy(update={"verdict": None, "reason_th": "", "agreed_runs": 0}))
            continue
        verdict, top = counts.most_common(1)[0]
        if top * 2 <= len(answers):
            out.append(
                base.model_copy(update={"verdict": None, "reason_th": "", "agreed_runs": top})
            )
            continue
        src = next(u for u in answers if u.verdict == verdict)
        out.append(
            base.model_copy(
                update={"verdict": verdict, "reason_th": src.reason_th, "agreed_runs": top}
            )
        )
    return out


def _representative(
    runs: Sequence[PLOSetReview],
    redundancies: Sequence[RedundancyFinding],
    ksec: Sequence[KsecFinding],
    bloom: Sequence[BloomFinding],
    alignment_counts: Counter[str],
    unused: Sequence[UnusedNeedFinding],
    threshold: int,
) -> PLOSetReview:
    main_groups = [_pairs(f.plo_ids) for f in redundancies if f.agreed_runs >= threshold]
    ksec_keys = {(k.plo_id, frozenset(k.suggested)) for k in ksec}
    bloom_keys = {
        (b.plo_id, b.suggested_level, b.suggested_verb_th)
        for b in bloom
        if b.agreed_runs >= threshold
    }
    alignment_keys = {pid for pid, n in alignment_counts.items() if n >= threshold}
    unused_keys = {(u.need_id, u.verdict) for u in unused if u.verdict}

    def score(run: PLOSetReview) -> int:
        named: set[Pair] = set()
        for f in run.redundancies:
            named |= _pairs(f.plo_ids)
        return (
            sum(1 for g in main_groups if g <= named)
            + sum(1 for k in run.ksec if (k.plo_id, frozenset(k.suggested)) in ksec_keys)
            + sum(
                1
                for b in run.bloom
                if (b.plo_id, b.suggested_level, b.suggested_verb_th) in bloom_keys
            )
            + sum(1 for a in run.alignment if a.plo_id in alignment_keys)
            + sum(1 for u in run.unused_needs if (u.need_id, u.verdict) in unused_keys)
        )

    best = runs[0]
    best_score = score(best)
    for run in runs[1:]:
        s = score(run)
        if s > best_score:
            best, best_score = run, s
    return best


def consensus_review(
    runs: Sequence[PLOSetReview], *, runs_requested: int, max_group: int
) -> PLOSetReview:
    """Vote over two or more judged reviews of one dossier."""
    if len(runs) < 2:
        raise ValueError("consensus needs at least two runs")
    threshold = agreement_threshold(len(runs))
    redundancies = _redundancies(runs, threshold, max_group)
    ksec = _ksec(runs)
    bloom = _bloom(runs)
    unused = _unused(runs)
    alignment_counts = _alignment_counts(runs)
    rep = _representative(runs, redundancies, ksec, bloom, alignment_counts, unused, threshold)
    alignment = _alignment(runs, alignment_counts, rep)
    # The representative run supplies the free text, the tool calls and the
    # dropped count, so the dropped-findings warning still describes the
    # summary shown. Fingerprint, model, timestamp and code facts are the same
    # in every run.
    return rep.model_copy(
        update={
            "redundancies": redundancies,
            "ksec": ksec,
            "bloom": bloom,
            "alignment": alignment,
            "unused_needs": unused,
            "runs_requested": runs_requested,
            "runs_succeeded": len(runs),
            "agreement_threshold": threshold,
        }
    )
