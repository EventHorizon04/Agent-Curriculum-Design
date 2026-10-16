# PLO QA Review Consensus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the stage-06 QA agent three times in parallel and store only what a majority agrees on, so the page's findings are ones the agent repeats.

**Architecture:** A new pure module `stages/plo_review_consensus.py` votes over two or more already-judged `PLOSetReview`s (each the output of today's `accept_review`). `stages/plo_review._review` gathers `settings.plo_review_runs` agent runs, judges each, and stores the consensus (≥2 runs), the single run (1), or the code facts (0). New fields ride in the existing JSONB column; the stage 06 page shows agreement chips and sets below-threshold findings apart.

**Tech Stack:** Python 3.11, pydantic v2, asyncio, pytest (asyncio_mode=auto); React 19 + TypeScript + Tailwind (project classes only).

**Spec:** `docs/superpowers/specs/2026-10-17-plo-review-consensus-design.md`

## Global Constraints

- Prompt, tools, dossier and `accept_review`'s rules are unchanged; every run sees exactly what one run sees today (information-bias rule).
- `plo_review_runs: int = Field(default=3, ge=1)`; `1` must store exactly what today's code stores (plus `runs_requested=1, runs_succeeded=1, agreement_threshold=1`, which are the defaults).
- Threshold = `runs_succeeded // 2 + 1`, stored as `agreement_threshold`.
- New fields default so a stored row without them reads as a one-run review: `agreed_runs: int = 1` on `RedundancyFinding`, `KsecFinding`, `BloomFinding`, `UnusedNeedFinding`; `runs_requested: int = 1`, `runs_succeeded: int = 1`, `agreement_threshold: int = 1` on `PLOSetReview`. No migration (JSONB).
- `MAX_REDUNDANCY_GROUP` (3) still bounds every stored redundancy finding.
- Thai for designer-facing strings, English for code/comments/logs. `loguru` only. Type hints on every signature, `from __future__ import annotations`.
- Frontend: only classes defined in `frontend/src/index.css` (`chip chip-*`, `notice notice-*`, `text-pencil`, `border-hair`, …); never the Tailwind palette.
- Never read `.env`. Stage by explicit path only; never stage `.scratch/**`, `curriculum-design-agent.skill`, or untracked `.claude/skills/*`.
- Commits in English, ending with the harness attribution line.

## Review Focus

1. An old stored review (no new fields) must render exactly as today: no agreement chips, no "พบไม่ถึงเกณฑ์" section, no single-run notice — pinned in Task 1 (read test) and Task 3 (render rules keyed on `runs_succeeded ≥ 2` / `runs_requested > 1`).
2. A PLO present in the KSEC list of only some runs (`accept_review` dropped it in another) must be voted over the runs that have it, not crash — test in Task 1.
3. Identical answers from all runs must give the single answer back with `agreed_runs = N` and run 1 as representative — test in Task 1.
4. Mixed failures (one timeout, one failed, nothing succeeded) store `code_only_reason="failed"`; only all-timeout stores `"timeout"` — test in Task 2.
5. One run naming overlapping groups (PLO1/PLO2 and PLO1/PLO2/PLO3) counts pair PLO1-PLO2 once for that run — test in Task 1.

Ruling recorded here: a Bloom entry whose `suggested_level` is `None` or equals `declared` (a comment with no proposed change) is **not** carried into a consensus review — the spec counts runs that "proposed a level different from declared", and a comment-only entry proposes none. A single-run review keeps such entries as today.

---

### Task 1: Fields, setting, and the consensus module

**Files:**
- Modify: `src/curriculum_agent/models.py` (the PLO set review block, ~line 538-645)
- Modify: `src/curriculum_agent/config.py` (beside `plo_review_timeout_seconds`, ~line 326)
- Create: `src/curriculum_agent/stages/plo_review_consensus.py`
- Test: `tests/unit/test_plo_review_consensus.py` (create)

**Interfaces:**
- Consumes: `PLOSetReview` and finding models from `models.py`; `BloomLevel` (enum order remember→create).
- Produces:
  - `agreement_threshold(runs_succeeded: int) -> int`
  - `consensus_review(runs: Sequence[PLOSetReview], *, runs_requested: int, max_group: int) -> PLOSetReview` — raises `ValueError` for fewer than 2 runs.
  - `settings.plo_review_runs: int` (default 3).
  - Model fields listed in Global Constraints.

- [ ] **Step 1: Add the model fields and the setting**

In `models.py`, add to `RedundancyFinding`, `KsecFinding`, `BloomFinding` and `UnusedNeedFinding` (last field of each):

```python
    # How many of the review's runs said this (stages/plo_review_consensus.py).
    # 1 for a one-run review and for rows written before the field existed.
    agreed_runs: int = 1
```

Add to `PLOSetReview`, after `dropped_findings`:

```python
    # Self-consistency (spec 2026-10-17): how many agent runs were asked for,
    # how many produced a usable answer, and how many had to agree for a finding
    # to count. All 1 for a one-run review and for rows written before the fields.
    runs_requested: int = 1
    runs_succeeded: int = 1
    agreement_threshold: int = 1
```

In `config.py`, after `plo_review_timeout_seconds: int = 300`:

```python
    # How many times the QA agent reads the same dossier, in parallel; the stored
    # review keeps what a majority agrees on. 1 restores the single-run review.
    plo_review_runs: int = Field(default=3, ge=1)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_plo_review_consensus.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pytest

from curriculum_agent.models import (
    BloomFinding,
    BloomLevel,
    KsecFinding,
    PLOSetReview,
    RedundancyFinding,
    ReviewToolCall,
    UnusedNeedFinding,
)
from curriculum_agent.stages.plo_review_consensus import agreement_threshold, consensus_review

_WHEN = datetime(2026, 10, 17, 9, 0)


def _unused(verdict: str | None = None, reason: str = "") -> UnusedNeedFinding:
    return UnusedNeedFinding(
        need_id="n9",
        statement_th="ต้องการบัณฑิตที่ออกแบบโปรแกรมท่องเที่ยวได้",
        demand_score=0.4,
        ksec_category="S",
        exclusion="lost_on_demand",
        verdict=verdict,
        reason_th=reason,
    )


def _run(
    *,
    groups: Sequence[list[str]] = (),
    ksec: dict[str, list[str]] | None = None,
    bloom: dict[str, BloomLevel | None] | None = None,
    verdict: str | None = None,
    summary: str = "สรุป",
    tool: str = "check_verbs",
) -> PLOSetReview:
    ksec = ksec if ksec is not None else {"PLO1": ["S"], "PLO2": ["S"]}
    return PLOSetReview(
        program_id="p",
        plo_fingerprint="fp",
        model="m",
        created_at=_WHEN,
        redundancies=[
            RedundancyFinding(plo_ids=g, reason_th=f"ซ้ำ {'-'.join(g)}", suggestion_th="รวม")
            for g in groups
        ],
        ksec=[
            KsecFinding(
                plo_id=pid, current=["S"], suggested=s, agrees=set(s) == {"S"}, reason_th=pid
            )
            for pid, s in ksec.items()
        ],
        bloom=[
            BloomFinding(
                plo_id=pid, declared=BloomLevel.APPLY, suggested_level=lv, reason_th=f"{pid} {lv}"
            )
            for pid, lv in (bloom or {}).items()
        ],
        unused_needs=[_unused(verdict, f"เหตุผล {verdict}" if verdict else "")],
        summary_th=summary,
        tool_calls=[ReviewToolCall(tool=tool, arg="PLO1")],
    )


def _consensus(*runs: PLOSetReview) -> PLOSetReview:
    return consensus_review(list(runs), runs_requested=3, max_group=3)


def test_threshold_is_more_than_half() -> None:
    assert [agreement_threshold(n) for n in (1, 2, 3, 4, 5)] == [1, 2, 2, 3, 3]


def test_fewer_than_two_runs_is_refused() -> None:
    with pytest.raises(ValueError):
        consensus_review([_run()], runs_requested=3, max_group=3)


def test_identical_runs_give_the_answer_back_with_full_agreement() -> None:
    a = _run(groups=[["PLO1", "PLO2"]], bloom={"PLO1": BloomLevel.ANALYZE}, verdict="consider")
    review = _consensus(a, a.model_copy(), a.model_copy())
    assert [(r.plo_ids, r.agreed_runs) for r in review.redundancies] == [(["PLO1", "PLO2"], 3)]
    assert [k.agreed_runs for k in review.ksec] == [3, 3]
    assert review.bloom[0].suggested_level == BloomLevel.ANALYZE and review.bloom[0].agreed_runs == 3
    assert review.unused_needs[0].verdict == "consider" and review.unused_needs[0].agreed_runs == 3
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 3, 2)


def test_a_pair_two_runs_name_passes_and_a_pair_one_names_is_kept_below() -> None:
    review = _consensus(
        _run(groups=[["PLO4", "PLO9"]]),
        _run(groups=[["PLO4", "PLO9"], ["PLO6", "PLO8"]]),
        _run(groups=[["PLO1", "PLO4"]]),
    )
    found = {tuple(r.plo_ids): r.agreed_runs for r in review.redundancies}
    assert found == {("PLO4", "PLO9"): 2, ("PLO6", "PLO8"): 1, ("PLO1", "PLO4"): 1}


def test_a_pair_counts_once_per_run_even_in_overlapping_groups() -> None:
    review = _consensus(
        _run(groups=[["PLO1", "PLO2"], ["PLO1", "PLO2", "PLO3"]]),
        _run(),
        _run(),
    )
    assert {tuple(r.plo_ids): r.agreed_runs for r in review.redundancies}[("PLO1", "PLO2")] == 1


def test_a_three_plo_group_needs_every_pair_to_pass() -> None:
    full = _consensus(
        _run(groups=[["PLO4", "PLO6", "PLO9"]]),
        _run(groups=[["PLO4", "PLO6", "PLO9"]]),
        _run(),
    )
    assert [(r.plo_ids, r.agreed_runs) for r in full.redundancies] == [(["PLO4", "PLO6", "PLO9"], 2)]

    chain = _consensus(
        _run(groups=[["PLO4", "PLO9"], ["PLO6", "PLO9"]]),
        _run(groups=[["PLO4", "PLO9"], ["PLO6", "PLO9"]]),
        _run(),
    )
    main = sorted(tuple(r.plo_ids) for r in chain.redundancies if r.agreed_runs >= 2)
    assert main == [("PLO4", "PLO9"), ("PLO6", "PLO9")]


def test_a_component_larger_than_the_cap_is_split_into_its_passing_pairs() -> None:
    groups = [["PLO1", "PLO2"], ["PLO2", "PLO3"], ["PLO3", "PLO4"]]
    review = _consensus(_run(groups=groups), _run(groups=groups), _run())
    assert all(len(r.plo_ids) == 2 for r in review.redundancies)
    assert len(review.redundancies) == 3


def test_redundancy_text_comes_from_the_run_overlapping_most() -> None:
    review = _consensus(
        _run(groups=[["PLO1", "PLO2", "PLO3"]]),
        _run(groups=[["PLO1", "PLO2"]]),
        _run(),
    )
    pair = next(r for r in review.redundancies if r.plo_ids == ["PLO1", "PLO2"])
    assert pair.reason_th == "ซ้ำ PLO1-PLO2"


def test_ksec_takes_the_most_given_set_and_a_tie_prefers_current() -> None:
    review = _consensus(
        _run(ksec={"PLO1": ["K", "S"]}),
        _run(ksec={"PLO1": ["S"]}),
    )
    assert review.ksec[0].suggested == ["S"] and review.ksec[0].agreed_runs == 1
    assert review.agreement_threshold == 2


def test_ksec_votes_only_over_the_runs_that_have_the_plo() -> None:
    review = _consensus(
        _run(ksec={"PLO1": ["S"], "PLO2": ["K"]}),
        _run(ksec={"PLO1": ["S"]}),
        _run(ksec={"PLO1": ["S"], "PLO2": ["K"]}),
    )
    plo2 = next(k for k in review.ksec if k.plo_id == "PLO2")
    assert plo2.suggested == ["K"] and plo2.agreed_runs == 2


def test_bloom_counts_runs_proposing_a_change_and_a_tie_takes_the_nearer_level() -> None:
    review = _consensus(
        _run(bloom={"PLO1": BloomLevel.CREATE}),
        _run(bloom={"PLO1": BloomLevel.ANALYZE}),
        _run(),
    )
    assert review.bloom[0].suggested_level == BloomLevel.ANALYZE
    assert review.bloom[0].agreed_runs == 2


def test_a_bloom_comment_without_a_change_is_not_carried() -> None:
    review = _consensus(
        _run(bloom={"PLO1": None}), _run(bloom={"PLO1": BloomLevel.APPLY}), _run()
    )
    assert review.bloom == []


def test_unused_without_a_majority_has_no_verdict() -> None:
    review = _consensus(_run(verdict="consider"), _run(verdict="ok_to_leave"), _run())
    assert review.unused_needs[0].verdict is None and review.unused_needs[0].agreed_runs == 1
    assert review.unused_needs[0].demand_score == 0.4  # code facts kept


def test_text_and_per_run_fields_come_from_the_most_representative_run() -> None:
    review = _consensus(
        _run(groups=[["PLO6", "PLO8"]], summary="หนึ่ง", tool="bloom_lookup"),
        _run(groups=[["PLO4", "PLO9"]], summary="สอง", tool="need_detail"),
        _run(groups=[["PLO4", "PLO9"]], summary="สาม", tool="check_verbs"),
    )
    assert review.summary_th == "สอง" and review.tool_calls[0].tool == "need_detail"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_plo_review_consensus.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'curriculum_agent.stages.plo_review_consensus'`.

- [ ] **Step 4: Write the module**

Create `src/curriculum_agent/stages/plo_review_consensus.py`:

```python
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


def _plo_order(plo_id: str) -> tuple[int, str]:
    # Length before value, or PLO10 sorts between PLO1 and PLO2.
    return (len(plo_id), plo_id)


def _pairs(plo_ids: Sequence[str]) -> set[Pair]:
    return {frozenset(p) for p in combinations(plo_ids, 2)}


def _sorted_ids(group: frozenset[str]) -> list[str]:
    return sorted(group, key=_plo_order)


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
            groups.extend(sorted((p for p in inner if p in passing), key=lambda p: _sorted_ids(p)))

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
    for pair in sorted(
        (p for p in support if p not in passing), key=lambda p: _sorted_ids(p)
    ):
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
            # A comment with no proposed change is not a vote for a change.
            if b.suggested_level is not None and b.suggested_level != b.declared:
                by_plo.setdefault(b.plo_id, []).append(b)
    out: list[BloomFinding] = []
    for entries in by_plo.values():
        counts = Counter(e.suggested_level for e in entries)
        top = max(counts.values())
        tied = [lv for lv, n in counts.items() if n == top]
        declared = _BLOOM_ORDER.index(entries[0].declared)

        def distance(level: BloomLevel | None) -> tuple[int, int]:
            i = _BLOOM_ORDER.index(level)  # type: ignore[arg-type]
            return (abs(i - declared), i)

        level = min(tied, key=distance)
        src = next(e for e in entries if e.suggested_level == level)
        out.append(src.model_copy(update={"agreed_runs": len(entries)}))
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
    unused: Sequence[UnusedNeedFinding],
    threshold: int,
) -> PLOSetReview:
    main_groups = [_pairs(f.plo_ids) for f in redundancies if f.agreed_runs >= threshold]
    ksec_keys = {(k.plo_id, frozenset(k.suggested)) for k in ksec}
    bloom_keys = {(b.plo_id, b.suggested_level) for b in bloom if b.agreed_runs >= threshold}
    unused_keys = {(u.need_id, u.verdict) for u in unused if u.verdict}

    def score(run: PLOSetReview) -> int:
        named: set[Pair] = set()
        for f in run.redundancies:
            named |= _pairs(f.plo_ids)
        return (
            sum(1 for g in main_groups if g <= named)
            + sum(1 for k in run.ksec if (k.plo_id, frozenset(k.suggested)) in ksec_keys)
            + sum(1 for b in run.bloom if (b.plo_id, b.suggested_level) in bloom_keys)
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
    rep = _representative(runs, redundancies, ksec, bloom, unused, threshold)
    # The representative run supplies the free text, the tool calls and the
    # dropped count, so the dropped-findings warning still describes the
    # summary shown. Fingerprint, model, timestamp and code facts are the same
    # in every run.
    return rep.model_copy(
        update={
            "redundancies": redundancies,
            "ksec": ksec,
            "bloom": bloom,
            "unused_needs": unused,
            "runs_requested": runs_requested,
            "runs_succeeded": len(runs),
            "agreement_threshold": threshold,
        }
    )
```

Note on `test_ksec_takes_the_most_given_set_and_a_tie_prefers_current`: with 2 runs the threshold is 2, `{K,S}` and `{S}` tie at 1, and `{S}` equals `current`, so it wins with `agreed_runs=1`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_plo_review_consensus.py -q`
Expected: all pass. If a test disagrees with the module, re-read the spec section it pins before changing either; the spec decides.

- [ ] **Step 6: Add the old-row read test**

Append to `tests/unit/test_plo_review_consensus.py`:

```python
def test_a_stored_review_without_the_new_fields_reads_as_one_run() -> None:
    raw = _run(groups=[["PLO1", "PLO2"]]).model_dump(mode="json")
    for key in ("runs_requested", "runs_succeeded", "agreement_threshold"):
        raw.pop(key)
    for r in raw["redundancies"]:
        r.pop("agreed_runs")
    review = PLOSetReview.model_validate(raw)
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (1, 1, 1)
    assert review.redundancies[0].agreed_runs == 1
```

Run: `uv run pytest tests/unit/test_plo_review_consensus.py -q` — expected PASS.

- [ ] **Step 7: Full checks and commit**

Run: `uv run pytest -q` (all green, no warnings), `uv run ruff check src/ tests/`, `uv run ruff format src/ tests/`, `uv run mypy src/`.

```bash
git add src/curriculum_agent/models.py src/curriculum_agent/config.py src/curriculum_agent/stages/plo_review_consensus.py tests/unit/test_plo_review_consensus.py
git commit -m "feat(review): vote over several judged QA reviews"
```

---

### Task 2: Run the agent several times and store the consensus

**Files:**
- Modify: `src/curriculum_agent/stages/plo_review.py` (`_review`, ~line 253-319; module docstring)
- Test: `tests/unit/test_plo_review_run.py` (add tests; existing ones must stay green)
- Modify: `CLAUDE.md` (the `PLO_REVIEW_PROVIDER` paragraph; the "QA review advises" pitfall)
- Modify: `.claude/skills/curriculum-design-agent/references/data-schemas.md` (the `PLOSetReview` block and its finding models)

**Interfaces:**
- Consumes: `consensus_review(runs, *, runs_requested, max_group)`, `settings.plo_review_runs` (Task 1); `run_review_agent(dossier, unused) -> AgentOutcome` (never raises; `AgentOutcome.finish`, `.reason` in `{"failed","timeout"}`, `.tool_calls`); `accept_review`; `has_agent_findings`; `code_only_review`; `MAX_REDUNDANCY_GROUP`.
- Produces: the stored `PLOSetReview` carries `runs_requested`, `runs_succeeded`, `agreement_threshold` on every agent path.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_plo_review_run.py` (it already defines `live`, `_PLOS`, `_FINISH`, `_MemoryRepo`, and imports `AgentOutcome`, `Redundancy`, `ReviewFinish`). Add `import asyncio` to the import block at the top of the file (ruff E402 rejects a mid-file import), then append:

```python
def _finish(*groups: list[str]) -> ReviewFinish:
    return ReviewFinish(
        kind="finish",
        redundancies=[Redundancy(plo_ids=g, reason_th="ซ้ำ", suggestion_th="รวม") for g in groups],
        summary_th="สรุป",
    )


async def test_three_runs_are_asked_for_and_voted_over(live: AsyncMock) -> None:
    review = await pr.fresh_review("p", _PLOS)
    assert live.await_count == 3
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 3, 2)
    assert review.redundancies[0].agreed_runs == 3


async def test_the_runs_are_concurrent(live: AsyncMock) -> None:
    started = 0
    all_started = asyncio.Event()

    async def blocking(dossier, unused):  # type: ignore[no-untyped-def]
        nonlocal started
        started += 1
        if started == 3:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1)
        return AgentOutcome(_FINISH, None, [])

    live.side_effect = blocking
    review = await pr.fresh_review("p", _PLOS)
    assert review.runs_succeeded == 3


async def test_two_successes_and_one_failure_vote_over_two(live: AsyncMock) -> None:
    live.side_effect = [
        AgentOutcome(_FINISH, None, []),
        AgentOutcome(None, "timeout", []),
        AgentOutcome(_FINISH, None, []),
    ]
    review = await pr.fresh_review("p", _PLOS)
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 2, 2)
    assert review.redundancies[0].agreed_runs == 2


async def test_one_success_is_stored_as_is_and_marked(live: AsyncMock) -> None:
    live.side_effect = [
        AgentOutcome(None, "failed", []),
        AgentOutcome(_finish(["PLO1", "PLO2"]), None, []),
        AgentOutcome(None, "timeout", []),
    ]
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "agent"
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 1, 1)
    assert review.redundancies[0].agreed_runs == 1


async def test_all_timeouts_store_timeout(live: AsyncMock) -> None:
    live.return_value = AgentOutcome(None, "timeout", [])
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "code_only" and review.code_only_reason == "timeout"


async def test_mixed_failures_store_failed(live: AsyncMock) -> None:
    live.side_effect = [
        AgentOutcome(None, "timeout", []),
        AgentOutcome(None, "failed", []),
        AgentOutcome(ReviewFinish(kind="finish"), None, []),  # judged empty: a failure
    ]
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "code_only" and review.code_only_reason == "failed"


async def test_one_run_setting_is_todays_single_review(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_runs", 1)
    review = await pr.fresh_review("p", _PLOS)
    assert live.await_count == 1
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (1, 1, 1)
    assert review.tool_calls[0].tool == "check_verbs"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_plo_review_run.py -q`
Expected: the new tests FAIL (`await_count == 1`, `runs_requested == 1`); the old ones pass.

- [ ] **Step 3: Rewrite the agent half of `_review`**

In `stages/plo_review.py` add `import asyncio` and
`from curriculum_agent.stages.plo_review_consensus import consensus_review`.
Replace everything in `_review` from `unused = {...}` to the end of the function with:

```python
    # The only gate on need_detail: the agent may open a Need the report lists as
    # unused and no other.
    unused = {u.need_id: needs_by_id[u.need_id] for u in dossier.unused_needs}
    requested = settings.plo_review_runs
    # Several independent reads of one dossier (spec 2026-10-17): the model
    # answers differently from run to run even at temperature 0, and a finding
    # most runs repeat is one the designer can trust. Each run keeps its own
    # budget and timeout; none sees another's answer.
    outcomes = await asyncio.gather(
        *(run_review_agent(dossier, unused) for _ in range(requested))
    )
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
        )
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
```

Update the module docstring's second paragraph to say the agent runs `plo_review_runs` times and the stored review is the majority (`plo_review_consensus`), one run as-is, or the code facts.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_plo_review_run.py tests/unit/test_plo_review_consensus.py -q`
Expected: PASS. If an existing test in another file assumes one agent call per review (grep `run_review_agent` in `tests/`), fix that test by setting `monkeypatch.setattr(settings, "plo_review_runs", 1)` in it — not by changing `_review`.

- [ ] **Step 5: Docs**

`CLAUDE.md`, in the `PLO_REVIEW_PROVIDER` paragraph, after "the whole run bounded by `plo_review_timeout_seconds` (300)." insert:

> It runs **`plo_review_runs` times (default 3) in parallel on the same dossier** and stores what a majority agrees on (`stages/plo_review_consensus.py`, pure code): the model answers differently from run to run even at temperature 0 — two runs on one program grouped the same PLOs into different redundancy findings — so a finding one run produced alone is kept with its `agreed_runs` but shown apart. One usable run is stored as-is and labelled unconfirmed; `plo_review_runs=1` is the single-run review.

`CLAUDE.md`, "QA review advises" pitfall, append before "**A review that could not run**":

> **The vote is code's, over judged runs:** each run passes `accept_review` first, and `consensus_review` only counts — a redundancy is voted pair by pair and a three-PLO group survives only when every pair in it has a majority, so the stored set never asserts a pair no majority asserted; the free text and `dropped_findings` come from the run that best matches the vote, so the dropped warning still describes the summary shown.

`data-schemas.md`: add `agreed_runs: int = 1  # runs that said this; 1 for one-run reviews and old rows` to `RedundancyFinding`, `KsecFinding`, `BloomFinding`, `UnusedNeedFinding`, and to `PLOSetReview`:

```python
    runs_requested: int = 1        # plo_review_runs at the time
    runs_succeeded: int = 1        # runs with a usable answer
    agreement_threshold: int = 1   # runs_succeeded // 2 + 1 when ≥2 runs
```

Run `uv run python scripts/dump_prompts.py --check` — expected exit 0 (no prompt changed).

- [ ] **Step 6: Full checks and commit**

Run: `uv run pytest -q`, `uv run ruff check src/ tests/`, `uv run ruff format src/ tests/`, `uv run mypy src/`.

```bash
git add src/curriculum_agent/stages/plo_review.py tests/unit/test_plo_review_run.py CLAUDE.md .claude/skills/curriculum-design-agent/references/data-schemas.md
git commit -m "feat(review): run the QA agent three times and store the majority"
```

---

### Task 3: Stage 06 page shows agreement

**Files:**
- Modify: `frontend/src/types/ploReview.ts`
- Modify: `frontend/src/pages/PloReview.tsx` (`StatusLine` ~265, summary ~201, `Redundancies` ~366, `KsecSection` ~430, `BloomSection` ~461, `UnusedNeeds` ~496)
- Modify: `frontend/src/mock/scenarios.ts` (`buildMockReview`, ~896)

**Interfaces:**
- Consumes: the JSON fields from Tasks 1-2 (`agreed_runs` on each finding; `runs_requested`, `runs_succeeded`, `agreement_threshold` on the review).

- [ ] **Step 1: Types**

In `ploReview.ts`, add `agreed_runs?: number` to `RedundancyFinding`, `KsecFinding`, `BloomFinding`, `UnusedNeedFinding`, and to `PLOSetReview`:

```ts
  /** Agent runs asked for / with a usable answer / needed to agree. 1 on old rows. */
  runs_requested?: number
  runs_succeeded?: number
  agreement_threshold?: number
```

- [ ] **Step 2: Helpers in `PloReview.tsx`** (module level, above the `StatusLine` doc comment)

```tsx
const runsOf = (r: PLOSetReview): number => r.runs_succeeded ?? 1
const isVoted = (r: PLOSetReview): boolean => runsOf(r) >= 2
/** Does a finding meet the review's agreement threshold? Old rows: always. */
const isMain = (agreed: number | undefined, r: PLOSetReview): boolean =>
  (agreed ?? 1) >= (r.agreement_threshold ?? 1)

/** "ตรงกัน 2/3" — only on a review voted over several runs. */
function AgreementChip({ agreed, review }: { agreed: number | undefined; review: PLOSetReview }) {
  if (!isVoted(review)) return null
  return (
    <span className="chip chip-neutral ml-2">
      ตรงกัน {agreed ?? 1}/{runsOf(review)}
    </span>
  )
}
```

- [ ] **Step 3: Status line, notice, summary note**

- `StatusLine`, agent branch: when `isVoted(review)`, add after the existing text: `ตรวจ {runsOf(review)} รอบ แสดงเฉพาะข้อที่ตรงกันอย่างน้อย {review.agreement_threshold} รอบ`.
- Above the dropped-findings notice: when `(review.runs_requested ?? 1) > 1 && runsOf(review) === 1`, render `<p className="notice notice-warn">ได้ผลรอบเดียว ยังไม่ได้ยืนยันซ้ำ</p>`.
- Directly under the summary paragraph, when `isVoted(review) && review.summary_th`: `<p className="text-sm text-pencil">สรุปจากรอบที่ตรงกับผลรวมมากที่สุด</p>`.

- [ ] **Step 4: Main lists show only findings that meet the threshold, each with a chip**

- `Redundancies`: render `review.redundancies.filter((f) => isMain(f.agreed_runs, review))`, `AgreementChip` beside the ids. The empty-state text applies when the filtered list is empty.
- `KsecSection`: `differing = rows.filter((r) => !r.agrees && isMain(r.agreed_runs, review))` (pass `review` in as a prop); a disagreeing row that is not main is left out of both the table and the "ตรงกับหมวดเดิม" `<details>`. Chip on differing rows.
- `BloomSection`: main = `isMain`; chip beside each.
- `UnusedNeeds`: every Need still listed (its facts are code's); the verdict chip and `reason_th` show only when `isMain(n.agreed_runs, review)`; add `AgreementChip` beside a shown verdict.

- [ ] **Step 5: The "พบไม่ถึงเกณฑ์" section**

A new component rendered after `UnusedNeeds`, only when `isVoted(review)` and it has at least one item:

```tsx
function BelowThreshold({ review }: { review: PLOSetReview }) {
  if (!isVoted(review)) return null
  const below = (agreed: number | undefined) => !isMain(agreed, review)
  const red = review.redundancies.filter((f) => below(f.agreed_runs))
  const ksec = review.ksec.filter((k) => !k.agrees && below(k.agreed_runs))
  const bloom = review.bloom.filter((b) => below(b.agreed_runs))
  const unused = review.unused_needs.filter((u) => u.verdict && below(u.agreed_runs))
  const total = red.length + ksec.length + bloom.length + unused.length
  if (total === 0) return null
  return (
    <details className="border-t border-hair pt-4">
      <summary className="eyebrow cursor-pointer">พบไม่ถึงเกณฑ์ ({total})</summary>
      <p className="mt-2 text-sm text-pencil">
        ข้อเหล่านี้มีบางรอบพูดถึงแต่ไม่ถึงเกณฑ์ {review.agreement_threshold} รอบ — ยังไม่ควรถือเป็นข้อค้นพบ
      </p>
      {/* One short list per non-empty kind, headed ความซ้ำซ้อน / หมวด KSEC /
          ระดับ Bloom / Need ที่ไม่ได้เป็น PLO, each item rendered like its main
          section's item (ids or plo_id, reason_th) with an AgreementChip. */}
    </details>
  )
}
```

Fill the four lists following the comment, reusing the same markup the main sections use for one item (no new CSS).

- [ ] **Step 6: Mock**

In `buildMockReview` set `runs_requested: 3, runs_succeeded: 3, agreement_threshold: 2`; give the existing redundancy group `agreed_runs: 3`, the disagreeing KSEC row `agreed_runs: 2`, the Bloom finding `agreed_runs: 3`, each unused verdict `agreed_runs: 3`; and add one more redundancy finding on two other mock PLOs with `agreed_runs: 1` and Thai reason "บางรอบเห็นว่าสองข้อนี้ใช้กริยาและวัตถุใกล้กัน" so the below-threshold section shows. Every other KSEC row gets `agreed_runs: 3`.

- [ ] **Step 7: Verify and commit**

From `frontend/`: `npm run lint` (0 errors; the existing `Pipeline.tsx` warning is fine) and `npm run build`. Check in mock mode by reading the code path: an old review object without the new fields renders no chips, no "พบไม่ถึงเกณฑ์", no single-run notice.

```bash
git add frontend/src/types/ploReview.ts frontend/src/pages/PloReview.tsx frontend/src/mock/scenarios.ts
git commit -m "feat(ui): show how many QA runs agreed and set apart what too few did"
```

---

### Task 4 (controller): Live measurement

Not dispatched. With the backend on :8000 (auto-reload picks up the code):

- [ ] `POST /programs/program-2-run-1/plos/review/run` three times, one after another, polling `GET /programs/program-2-run-1/jobs/` until each job is terminal.
- [ ] For each run record: wall time (`finished_at - created_at`), `runs_succeeded`, the main redundancy findings (`agreed_runs >= agreement_threshold`), and the below-threshold count.
- [ ] Success: the three sets of main redundancy findings are identical or differ by at most one finding.
- [ ] Write a "Measured" section into the spec and commit it by path.
