# PLO QA Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the PLO set review into the closing stage 06: a small tool-using QA agent that reads the finished PLO set, with every number computed in code, run after the report and shown on its own page.

**Architecture:** A pure-code facts module builds a dossier (the set, the Need sentences behind it, KSEC coverage, Bloom histogram, the important unused Needs). A structured action loop on the existing `plo_review` slot reads the dossier, may make up to 4 tool calls (`bloom_lookup`, `check_verbs`, `need_detail` — no evidence access), and finishes with loose findings that `accept_review` judges entry by entry. Any failure stores the code facts as a `code_only` review. The graph runs `review_plos_node → plo_report → plo_review → END`; "สร้างรายงาน" no longer runs the review.

**Tech Stack:** Python 3.11, Pydantic v2, Instructor (JSON mode), LangGraph, FastAPI, SQLAlchemy async, pytest (asyncio_mode=auto); React 19 + Vite + TypeScript + Tailwind (component classes in `frontend/src/index.css`).

**Spec:** `docs/superpowers/specs/2026-10-12-plo-qa-agent-design.md`

## Global Constraints

- Advisory only: no code path in this plan changes a PLO, Need, KSEC tag or Bloom level from a review finding.
- The agent never sees evidence text, member skill names, a shared-evidence share, SMART diagnoses/findings, or a previous review — not in the dossier and not through any tool.
- At most 4 tool calls per run (`MAX_TOOL_CALLS = 4`); at most 6 steps (`MAX_STEPS = 6`); every step bounds hidden reasoning at 1024 tokens; whole-run timeout `settings.plo_review_timeout_seconds = 300`.
- Every number stored on a review is computed in code; no model field is ever copied into `ksec_coverage`, `bloom_histogram`, `unused_needs[*]` facts, `current`, `agrees` or `declared`.
- Any failure (slot disabled, timeout, malformed/truncated step, step cap, answer emptied by `accept_review`) stores the code facts with `reviewed_by="code_only"` and `code_only_reason` in `disabled` / `failed` / `timeout`; no agent finding is manufactured.
- Keep every existing name: slot `PLO_REVIEW_*`, table `plo_reviews`, job kind `plo_review`, routes under `/programs/{id}/plos/review`.
- Decision (designer, 2026-10-12): `ksec_coverage` and `bloom_histogram` count **every PLO, optional included**. `core_count` stays core-only (it is measured against the 6-10 band). With zero PLOs no flag is raised.
- Unused-Need selection: the 5 highest `demand_score` uncited Needs plus every uncited Need whose `source_stakeholder_types` contains `professional_council`, de-duplicated, ordered by `demand_score` descending then `need_id`. Exclusion reason: `out_of_scope` (`not is_in_scope`) first, then `unwritten` (`is_unwritten_need`), else `lost_on_demand`.
- Code, comments, log lines, commit messages: English. Designer-facing strings: Thai.
- Repository pattern for data access; prompts live in `src/curriculum_agent/prompts/`; type hints everywhere with `from __future__ import annotations`; `loguru` for logging.
- Frontend: only `index.css` component classes and tokens, never the Tailwind colour palette; layout works at phone width.
- Commits end with the session's Co-Authored-By trailer; stage files by explicit path only — never `.scratch/plo-scope-guard/**`, `curriculum-design-agent.skill`, or `.claude/skills/*`.

## Review Focus

1. A PLO citing a Need id that no longer exists → it contributes no KSEC count, the dossier renders "(ไม่พบ Need)", nothing raises (Task 1 test).
2. A program whose PLOs are all optional → they are counted in coverage and histogram, `core_count` is 0; an empty set raises no flag (Task 1 test).
3. A review row stored before this change (no new fields) → reads with `reviewed_by="agent"` and reads stale under the new fingerprint (Task 1 and Task 3 tests).
4. The agent calls `need_detail` with a Need outside the unused list, or `check_verbs` with an unknown PLO → refused observation, and the refused call still counts toward the 4 (Task 2 test).
5. In the graph path the Needs fail to load → the node logs, keeps the stored review (or none), and the session still completes (Task 3 test).

---

### Task 1: Review models, the facts module, and the new fingerprint

**Files:**
- Modify: `src/curriculum_agent/models.py` (after `BloomFinding`, inside `PLOSetReview`)
- Create: `src/curriculum_agent/stages/plo_review_facts.py`
- Modify: `src/curriculum_agent/stages/plo_review.py` (remove `_KSEC_ORDER`, `_normalize_ksec`, `current_ksec`, `plo_fingerprint`, `is_stale` bodies; re-export from the facts module)
- Modify: `src/curriculum_agent/data/repositories.py:438` (`_REVIEW_BODY_FIELDS`)
- Modify: `src/curriculum_agent/data/program_copy.py:115-172` (`_fingerprint`, review re-fingerprint)
- Modify: `src/curriculum_agent/prompts/plo_review.py` (only: `ReviewItem` stays here; no other change in this task)
- Test: `tests/unit/test_plo_review_facts.py` (new); update `tests/unit/test_plo_review_accept.py` fingerprint/stale tests; `tests/unit/test_program_copy_build.py` if it calls `plo_fingerprint`

**Interfaces:**
- Produces (models): `KsecCoverage`, `BloomHistogram`, `UnusedNeedFinding`, `ReviewToolCall`; `PLOSetReview` gains `ksec_coverage`, `bloom_histogram`, `coverage_th`, `unused_needs`, `reviewed_by`, `code_only_reason`, `tool_calls`.
- Produces (`stages/plo_review_facts.py`):
  - `KSEC_ORDER: tuple[str, ...] = ("K", "S", "E", "C")`
  - `normalize_ksec(values: Sequence[str]) -> list[str]`
  - `current_ksec(plo: PLO, needs_by_id: Mapping[str, Need]) -> list[str]`
  - `ksec_coverage(plos: Sequence[PLO], needs_by_id: Mapping[str, Need]) -> KsecCoverage`
  - `bloom_histogram(plos: Sequence[PLO], degree_level: str) -> BloomHistogram`
  - `exclusion_reason(need: Need) -> str`
  - `select_unused_needs(plos: Sequence[PLO], needs: Sequence[Need], *, top: int = UNUSED_TOP) -> list[UnusedNeedFinding]` with `UNUSED_TOP = 5`
  - `@dataclass(frozen=True) class ReviewDossier` (fields below)
  - `build_dossier(plos, needs, *, program_context: str | None, degree_level: str) -> ReviewDossier`
  - `need_demands(needs: Sequence[Need]) -> dict[str, float]`
  - `plo_fingerprint(plos: Sequence[PLO], demands: Mapping[str, float]) -> str`
  - `is_stale(review: PLOSetReview, plos: Sequence[PLO], demands: Mapping[str, float]) -> bool`
- `plo_review.py` keeps importable names `current_ksec`, `plo_fingerprint`, `is_stale` (re-exported) so existing importers (`program_copy`, `plo_report`, routes) resolve until later tasks change their calls.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_plo_review_facts.py`

```python
from __future__ import annotations

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    PLOSetReview,
    SMARTCheck,
    StakeholderType,
)
from curriculum_agent.stages.plo_review_facts import (
    bloom_histogram,
    build_dossier,
    current_ksec,
    exclusion_reason,
    is_stale,
    ksec_coverage,
    need_demands,
    plo_fingerprint,
    select_unused_needs,
)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _need(
    nid: str,
    ksec: KSECCategory = KSECCategory.S,
    *,
    demand: float = 0.5,
    types: list[StakeholderType] | None = None,
    statement: str | None = None,
    in_field: int | None = None,
) -> Need:
    data: dict = dict(
        need_id=nid,
        program_id="p",
        statement_th=statement or f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        rationale_th=f"เหตุผลของ {nid}",
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=[f"S-{nid}-1", f"S-{nid}-2"],
        source_evidence_ids=[f"E-{nid}"],
        source_stakeholder_types=types or [StakeholderType.EMPLOYER],
        stakeholder_coverage={t: 1 for t in (types or [StakeholderType.EMPLOYER])},
        freq=2,
        demand_score=demand,
    )
    if in_field is not None:
        data["in_field_skill_count"] = in_field
    return Need(**data)


def _plo(
    pid: str,
    need_ids: list[str],
    *,
    level: BloomLevel = BloomLevel.APPLY,
    optional: bool = False,
) -> PLO:
    return PLO(
        plo_id=pid,
        program_id="p",
        statement_th=f"วิเคราะห์ระบบงาน {pid} เพื่อเสนอแนวทางแก้ปัญหา",
        bloom_level=level,
        action_verb_th="วิเคราะห์",
        smart_check=_SMART,
        source_need_ids=need_ids,
        source_evidence_ids=["E1"],
        rationale_th="เหตุผล",
        is_optional=optional,
    )


# ------------------------------ KSEC ------------------------------


def test_current_ksec_expands_ec_and_ignores_a_missing_need() -> None:
    needs = {"n1": _need("n1", KSECCategory.EC), "n2": _need("n2", KSECCategory.K)}
    assert current_ksec(_plo("PLO1", ["n2", "n1", "gone"]), needs) == ["K", "E", "C"]


def test_coverage_counts_every_plo_per_domain_and_names_the_missing() -> None:
    needs = {"n1": _need("n1", KSECCategory.S), "n2": _need("n2", KSECCategory.EC)}
    plos = [_plo("PLO1", ["n1"]), _plo("PLO2", ["n2"]), _plo("OPT1", ["n1"], optional=True)]
    cov = ksec_coverage(plos, needs)
    assert cov.counts == {"K": 0, "S": 2, "E": 1, "C": 1}
    assert cov.missing == ["K"]
    assert cov.flags == []


def test_coverage_flags_an_all_k_set_and_a_set_without_e_or_c() -> None:
    needs = {"k": _need("k", KSECCategory.K)}
    cov = ksec_coverage([_plo("PLO1", ["k"]), _plo("PLO2", ["k"])], needs)
    assert cov.flags == ["all_k", "no_e_or_c"]


def test_a_plo_citing_a_vanished_need_counts_nothing() -> None:
    cov = ksec_coverage([_plo("PLO1", ["gone"])], {})
    assert cov.counts == {"K": 0, "S": 0, "E": 0, "C": 0}


def test_optional_plos_count_and_an_empty_set_raises_no_flag() -> None:
    needs = {"k": _need("k", KSECCategory.K)}
    cov = ksec_coverage([_plo("OPT1", ["k"], optional=True)], needs)
    assert cov.counts == {"K": 1, "S": 0, "E": 0, "C": 0}
    assert cov.flags == ["all_k", "no_e_or_c"]
    hist = bloom_histogram([_plo("OPT1", ["k"], optional=True, level=BloomLevel.REMEMBER)], "bachelor")
    assert hist.counts["remember"] == 1 and hist.flags == ["below_apply_majority"]
    assert ksec_coverage([], needs).flags == [] and bloom_histogram([], "bachelor").flags == []


# ------------------------------ Bloom ------------------------------


def test_histogram_counts_every_plo_in_level_order() -> None:
    plos = [
        _plo("PLO1", ["n"], level=BloomLevel.CREATE),
        _plo("PLO2", ["n"], level=BloomLevel.APPLY),
        _plo("PLO3", ["n"], level=BloomLevel.CREATE),
        _plo("OPT1", ["n"], level=BloomLevel.REMEMBER, optional=True),
    ]
    hist = bloom_histogram(plos, "bachelor")
    assert list(hist.counts) == [l.value for l in BloomLevel]
    assert hist.counts["create"] == 2 and hist.counts["apply"] == 1 and hist.counts["remember"] == 1
    assert hist.degree_level == "bachelor"
    assert hist.flags == []


def test_histogram_flags_a_majority_below_apply() -> None:
    plos = [
        _plo("PLO1", ["n"], level=BloomLevel.UNDERSTAND),
        _plo("PLO2", ["n"], level=BloomLevel.REMEMBER),
        _plo("PLO3", ["n"], level=BloomLevel.APPLY),
    ]
    assert bloom_histogram(plos, "bachelor").flags == ["below_apply_majority"]


def test_exactly_half_below_apply_is_not_a_majority() -> None:
    plos = [_plo("PLO1", ["n"], level=BloomLevel.UNDERSTAND), _plo("PLO2", ["n"])]
    assert bloom_histogram(plos, "bachelor").flags == []


# ------------------------------ unused Needs ------------------------------


def test_unused_needs_are_the_top_five_by_demand_plus_council_backed() -> None:
    needs = [_need(f"n{i}", demand=i / 10) for i in range(1, 9)]  # n8 highest
    council = _need("c1", demand=0.05, types=[StakeholderType.PROFESSIONAL_COUNCIL])
    cited = _need("used", demand=0.99)
    plos = [_plo("PLO1", ["used"])]
    picked = select_unused_needs(plos, [*needs, council, cited])
    assert [u.need_id for u in picked] == ["n8", "n7", "n6", "n5", "n4", "c1"]
    assert picked[-1].stakeholder_types == ["professional_council"]
    assert all(u.verdict is None and u.reason_th == "" for u in picked)


def test_unused_selection_is_deduplicated_when_a_council_need_is_also_top() -> None:
    council = _need("c1", demand=0.9, types=[StakeholderType.PROFESSIONAL_COUNCIL])
    picked = select_unused_needs([], [council, _need("n1", demand=0.1)])
    assert [u.need_id for u in picked] == ["c1", "n1"]


def test_exclusion_reason_checks_scope_then_unwritten() -> None:
    assert exclusion_reason(_need("a")) == "lost_on_demand"
    assert exclusion_reason(_need("b", in_field=0)) == "out_of_scope"
    unwritten = _need("c", statement="[ต้องทบทวน] ทักษะก, ทักษะข, ทักษะค ที่ต้องเขียนใหม่")
    assert exclusion_reason(unwritten) == "unwritten"


# ------------------------------ dossier ------------------------------


def test_the_dossier_carries_no_evidence_skill_names_or_old_verdicts() -> None:
    """The information-bias rule (spec section 2): the dossier is the set, its
    Need sentences, and code facts — nothing a reviewer could anchor on."""
    needs = [_need("n1"), _need("n2", KSECCategory.EC), _need("u1", demand=0.9)]
    plos = [_plo("PLO1", ["n1"]), _plo("PLO2", ["n2", "gone"])]
    d = build_dossier(plos, needs, program_context="หลักสูตรปริญญาตรี สาขาการแปล", degree_level="bachelor")
    text = repr(d)
    for forbidden in ("E-n1", "S-n1-1", "rationale", "เหตุผลของ", "smart_check", "diagnosis"):
        assert forbidden not in text, forbidden
    assert [i.plo_id for i in d.items] == ["PLO1", "PLO2"]
    assert d.items[1].need_statements_th == (needs[1].statement_th,)
    assert d.core_count == 2
    assert [u.need_id for u in d.unused_needs] == ["u1"]


# ------------------------------ fingerprint ------------------------------


def test_fingerprint_moves_when_a_need_demand_changes() -> None:
    plos = [_plo("PLO1", ["n1"])]
    a = plo_fingerprint(plos, need_demands([_need("n1", demand=0.5)]))
    b = plo_fingerprint(plos, need_demands([_need("n1", demand=0.6)]))
    c = plo_fingerprint(plos, need_demands([_need("n1", demand=0.5), _need("n2")]))
    assert len({a, b, c}) == 3
    assert a == plo_fingerprint(plos, {"n1": 0.5})


def test_an_old_review_row_reads_and_is_stale_under_the_new_fingerprint() -> None:
    old = PLOSetReview.model_validate(
        {
            "program_id": "p",
            "plo_fingerprint": "0" * 64,
            "model": "z-ai/glm-5.3-flash",
            "created_at": "2026-10-05T16:32:00",
            "redundancies": [],
            "ksec": [],
            "bloom": [],
            "bloom_distribution_th": "",
            "summary_th": "เดิม",
        }
    )
    assert old.reviewed_by == "agent"
    assert old.code_only_reason is None and old.unused_needs == [] and old.tool_calls == []
    assert is_stale(old, [_plo("PLO1", ["n1"])], {"n1": 0.5})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/test_plo_review_facts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.stages.plo_review_facts'`

- [ ] **Step 3: Add the models** — in `src/curriculum_agent/models.py`, after `BloomFinding` and before `PLOSetReview`:

```python
class KsecCoverage(BaseModel):
    """How many PLOs (optional included) sit in each of K/S/E/C. Computed in code, never by the reviewer.

    Plain `str` keys and flags for the `soft_flags` reason: a stored row must
    stay readable if the vocabulary moves.
    """

    counts: dict[str, int] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class BloomHistogram(BaseModel):
    """PLOs (optional included) per Bloom level against the degree level. Computed in code."""

    counts: dict[str, int] = Field(default_factory=dict)
    degree_level: str = ""
    flags: list[str] = Field(default_factory=list)


class UnusedNeedFinding(BaseModel):
    """An important Need no PLO cites: facts from code, verdict from the reviewer."""

    need_id: str
    statement_th: str
    demand_score: float
    ksec_category: str
    stakeholder_types: list[str] = Field(default_factory=list)
    exclusion: str
    verdict: str | None = None
    reason_th: str = ""


class ReviewToolCall(BaseModel):
    """One tool call the QA agent made, in order, for the "what it looked at" list."""

    tool: str
    arg: str = ""
```

and extend `PLOSetReview` (keep its existing fields; append these):

```python
    ksec_coverage: KsecCoverage = Field(default_factory=KsecCoverage)
    bloom_histogram: BloomHistogram = Field(default_factory=BloomHistogram)
    coverage_th: str = ""
    unused_needs: list[UnusedNeedFinding] = Field(default_factory=list)
    # "agent" for every row written before this field existed: those were all
    # made by the model. Plain str, not a Literal, for the soft_flags reason.
    reviewed_by: str = "agent"
    code_only_reason: str | None = None
    tool_calls: list[ReviewToolCall] = Field(default_factory=list)
```

Update the `PLOSetReview` docstring's first line to: `"""The QA agent's review of one program's PLO set — see stages/plo_review.py.`

- [ ] **Step 4: Create `src/curriculum_agent/stages/plo_review_facts.py`**

```python
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
from curriculum_agent.prompts.plo_review import ReviewItem
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
        [needs_by_id[nid].ksec_category.value for nid in plo.source_need_ids if nid in needs_by_id]
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
            ksec_category=n.ksec_category.value,
            stakeholder_types=[t.value for t in n.source_stakeholder_types],
            exclusion=exclusion_reason(n),
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
            need_statements_th=tuple(
                needs_by_id[nid].statement_th for nid in p.source_need_ids if nid in needs_by_id
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
```

- [ ] **Step 5: Point `plo_review.py` at the facts module.** Delete `_KSEC_ORDER`, `_normalize_ksec`, `current_ksec`, `plo_fingerprint` and `is_stale` from `src/curriculum_agent/stages/plo_review.py`, add

```python
from curriculum_agent.stages.plo_review_facts import (
    current_ksec,
    is_stale,
    need_demands,
    normalize_ksec,
    plo_fingerprint,
)
```

and replace the remaining `_normalize_ksec(` call in `accept_review` with `normalize_ksec(`. Callers that pass only PLOs to `plo_fingerprint`/`is_stale` (`_call`, `review_plo_set`, `plo_report.run`, the two review routes) get `need_demands(needs)` from the Needs they already load or — where none are loaded — load them with `NeedRepository().list_by_program(program_id)`; Tasks 3-5 rewrite these bodies, so a minimal correct call is enough here. `plo_report.py` may keep importing `is_stale` from `plo_review` for now.

- [ ] **Step 6: Persist the new fields** — `src/curriculum_agent/data/repositories.py:438`:

```python
_REVIEW_BODY_FIELDS = {
    "redundancies",
    "ksec",
    "bloom",
    "bloom_distribution_th",
    "summary_th",
    "ksec_coverage",
    "bloom_histogram",
    "coverage_th",
    "unused_needs",
    "reviewed_by",
    "code_only_reason",
    "tool_calls",
}
```

Add a test to `tests/unit/test_plo_review_storage.py` (follow that file's existing session-mocking style) asserting `upsert` writes `reviewed_by`, `unused_needs` and `tool_calls` into the JSONB body.

- [ ] **Step 7: Re-fingerprint copies with Needs** — `src/curriculum_agent/data/program_copy.py`:

```python
def _fingerprint(plo_rows: list[PLOTable], need_rows: list[NeedTable]) -> str | None:
    """The review fingerprint of a program's rows, or None if a PLO row won't parse."""
    try:
        return plo_fingerprint(
            [PLO.model_validate(_row_to_dict(r)) for r in plo_rows],
            {r.need_id: r.demand_score for r in need_rows},
        )
    except Exception as exc:  # noqa: BLE001 - a legacy row only costs freshness
        logger.warning(f"program copy: PLO rows did not parse for the fingerprint: {exc}")
        return None
```

and in `build_copy`: `source_fp = _fingerprint(src.plos, src.needs)`, `copied_fp = _fingerprint(plos, needs)`. Import `NeedTable` if not imported. Import `plo_fingerprint` from `curriculum_agent.stages.plo_review_facts`.

- [ ] **Step 8: Update the moved-function tests.** In `tests/unit/test_plo_review_accept.py`, `test_fingerprint_ignores_order_and_moves_on_each_field` and `test_is_stale_compares_fingerprints` call `plo_fingerprint(PLOS)` / `is_stale(review, PLOS)`; pass `{}` (or `need_demands(NEEDS.values())`) as the demands argument. Any other test calling these with one argument gets the same fix (`uv run pytest -q` lists them).

- [ ] **Step 9: Run the tests**

Run: `uv run pytest tests/unit/test_plo_review_facts.py tests/unit/test_plo_review_accept.py tests/unit/test_plo_review_storage.py tests/unit/test_program_copy_build.py -q`
Expected: PASS. Then `uv run pytest -q` — every test that still fails must be one Task 3-5 rewrites (the report/review wiring); note them in the report rather than weakening them.

- [ ] **Step 10: Lint, type-check, commit**

```bash
uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/
git add src/curriculum_agent/models.py src/curriculum_agent/stages/plo_review_facts.py src/curriculum_agent/stages/plo_review.py src/curriculum_agent/data/repositories.py src/curriculum_agent/data/program_copy.py tests/unit/test_plo_review_facts.py tests/unit/test_plo_review_accept.py tests/unit/test_plo_review_storage.py tests/unit/test_program_copy_build.py
git commit -m "feat(plo_review): code facts, the QA dossier, and a fingerprint that covers the Needs"
```

---

### Task 2: The QA agent prompt and loop

**Files:**
- Modify: `src/curriculum_agent/prompts/plo_review.py` (rewrite `_SYSTEM_TH` and `build_plo_review_prompt`; add observation builders; keep `ReviewItem`)
- Create: `src/curriculum_agent/stages/plo_review_agent.py`
- Modify: `src/curriculum_agent/config.py:325` (`plo_review_timeout_seconds: int = 300`)
- Test: `tests/unit/test_plo_review_prompt.py` (rewrite), `tests/unit/test_plo_review_agent.py` (new)

**Interfaces:**
- Consumes: `ReviewDossier`, `ReviewItem`, `UnusedNeedFinding`, `ReviewToolCall` (Task 1).
- Produces (`prompts/plo_review.py`): `build_plo_review_prompt(dossier: ReviewDossier) -> list[dict[str, str]]`, `build_review_observation(tool: str, payload: Mapping[str, Any]) -> str`, `build_review_refusal(reason_th: str) -> str`.
- Produces (`stages/plo_review_agent.py`): `MAX_TOOL_CALLS = 4`, `MAX_STEPS = 6`; loose answer models `Redundancy`, `KsecVerdict`, `BloomVerdict`, `UnusedVerdict`; `ReviewCallTool`, `ReviewFinish`, `ReviewStep`; `ReviewToolName`; `@dataclass AgentOutcome(finish: ReviewFinish | None, reason: str | None, tool_calls: list[ReviewToolCall])`; `async run_review_agent(dossier: ReviewDossier, unused_needs: Mapping[str, Need]) -> AgentOutcome`; pure `run_review_tool(dossier, unused_needs, tool: ReviewToolName, arg: str) -> tuple[bool, dict[str, Any]]`.

Import direction note: `prompts/plo_review.py` must not import `stages/plo_review_facts` at module level (the facts module imports `ReviewItem` from the prompt module). Type the dossier parameter under `if TYPE_CHECKING:`.

- [ ] **Step 1: Write the failing prompt tests** — replace `tests/unit/test_plo_review_prompt.py`:

```python
from __future__ import annotations

from curriculum_agent.models import BloomHistogram, KsecCoverage, UnusedNeedFinding
from curriculum_agent.prompts.plo_review import (
    ReviewItem,
    build_plo_review_prompt,
    build_review_observation,
    build_review_refusal,
)
from curriculum_agent.stages.plo_review_facts import ReviewDossier


def _dossier(**kw: object) -> ReviewDossier:
    base: dict = dict(
        program_context="หลักสูตรปริญญาตรี สาขาการแปล",
        degree_level="bachelor",
        items=(
            ReviewItem(
                plo_id="PLO1",
                is_optional=False,
                statement_th="แปลเอกสารธุรกิจโดยใช้เครื่องมือดิจิทัล",
                action_verb_th="แปล",
                bloom_level="apply",
                current_ksec=("S",),
                need_statements_th=("ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้",),
            ),
            ReviewItem(
                plo_id="OPT1",
                is_optional=True,
                statement_th="ประพฤติตนตามจรรยาบรรณนักแปล",
                action_verb_th="ประพฤติตน",
                bloom_level="apply",
                current_ksec=("E", "C"),
                need_statements_th=(),
            ),
        ),
        ksec_coverage=KsecCoverage(
            counts={"K": 0, "S": 1, "E": 0, "C": 0}, missing=["K", "E", "C"], flags=["no_e_or_c"]
        ),
        bloom_histogram=BloomHistogram(
            counts={"remember": 0, "understand": 0, "apply": 1, "analyze": 0, "evaluate": 0, "create": 0},
            degree_level="bachelor",
            flags=[],
        ),
        core_count=1,
        unused_needs=(
            UnusedNeedFinding(
                need_id="n9",
                statement_th="ต้องการบัณฑิตที่ล่ามในการประชุมได้",
                demand_score=0.42,
                ksec_category="S",
                stakeholder_types=["employer"],
                exclusion="lost_on_demand",
            ),
        ),
    )
    base.update(kw)
    return ReviewDossier(**base)


def _turns() -> tuple[str, str]:
    msgs = build_plo_review_prompt(_dossier())
    assert [m["role"] for m in msgs] == ["system", "user"]
    return msgs[0]["content"], msgs[1]["content"]


def test_every_plo_its_needs_and_ksec_reach_the_user_turn() -> None:
    _, user = _turns()
    assert "[PLO1] (หลัก)" in user and "[OPT1] (เสริม)" in user
    assert "ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้" in user
    assert "E|C" in user
    assert "(ไม่พบ Need)" in user


def test_the_code_facts_reach_the_user_turn_as_facts() -> None:
    _, user = _turns()
    assert "K 0 · S 1 · E 0 · C 0" in user
    assert "no_e_or_c" in user
    assert "apply 1" in user
    assert "PLO หลัก 1 ข้อ" in user


def test_the_unused_needs_reach_the_user_turn_with_their_ids() -> None:
    _, user = _turns()
    assert "[n9]" in user and "0.42" in user and "lost_on_demand" in user


def test_no_unused_need_is_said_outright() -> None:
    user = build_plo_review_prompt(_dossier(unused_needs=()))[1]["content"]
    assert "ไม่มี Need สำคัญที่ไม่ได้เป็น PLO" in user


def test_rubric_names_the_six_checks_tools_budget_and_json_keys() -> None:
    system, _ = _turns()
    for key in (
        "redundancies", "ksec", "bloom", "bloom_distribution_th",
        "coverage_th", "unused_needs", "summary_th",
        "bloom_lookup", "check_verbs", "need_detail",
    ):
        assert key in system, key
    assert "4 ครั้ง" in system


def test_rubric_says_the_reviewer_changes_nothing_and_does_not_recount() -> None:
    system, _ = _turns()
    assert "ห้ามเขียนประโยค PLO ใหม่" in system
    assert "ไม่ต้องนับใหม่" in system


def test_rubric_keeps_the_existing_rules() -> None:
    system, _ = _turns()
    assert "ไม่ถือว่าซ้ำ" in system  # sharing a field is not redundancy
    assert "มากกว่าหนึ่งหมวด" in system  # KSEC may be several


def test_observation_and_refusal_are_thai_user_turn_text() -> None:
    assert "check_verbs" in build_review_observation("check_verbs", {"plo_id": "PLO1"})
    assert "ปฏิเสธ" in build_review_refusal("ใช้ tool ครบแล้ว")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_plo_review_prompt.py -q`
Expected: FAIL (`ImportError` on `build_review_observation`, or the old signature).

- [ ] **Step 3: Rewrite `src/curriculum_agent/prompts/plo_review.py`**

```python
"""The PLO QA agent prompt: read the finished set, check a few suspicions, advise.

Stage 06. The agent is handed the set, the Need sentences behind it, and facts
code computed (spec 2026-10-12). It may check a suspicion with at most four tool
calls, then answers once. It sees no evidence text on purpose: the more upstream
detail a reviewer reads, the more it anchors on it instead of judging the set as
a curriculum committee reads it.

The answer is advice, so the prompt says outright that the reviewer rewrites
nothing — a reviewer handed the statements and no such line drifts into proposing
replacement sentences, which nothing downstream would check.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from curriculum_agent.stages.plo_review_facts import ReviewDossier


@dataclass(frozen=True)
class ReviewItem:
    plo_id: str
    is_optional: bool
    statement_th: str
    action_verb_th: str
    bloom_level: str
    current_ksec: tuple[str, ...]
    need_statements_th: tuple[str, ...]


_SYSTEM_TH = """คุณเป็นกรรมการตรวจคุณภาพหลักสูตรอุดมศึกษาไทยตามแนว OBE และมาตรฐาน อว.
งานของคุณคือตรวจ PLO ทั้งชุดที่ทำเสร็จแล้วของหลักสูตรหนึ่ง แล้วรายงานข้อเสนอแนะให้ผู้ออกแบบหลักสูตร
คุณไม่ได้แก้ PLO ห้ามเขียนประโยค PLO ใหม่ ให้บอกเพียงว่าควรปรับอะไรและเพราะอะไร
ตัวเลขในหัวข้อ "ข้อเท็จจริงที่ระบบนับให้" ถูกต้องแล้ว ไม่ต้องนับใหม่ ให้ตีความ

ตรวจ 6 เรื่อง
1) redundancies (ความซ้ำซ้อน): กลุ่ม PLO 2-3 ข้อที่กรรมการหลักสูตรจะอ่านว่าเป็นผลลัพธ์เดียวกัน
   คือมีงานหลักเดียวกันกับวัตถุประเภทเดียวกัน ต่างกันแค่บริบท เครื่องมือ หรือถ้อยคำ
   การอยู่ในสาขาเดียวกันหรือใช้เครื่องมือเดียวกันไม่ถือว่าซ้ำ เช่น ทุกข้อของหลักสูตรการแปลมีการแปลอยู่แล้ว
   แต่ละกลุ่ม: plo_ids, reason_th (ซ้ำกันตรงไหน), suggestion_th (ควรรวม หรือควรแยกวัตถุให้ชัดอย่างไร)
2) ksec (หมวดสมรรถนะรายข้อ): ทุก PLO ต้องมีหนึ่งรายการ ระบุหมวดที่ผลลัพธ์ตามที่เขียนไว้ควรอยู่
   เลือกได้มากกว่าหนึ่งหมวดจาก K S E C
   K = รู้และอธิบายองค์ความรู้, S = ลงมือทำงานของวิชาชีพ, E = คุณธรรมจริยธรรม,
   C = คุณลักษณะบุคคล เช่น การปรับตัว ภาวะผู้นำ การพัฒนาตนเอง
   ตัดสินจากสิ่งที่บัณฑิตทำในประโยค ไม่ใช่จากหมวดเดิม
   แต่ละรายการ: plo_id, suggested (list เช่น ["S","E"]), reason_th
3) bloom (ระดับ Bloom รายข้อ): ใส่เฉพาะ PLO ที่ระดับที่ประกาศไม่เหมาะกับกริยา กรรม และระดับปริญญา
   แต่ละรายการ: plo_id, suggested_level (remember understand apply analyze evaluate create), reason_th
4) coverage_th (KSEC ทั้งชุด): หนึ่งถึงสามประโยค ตีความจำนวน PLO ต่อหมวดที่ระบบนับให้
   หมวดไหนขาดหรือหนาแน่นเกิน และสำคัญอย่างไรกับหลักสูตรนี้
5) bloom_distribution_th (การกระจาย Bloom): หนึ่งถึงสามประโยค ตีความจำนวน PLO ต่อระดับเทียบระดับปริญญา
6) unused_needs (Need สำคัญที่ไม่ได้เป็น PLO): สำหรับแต่ละ Need ในรายการที่ให้มา
   need_id, verdict ("consider" = ควรพิจารณาใส่เป็น PLO, "ok_to_leave" = ปล่อยไว้ได้), reason_th

summary_th: สรุป 2-5 ประโยคให้ผู้ออกแบบ เรียงเรื่องสำคัญก่อน

เครื่องมือ (ใช้ได้รวมไม่เกิน 4 ครั้ง ใช้เมื่อสงสัยจริงเท่านั้น ไม่ต้องใช้ก็ได้)
- bloom_lookup: arg = กริยาภาษาไทย ได้ระดับ Bloom ที่กริยานั้นอยู่ได้
- check_verbs: arg = plo_id ได้ผลตรวจกริยาของ PLO ข้อนั้นด้วยโค้ด
  (ประโยคขึ้นต้นด้วยกริยาที่ประกาศไหม กริยาที่ประกาศมีกี่คำ และอยู่ระดับใดได้บ้าง)
- need_detail: arg = need_id ของ Need ในรายการ Need ที่ไม่ได้เป็น PLO เท่านั้น
  ได้คำอธิบายของโมเดลที่เขียน Need นั้น จำนวนทักษะสมาชิก และจำนวนเสียงต่อกลุ่มผู้มีส่วนได้ส่วนเสีย

ทุกรอบตอบเป็น JSON object เดียว: {"reasoning_th": "...", "action": {...}}
เรียกเครื่องมือ: "action": {"kind": "call_tool", "tool": "check_verbs", "arg": "PLO3"}
สรุปผล: "action": {"kind": "finish", "redundancies": [...], "ksec": [...], "bloom": [...],
  "bloom_distribution_th": "...", "coverage_th": "...", "unused_needs": [...], "summary_th": "..."}
ถ้าชุด PLO ไม่มีปัญหาในเรื่องใด ให้ส่งรายการของเรื่องนั้นว่าง แต่ ksec ต้องมีครบทุก PLO และต้องมี summary_th เสมอ
ใช้ plo_id และ need_id ตามที่ให้มาเท่านั้น"""  # noqa: E501


def _ksec_label(tags: Sequence[str]) -> str:
    if not tags:
        return "-"
    joined = "|".join(tags)
    return joined


def _counts_line(counts: Mapping[str, int], sep: str = " · ") -> str:
    return sep.join(f"{k} {v}" for k, v in counts.items())


def build_plo_review_prompt(dossier: ReviewDossier) -> list[dict[str, str]]:
    """The rubric, then the whole dossier in one user turn."""
    blocks: list[str] = []
    for item in dossier.items:
        needs = "\n".join(f"- {s}" for s in item.need_statements_th) or "- (ไม่พบ Need)"
        blocks.append(
            f"[{item.plo_id}] ({'เสริม' if item.is_optional else 'หลัก'})\n"
            f"ประโยค: {item.statement_th}\n"
            f"กริยา: {item.action_verb_th} | ระดับ Bloom: {item.bloom_level} | "
            f"KSEC ปัจจุบัน: {_ksec_label(item.current_ksec)}\n"
            f"Need ที่อ้างถึง:\n{needs}"
        )
    cov = dossier.ksec_coverage
    hist = dossier.bloom_histogram
    facts = (
        "ข้อเท็จจริงที่ระบบนับให้ (KSEC และ Bloom นับทุก PLO รวม PLO เสริม):\n"
        f"- PLO หลัก {dossier.core_count} ข้อ (นโยบาย 6-10 ข้อ)\n"
        f"- KSEC: {_counts_line(cov.counts)} | หมวดที่ไม่มี: {', '.join(cov.missing) or '-'} | "
        f"ธง: {', '.join(cov.flags) or '-'}\n"
        f"- Bloom ({hist.degree_level or '-'}): {_counts_line(hist.counts, ', ')} | "
        f"ธง: {', '.join(hist.flags) or '-'}"
    )
    if dossier.unused_needs:
        unused = "\n".join(
            f"[{u.need_id}] demand {u.demand_score:.2f} | KSEC {u.ksec_category} | "
            f"ผู้ขอ: {', '.join(u.stakeholder_types) or '-'} | เหตุที่ไม่ได้ใช้: {u.exclusion}\n"
            f"  {u.statement_th}"
            for u in dossier.unused_needs
        )
    else:
        unused = "ไม่มี Need สำคัญที่ไม่ได้เป็น PLO"
    header = f"หลักสูตร: {dossier.program_context}\n" if dossier.program_context else ""
    user = (
        f"{header}PLO ทั้งหมด {len(dossier.items)} ข้อ:\n\n"
        + "\n\n".join(blocks)
        + f"\n\n{facts}\n\nNeed สำคัญที่ไม่ได้เป็น PLO:\n{unused}"
    )
    return [
        {"role": "system", "content": _SYSTEM_TH},
        {"role": "user", "content": user},
    ]


def build_review_observation(tool: str, payload: Mapping[str, Any]) -> str:
    """A tool result, as the next user turn."""
    return f"ผลจาก {tool}:\n{json.dumps(payload, ensure_ascii=False)}"


def build_review_refusal(reason_th: str) -> str:
    """A refused tool call, as the next user turn."""
    return f"ปฏิเสธ: {reason_th}"
```

Note `"E|C"` comes from `_ksec_label(("E","C"))`.

- [ ] **Step 4: Write the failing agent tests** — `tests/unit/test_plo_review_agent.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from curriculum_agent.config import settings
from curriculum_agent.models import BloomHistogram, BloomLevel, KSECCategory, KsecCoverage, Need, UnusedNeedFinding
from curriculum_agent.prompts.plo_review import ReviewItem
from curriculum_agent.stages import plo_review_agent as agent
from curriculum_agent.stages.plo_review_facts import ReviewDossier

_ITEM = ReviewItem(
    plo_id="PLO1",
    is_optional=False,
    statement_th="วิเคราะห์ระบบงานเพื่อเสนอแนวทาง",
    action_verb_th="วิเคราะห์",
    bloom_level="analyze",
    current_ksec=("S",),
    need_statements_th=("ต้องการบัณฑิตที่วิเคราะห์ระบบงานได้",),
)
_UNUSED = UnusedNeedFinding(
    need_id="u1", statement_th="ต้องการบัณฑิตที่ล่ามได้", demand_score=0.4,
    ksec_category="S", stakeholder_types=["employer"], exclusion="lost_on_demand",
)
_DOSSIER = ReviewDossier(
    program_context=None, degree_level="bachelor", items=(_ITEM,),
    ksec_coverage=KsecCoverage(counts={"K": 0, "S": 1, "E": 0, "C": 0}),
    bloom_histogram=BloomHistogram(counts={"analyze": 1}, degree_level="bachelor"),
    core_count=1, unused_needs=(_UNUSED,),
)
_U1 = Need(
    need_id="u1", program_id="p", statement_th="ต้องการบัณฑิตที่ล่ามได้ในการประชุมธุรกิจ",
    rationale_th="ทักษะล่ามสามข้อเป็นงานเดียวกัน", ksec_category=KSECCategory.S,
    bloom_level=BloomLevel.APPLY, member_skill_ids=["s1", "s2"], source_evidence_ids=["e1"],
    stakeholder_coverage={"employer": 2}, freq=2, demand_score=0.4,
)


def _tool(tool: str, arg: str) -> agent.ReviewStep:
    return agent.ReviewStep(reasoning_th="ตรวจ", action={"kind": "call_tool", "tool": tool, "arg": arg})


def _finish(**kw: Any) -> agent.ReviewStep:
    return agent.ReviewStep(reasoning_th="สรุป", action={"kind": "finish", "summary_th": "ดี", **kw})


class _Script:
    """A fake model: answers each step from a list, recording what it was sent."""

    def __init__(self, steps: list[Any]) -> None:
        self.steps = list(steps)
        self.sent: list[list[dict[str, Any]]] = []
        self.kwargs: list[dict[str, Any]] = []

    async def __call__(self, response_model: type, messages: list[dict[str, Any]], **kw: Any) -> Any:
        self.sent.append([dict(m) for m in messages])
        self.kwargs.append(kw)
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch):
    def install(steps: list[Any]) -> _Script:
        fake = _Script(steps)
        monkeypatch.setattr(agent, "complete_plo_review", fake)
        return fake

    return install


async def test_a_finish_on_the_first_step_is_the_answer(script) -> None:
    fake = script([_finish()])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert out.reason is None and out.finish is not None and out.tool_calls == []
    assert fake.kwargs[0]["reasoning_max_tokens"] == 1024


async def test_tool_results_go_back_as_the_next_user_turn(script) -> None:
    fake = script([_tool("check_verbs", "PLO1"), _finish()])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert [c.model_dump() for c in out.tool_calls] == [{"tool": "check_verbs", "arg": "PLO1"}]
    last = fake.sent[1][-1]
    assert last["role"] == "user" and "opens_with_declared_verb" in last["content"]


async def test_the_fifth_tool_call_is_refused(script) -> None:
    fake = script([_tool("bloom_lookup", f"v{i}") for i in range(5)] + [_finish()])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert len(out.tool_calls) == agent.MAX_TOOL_CALLS == 4
    assert "ปฏิเสธ" in fake.sent[5][-1]["content"]
    assert out.finish is not None


async def test_a_refused_argument_still_counts_toward_the_budget(script) -> None:
    fake = script([_tool("need_detail", "not-unused"), _tool("check_verbs", "PLO9"), _finish()])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert len(out.tool_calls) == 2
    assert "ปฏิเสธ" in fake.sent[1][-1]["content"] and "ปฏิเสธ" in fake.sent[2][-1]["content"]


async def test_need_detail_gives_the_explanation_and_counts_never_evidence(script) -> None:
    fake = script([_tool("need_detail", "u1"), _finish()])
    await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    content = fake.sent[1][-1]["content"]
    assert "ทักษะล่ามสามข้อเป็นงานเดียวกัน" in content and '"member_count": 2' in content
    assert "e1" not in content and "s1" not in content


async def test_six_steps_without_a_finish_is_a_failure(script) -> None:
    script([_tool("bloom_lookup", f"v{i}") for i in range(6)])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert out.finish is None and out.reason == "failed"


async def test_a_malformed_or_failing_step_is_a_failure(script) -> None:
    script([ValueError("schema")])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert out.finish is None and out.reason == "failed"


async def test_the_run_timeout_is_reported_as_timeout(script, monkeypatch) -> None:
    monkeypatch.setattr(settings, "plo_review_timeout_seconds", 0.01)

    async def slow(*_a: Any, **_k: Any) -> Any:
        await asyncio.sleep(1)

    monkeypatch.setattr(agent, "complete_plo_review", slow)
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert out.finish is None and out.reason == "timeout"


def test_check_verbs_reports_the_opening_and_the_declared_verbs() -> None:
    ok, payload = agent.run_review_tool(_DOSSIER, {}, agent.ReviewToolName.CHECK_VERBS, "PLO1")
    assert ok and payload["opens_with_declared_verb"] is True
    assert payload["too_many_verbs"] is False
    assert "analyze" in payload["levels"]["วิเคราะห์"]


def test_bloom_lookup_answers_an_unknown_verb_without_refusing() -> None:
    ok, payload = agent.run_review_tool(_DOSSIER, {}, agent.ReviewToolName.BLOOM_LOOKUP, "ฟฟฟ")
    assert ok and payload == {"verb_th": "ฟฟฟ", "recognized": False, "levels": []}
```

(`settings.plo_review_timeout_seconds` is an `int` field; if pydantic rejects assigning `0.01` via `monkeypatch.setattr`, use `0` and keep the `sleep(1)` — `asyncio.timeout(0)` expires at the first await.)

- [ ] **Step 5: Run to verify they fail**

Run: `uv run pytest tests/unit/test_plo_review_agent.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.stages.plo_review_agent'`

- [ ] **Step 6: Create `src/curriculum_agent/stages/plo_review_agent.py`**

```python
"""The PLO QA agent: a small structured action loop over the finished set.

Stage 06 (spec 2026-10-12). The same shape as `smart_agent` and for the same
reasons — instructor JSON mode, one step object with a discriminated action, no
native tool-calling — but smaller on purpose: three tools, four calls, six steps,
and no tool that reaches evidence. The agency is in choosing which suspicion to
check, not in seeing more; a reviewer that reads the upstream detail anchors on
it instead of judging the set as written.

Nothing here decides what is stored. `plo_review.accept_review` judges the
answer entry by entry and computes every number in code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Any, Literal

from instructor.core.exceptions import IncompleteOutputException
from loguru import logger
from pydantic import BaseModel, Field
from tenacity import AsyncRetrying, retry_if_not_exception_type, stop_after_attempt

from curriculum_agent.config import settings
from curriculum_agent.llm import complete_plo_review
from curriculum_agent.models import Need, ReviewToolCall
from curriculum_agent.prompts.plo_review import (
    build_plo_review_prompt,
    build_review_observation,
    build_review_refusal,
)
from curriculum_agent.stages.bloom_verbs import levels_for_verb, scan_statement_verbs
from curriculum_agent.stages.plo_review_facts import ReviewDossier
from curriculum_agent.stages.smart_rules import declares_too_many_verbs, strip_outcome_prefix

MAX_TOOL_CALLS = 4
MAX_STEPS = 6
# A Finish carries every section in Thai, which JSON escapes per character.
_MAX_STEP_TOKENS = 8192
# Bounded on every step. Unbounded, this slot produced nothing on the tourism set
# 3/3 (one truncation at 8192 tokens, two 180s timeouts); bounded at 1024 it
# answered 3/3 in 45-57s (spec 2026-10-04, "Measured").
_MAX_REASONING_TOKENS = 1024
_STEP_ATTEMPTS = 2


class ReviewToolName(StrEnum):
    BLOOM_LOOKUP = "bloom_lookup"
    CHECK_VERBS = "check_verbs"
    NEED_DETAIL = "need_detail"


# Loose on purpose (plain strings, defaults everywhere): a pydantic failure fails
# the whole step and loses every good entry with the bad one. `accept_review`
# judges entry by entry.
class Redundancy(BaseModel):
    plo_ids: list[str] = Field(default_factory=list)
    reason_th: str = ""
    suggestion_th: str = ""


class KsecVerdict(BaseModel):
    plo_id: str = ""
    suggested: list[str] = Field(default_factory=list)
    reason_th: str = ""


class BloomVerdict(BaseModel):
    plo_id: str = ""
    suggested_level: str | None = None
    reason_th: str = ""


class UnusedVerdict(BaseModel):
    need_id: str = ""
    verdict: str = ""
    reason_th: str = ""


class ReviewCallTool(BaseModel):
    kind: Literal["call_tool"]
    tool: ReviewToolName
    arg: str = Field(min_length=1, max_length=120)


class ReviewFinish(BaseModel):
    """The answer. It has no field for any number — those are code's."""

    kind: Literal["finish"]
    redundancies: list[Redundancy] = Field(default_factory=list)
    ksec: list[KsecVerdict] = Field(default_factory=list)
    bloom: list[BloomVerdict] = Field(default_factory=list)
    bloom_distribution_th: str = ""
    coverage_th: str = ""
    unused_needs: list[UnusedVerdict] = Field(default_factory=list)
    summary_th: str = ""


class ReviewStep(BaseModel):
    """`reasoning_th` first: field order is generation order."""

    reasoning_th: str = ""
    action: Annotated[ReviewCallTool | ReviewFinish, Field(discriminator="kind")]


@dataclass
class AgentOutcome:
    finish: ReviewFinish | None
    reason: str | None  # None when finished; "failed" | "timeout"
    tool_calls: list[ReviewToolCall] = field(default_factory=list)


def run_review_tool(
    dossier: ReviewDossier,
    unused_needs: Mapping[str, Need],
    tool: ReviewToolName,
    arg: str,
) -> tuple[bool, dict[str, Any]]:
    """One tool, pure. (False, {"error_th": ...}) is a refusal the model reads."""
    arg = arg.strip()
    if tool is ReviewToolName.BLOOM_LOOKUP:
        levels = [lv.value for lv in levels_for_verb(arg)]
        return True, {"verb_th": arg, "recognized": bool(levels), "levels": levels}
    if tool is ReviewToolName.CHECK_VERBS:
        item = next((i for i in dossier.items if i.plo_id == arg), None)
        if item is None:
            return False, {"error_th": f"ไม่มี PLO รหัส {arg} ในชุดนี้"}
        declared = scan_statement_verbs(item.action_verb_th)
        return True, {
            "plo_id": item.plo_id,
            "action_verb_th": item.action_verb_th,
            "opens_with_declared_verb": bool(item.action_verb_th)
            and strip_outcome_prefix(item.statement_th).startswith(item.action_verb_th),
            "declared_verbs": declared,
            "too_many_verbs": declares_too_many_verbs(item.action_verb_th),
            "levels": {v: [lv.value for lv in levels_for_verb(v)] for v in declared},
        }
    need = unused_needs.get(arg)
    if need is None:
        return False, {"error_th": "need_detail ใช้ได้กับ Need ในรายการที่ไม่ได้เป็น PLO เท่านั้น"}
    return True, {
        "need_id": need.need_id,
        "rationale_th": need.rationale_th,
        "rationale_note_th": "คำอธิบายของโมเดลที่เขียน Need นี้ ไม่ใช่หลักฐาน",
        "member_count": len(need.member_skill_ids),
        "stakeholder_coverage": {str(k): v for k, v in need.stakeholder_coverage.items()},
    }


def _step_retrying() -> AsyncRetrying:
    # A schema miss is worth one re-ask; a truncation is not (same as smart_agent).
    return AsyncRetrying(
        stop=stop_after_attempt(_STEP_ATTEMPTS),
        retry=retry_if_not_exception_type(IncompleteOutputException),
    )


async def _ask_step(messages: list[dict[str, Any]]) -> ReviewStep:
    return await complete_plo_review(
        ReviewStep,
        messages,
        max_retries=_step_retrying(),
        temperature=0,
        max_tokens=_MAX_STEP_TOKENS,
        reasoning_max_tokens=_MAX_REASONING_TOKENS,
    )


async def run_review_agent(
    dossier: ReviewDossier, unused_needs: Mapping[str, Need]
) -> AgentOutcome:
    """Run the loop. Never raises: every failure is an outcome with a reason."""
    messages: list[dict[str, Any]] = build_plo_review_prompt(dossier)
    calls: list[ReviewToolCall] = []
    try:
        async with asyncio.timeout(settings.plo_review_timeout_seconds):
            for step_no in range(1, MAX_STEPS + 1):
                step = await _ask_step(messages)
                messages.append({"role": "assistant", "content": step.model_dump_json()})
                action = step.action
                if isinstance(action, ReviewFinish):
                    logger.info(f"plo_review agent: finish at step {step_no}, {len(calls)} tool call(s)")
                    return AgentOutcome(action, None, calls)
                if step_no == MAX_STEPS:
                    break
                last_note = " — รอบถัดไปเป็นรอบสุดท้าย ต้องสรุปด้วย finish" if step_no == MAX_STEPS - 1 else ""
                if len(calls) >= MAX_TOOL_CALLS:
                    messages.append(
                        {
                            "role": "user",
                            "content": build_review_refusal(
                                f"ใช้เครื่องมือครบ {MAX_TOOL_CALLS} ครั้งแล้ว — สรุปผลด้วย finish"
                            ),
                        }
                    )
                    continue
                calls.append(ReviewToolCall(tool=action.tool.value, arg=action.arg))
                ok, payload = run_review_tool(dossier, unused_needs, action.tool, action.arg)
                content = (
                    build_review_observation(action.tool.value, payload)
                    if ok
                    else build_review_refusal(payload["error_th"])
                )
                messages.append({"role": "user", "content": content + last_note})
    except TimeoutError:
        logger.warning(
            f"plo_review agent: timed out after {settings.plo_review_timeout_seconds}s "
            f"({len(calls)} tool call(s)) — code facts only"
        )
        return AgentOutcome(None, "timeout", calls)
    except Exception as exc:  # malformed step, truncation, provider error
        logger.warning(f"plo_review agent: step failed ({exc!r}) — code facts only")
        return AgentOutcome(None, "failed", calls)
    logger.warning(f"plo_review agent: {MAX_STEPS} steps without a finish — code facts only")
    return AgentOutcome(None, "failed", calls)
```

Note on the refusal path: a refused call (`ok=False`) is still appended to `calls` before `run_review_tool` runs — that is what makes it count toward the budget (Review Focus 4).

- [ ] **Step 7: Raise the timeout** — `src/curriculum_agent/config.py:325`: `plo_review_timeout_seconds: int = 300`; update the comment above it (if any) to say the whole agent run, not one call.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/unit/test_plo_review_prompt.py tests/unit/test_plo_review_agent.py -q`
Expected: PASS.

- [ ] **Step 9: Lint, type-check, commit**

```bash
uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/
git add src/curriculum_agent/prompts/plo_review.py src/curriculum_agent/stages/plo_review_agent.py src/curriculum_agent/config.py tests/unit/test_plo_review_prompt.py tests/unit/test_plo_review_agent.py
git commit -m "feat(plo_review): the QA agent loop — three tools, four calls, no evidence"
```

---

### Task 3: Orchestration — the review is the agent's answer or the code facts

**Files:**
- Modify: `src/curriculum_agent/stages/plo_review.py` (rewrite `accept_review`, `_call`→`_review`, `fresh_review`, `review_plo_set`, `run`; delete `ReviewAnswer`/`_Redundancy`/`_KsecVerdict`/`_BloomVerdict`/`_items`/`_ATTEMPTS`/`_MAX_TOKENS`/`_MAX_REASONING_TOKENS`/`is_empty`)
- Test: `tests/unit/test_plo_review_accept.py` (rewrite to the new answer types), `tests/unit/test_plo_review_run.py` (rewrite)

**Interfaces:**
- Consumes: Task 1 facts (`build_dossier`, `need_demands`, `plo_fingerprint`, `is_stale`), Task 2 (`run_review_agent`, `AgentOutcome`, `ReviewFinish`, `Redundancy`, `KsecVerdict`, `BloomVerdict`, `UnusedVerdict`).
- Produces:
  - `accept_review(answer: ReviewFinish, plos, needs_by_id, dossier: ReviewDossier, *, program_id: str, fingerprint: str, model: str, created_at: datetime, tool_calls: Sequence[ReviewToolCall] = ()) -> tuple[PLOSetReview, Counter[str]]`
  - `code_only_review(dossier, *, program_id, fingerprint, created_at, reason: str, tool_calls=()) -> PLOSetReview`
  - `has_agent_findings(review: PLOSetReview) -> bool`
  - `async fresh_review(program_id: str, plos: Sequence[PLO]) -> PLOSetReview` — never `None`; raises `ReviewAlreadyRunning`, or a database error.
  - `async review_plo_set(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None` — reuses a current stored review; never raises.
  - `async run(state: AgentState) -> AgentState` — graph node; sets `state["plo_review"]` and `state["current_stage"] = "plo_review"`.

- [ ] **Step 1: Rewrite `tests/unit/test_plo_review_accept.py`** with the fixtures it has today (`_need`, `_plo`, `NEEDS`, `PLOS`) and these tests (keep the existing redundancy/KSEC/Bloom cases, rewritten to `Redundancy`/`KsecVerdict`/`BloomVerdict` from `plo_review_agent` and `ReviewFinish(kind="finish", ...)`):

```python
from curriculum_agent.models import ReviewToolCall
from curriculum_agent.stages.plo_review import accept_review, code_only_review, has_agent_findings
from curriculum_agent.stages.plo_review_agent import (
    BloomVerdict, KsecVerdict, Redundancy, ReviewFinish, UnusedVerdict,
)
from curriculum_agent.stages.plo_review_facts import build_dossier

UNUSED = _need("u1", KSECCategory.S)  # cited by nothing in PLOS
DOSSIER = build_dossier(PLOS, [*NEEDS.values(), UNUSED], program_context=None, degree_level="bachelor")


def _accept(answer: ReviewFinish, calls=()):
    return accept_review(
        answer, PLOS, NEEDS, DOSSIER, program_id="p", fingerprint="f",
        model="m", created_at=_NOW, tool_calls=calls,
    )


def test_code_facts_come_from_the_dossier_not_the_answer() -> None:
    review, _ = _accept(ReviewFinish(kind="finish", summary_th="ok", coverage_th=" ขาด K "))
    assert review.ksec_coverage == DOSSIER.ksec_coverage
    assert review.bloom_histogram == DOSSIER.bloom_histogram
    assert review.coverage_th == "ขาด K"
    assert review.reviewed_by == "agent" and review.code_only_reason is None


def test_unused_verdicts_merge_onto_the_selected_needs_only() -> None:
    answer = ReviewFinish(
        kind="finish",
        summary_th="ok",
        unused_needs=[
            UnusedVerdict(need_id="u1", verdict="Consider", reason_th="นายจ้างขอ"),
            UnusedVerdict(need_id="u1", verdict="ok_to_leave", reason_th="ซ้ำ"),
            UnusedVerdict(need_id="n1", verdict="consider", reason_th="ไม่อยู่ในรายการ"),
        ],
    )
    review, drops = _accept(answer)
    [u] = review.unused_needs
    assert (u.need_id, u.verdict, u.reason_th) == ("u1", "consider", "นายจ้างขอ")
    assert u.demand_score == UNUSED.demand_score and u.exclusion == "lost_on_demand"
    assert drops["unused"] == 2


def test_an_unknown_verdict_word_keeps_the_entry_without_a_verdict() -> None:
    answer = ReviewFinish(
        kind="finish", summary_th="ok",
        unused_needs=[UnusedVerdict(need_id="u1", verdict="maybe", reason_th="ไม่แน่ใจ")],
    )
    [u] = _accept(answer)[0].unused_needs
    assert u.verdict is None and u.reason_th == "ไม่แน่ใจ"


def test_the_tool_calls_are_recorded() -> None:
    calls = [ReviewToolCall(tool="check_verbs", arg="PLO1")]
    review, _ = _accept(ReviewFinish(kind="finish", summary_th="ok"), calls)
    assert review.tool_calls == calls


def test_a_code_only_review_has_facts_and_no_findings() -> None:
    review = code_only_review(
        DOSSIER, program_id="p", fingerprint="f", created_at=_NOW, reason="timeout"
    )
    assert review.reviewed_by == "code_only" and review.code_only_reason == "timeout"
    assert review.model == "" and review.summary_th == ""
    assert review.ksec_coverage == DOSSIER.ksec_coverage
    assert [u.need_id for u in review.unused_needs] == ["u1"]
    assert all(u.verdict is None for u in review.unused_needs)
    assert not has_agent_findings(review)


def test_an_answer_with_nothing_has_no_agent_findings() -> None:
    review, _ = _accept(ReviewFinish(kind="finish"))
    assert not has_agent_findings(review)
```

- [ ] **Step 2: Rewrite `tests/unit/test_plo_review_run.py`.** Keep its `_META`, `_NEED`, `_PLOS`, `_MemoryRepo` and `live` fixture shape, but patch `pr.run_review_agent` instead of `complete_plo_review`:

```python
from curriculum_agent.models import ReviewToolCall
from curriculum_agent.stages.plo_review_agent import AgentOutcome, Redundancy, ReviewFinish

_FINISH = ReviewFinish(
    kind="finish",
    redundancies=[Redundancy(plo_ids=["PLO1", "PLO2"], reason_th="ซ้ำ", suggestion_th="รวม")],
    summary_th="สองข้อซ้ำกัน",
)


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    _MemoryRepo.rows = {}
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    monkeypatch.setattr(pr, "PLOReviewRepository", _MemoryRepo)
    monkeypatch.setattr(pr, "ProgramRepository", lambda: AsyncMock(get=AsyncMock(return_value=_META)))
    monkeypatch.setattr(
        pr, "NeedRepository", lambda: AsyncMock(list_by_program=AsyncMock(return_value=[_NEED]))
    )
    agent_run = AsyncMock(
        return_value=AgentOutcome(_FINISH, None, [ReviewToolCall(tool="check_verbs", arg="PLO1")])
    )
    monkeypatch.setattr(pr, "run_review_agent", agent_run)
    return agent_run


async def test_a_fresh_review_is_the_agents_answer_judged_and_stored(live: AsyncMock) -> None:
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "agent" and review.redundancies[0].plo_ids == ["PLO1", "PLO2"]
    assert review.tool_calls[0].tool == "check_verbs"
    assert _MemoryRepo.rows["p"] == review


async def test_the_agent_is_handed_the_dossier_and_only_the_unused_needs(live: AsyncMock) -> None:
    await pr.fresh_review("p", _PLOS)
    dossier, unused = live.await_args.args
    assert [i.plo_id for i in dossier.items] == ["PLO1", "PLO2"]
    assert dict(unused) == {}  # _NEED is cited by both PLOs


@pytest.mark.parametrize("reason", ["failed", "timeout"])
async def test_an_agent_failure_stores_the_code_facts(live: AsyncMock, reason: str) -> None:
    live.return_value = AgentOutcome(None, reason, [])
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "code_only" and review.code_only_reason == reason
    assert review.redundancies == [] and review.summary_th == ""
    assert _MemoryRepo.rows["p"] == review


async def test_an_answer_the_judge_empties_is_stored_as_code_only(live: AsyncMock) -> None:
    live.return_value = AgentOutcome(ReviewFinish(kind="finish"), None, [])
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "code_only" and review.code_only_reason == "failed"


async def test_the_switched_off_slot_never_runs_the_agent(live: AsyncMock, monkeypatch) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "")
    review = await pr.fresh_review("p", _PLOS)
    live.assert_not_awaited()
    assert review.reviewed_by == "code_only" and review.code_only_reason == "disabled"


async def test_an_unchanged_set_reuses_the_stored_review(live: AsyncMock) -> None:
    first = await pr.review_plo_set("p", _PLOS)
    second = await pr.review_plo_set("p", _PLOS)
    assert first == second and live.await_count == 1


async def test_a_storage_failure_raises_from_fresh_review(live: AsyncMock, monkeypatch) -> None:
    async def boom(self, review) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(_MemoryRepo, "upsert", boom)
    with pytest.raises(RuntimeError):
        await pr.fresh_review("p", _PLOS)


async def test_the_graph_node_keeps_going_when_the_needs_fail_to_load(live: AsyncMock, monkeypatch) -> None:
    monkeypatch.setattr(
        pr, "NeedRepository",
        lambda: AsyncMock(list_by_program=AsyncMock(side_effect=RuntimeError("db"))),
    )
    state = await pr.run({"program_id": "p", "plos": [p.model_dump(mode="json") for p in _PLOS]})
    assert state["plo_review"] is None and state["current_stage"] == "plo_review"


async def test_run_puts_the_review_on_the_state(live: AsyncMock) -> None:
    state = await pr.run({"program_id": "p", "plos": [p.model_dump(mode="json") for p in _PLOS]})
    assert state["plo_review"]["summary_th"] == "สองข้อซ้ำกัน"
    assert state["current_stage"] == "plo_review"


async def test_a_second_review_while_one_is_in_flight_is_refused(live: AsyncMock) -> None:
    pr._REVIEW_IN_FLIGHT.add("p")
    try:
        with pytest.raises(pr.ReviewAlreadyRunning):
            await pr.fresh_review("p", _PLOS)
    finally:
        pr._REVIEW_IN_FLIGHT.discard("p")
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/unit/test_plo_review_accept.py tests/unit/test_plo_review_run.py -q`
Expected: FAIL (`ImportError` on `code_only_review` / `run_review_agent`).

- [ ] **Step 4: Rewrite the orchestration in `src/curriculum_agent/stages/plo_review.py`.** Update the module docstring to describe stage 06 (an agent; runs after the report; code facts stored on every path). Keep `MAX_REDUNDANCY_GROUP`, `_bloom_level`, `_REVIEW_IN_FLIGHT`, `ReviewAlreadyRunning`. Replace the rest with:

```python
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
    # --- redundancies, ksec, bloom: the existing loops, unchanged, reading
    # answer.redundancies / answer.ksec / answer.bloom and using normalize_ksec ---
    ...  # move the three existing loops here verbatim

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
        v = verdicts.get(u.need_id)
        if v is None:
            unused.append(u)
            continue
        word = v.verdict.strip().lower()
        unused.append(
            u.model_copy(
                update={
                    "verdict": word if word in _VERDICTS else None,
                    "reason_th": v.reason_th.strip(),
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
            dossier, program_id=program_id, fingerprint=fingerprint, created_at=now, reason="disabled"
        )
    unused = {u.need_id: needs_by_id[u.need_id] for u in dossier.unused_needs}
    outcome = await run_review_agent(dossier, unused)
    if outcome.finish is None:
        return code_only_review(
            dossier,
            program_id=program_id,
            fingerprint=fingerprint,
            created_at=now,
            reason=outcome.reason or "failed",
            tool_calls=outcome.tool_calls,
        )
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
        f"plo_review: kept {len(review.redundancies)} redundancy / {len(review.ksec)} ksec / "
        f"{len(review.bloom)} bloom / {sum(1 for u in review.unused_needs if u.verdict)} unused "
        f"verdict(s), dropped {dict(drops) or 'nothing'}, {len(review.tool_calls)} tool call(s)"
    )
    if not has_agent_findings(review):
        logger.warning(f"plo_review: the answer for {program_id} held nothing usable — code facts only")
        return code_only_review(
            dossier,
            program_id=program_id,
            fingerprint=fingerprint,
            created_at=now,
            reason="failed",
            tool_calls=outcome.tool_calls,
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


async def review_plo_set(program_id: str, plos: Sequence[PLO]) -> PLOSetReview | None:
    """The graph's review: the stored one if the set is unchanged, else a fresh
    one. Never raises — an advisory step must not fail the session."""
    try:
        stored = await PLOReviewRepository().get(program_id)
        needs = await NeedRepository().list_by_program(program_id)
    except Exception as exc:
        logger.warning(f"plo_review: could not read inputs for {program_id}: {exc!r}")
        return None
    if stored is not None and not is_stale(stored, plos, need_demands(needs)):
        return stored
    try:
        return await fresh_review(program_id, plos)
    except ReviewAlreadyRunning:
        logger.info(f"plo_review: a review of {program_id} is already running — keeping the stored one")
        return stored
    except Exception as exc:
        logger.warning(f"plo_review: review of {program_id} failed, keeping the stored one: {exc!r}")
        return stored


async def run(state: AgentState) -> AgentState:
    """Graph entry, stage 06: after the report, review the set it persisted."""
    program_id = state.get("program_id", "unknown")
    plos = [PLO.model_validate(d) for d in state.get("plos", [])]
    review = await review_plo_set(program_id, plos) if plos else None
    state["plo_review"] = review.model_dump(mode="json") if review is not None else None
    state["current_stage"] = "plo_review"
    return state
```

Imports to add: `ReviewToolCall`, `UnusedNeedFinding` from models; `AgentOutcome` is not needed here; `ReviewFinish`, `UnusedVerdict`, `run_review_agent` from `plo_review_agent`; `ReviewDossier`, `build_dossier` from `plo_review_facts`. Remove `complete_plo_review` and `build_plo_review_prompt` imports. The three existing loops in `accept_review` keep their bodies; they now build `RedundancyFinding`/`KsecFinding`/`BloomFinding` from `Redundancy`/`KsecVerdict`/`BloomVerdict` entries (same field names).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_plo_review_accept.py tests/unit/test_plo_review_run.py tests/unit/test_plo_review_facts.py tests/unit/test_plo_review_agent.py -q`
Expected: PASS.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/
git add src/curriculum_agent/stages/plo_review.py tests/unit/test_plo_review_accept.py tests/unit/test_plo_review_run.py
git commit -m "feat(plo_review): store the agent's judged answer, or the code facts when it cannot answer"
```

---

### Task 4: Stage 06 in the graph, on the rail, and out of the report

**Files:**
- Modify: `src/curriculum_agent/graph.py:105-262` (nodes, edges, `DESIGNER_STAGES`, `REVIEW_NODE_STAGE`, `stage_reached`)
- Modify: `src/curriculum_agent/data/repositories.py:109-160` (`ProgramRepository.list_all`)
- Modify: `src/curriculum_agent/stages/plo_report.py` (drop the review)
- Modify: `src/curriculum_agent/models.py:591-598` (`StageCheckpoint.stage` Literal gains `"plo_review"`)
- Test: `tests/unit/test_stage_reached.py`, `tests/unit/test_session_stage_mapping.py`, `tests/unit/test_plo_report_graph.py`, `tests/unit/test_plo_review_wiring.py` (graph/report parts), `tests/unit/test_program_repository.py`, `tests/unit/test_plo_report.py`

**Interfaces:**
- Consumes: `plo_review.run` (Task 3), `plo_review_facts.plo_fingerprint`, `need_demands` (Task 1).
- Produces: `stage_reached(*, has_evidence, has_skills, has_needs, has_plos, has_current_review: bool = False) -> str`; `DESIGNER_STAGES` ending `"plo_report", "plo_review"`; graph `review_plos_node → plo_report → plo_review → END`; report dict without `review`/`review_stale`.

- [ ] **Step 1: Write the failing tests.**

In `tests/unit/test_stage_reached.py` add:

```python
def test_a_current_review_is_the_last_stage():
    assert (
        stage_reached(
            has_evidence=True, has_skills=True, has_needs=True, has_plos=True,
            has_current_review=True,
        )
        == "plo_review"
    )


def test_without_a_current_review_plos_are_still_plo_synthesis():
    assert (
        stage_reached(has_evidence=True, has_skills=True, has_needs=True, has_plos=True)
        == "plo_synthesis"
    )
```

and extend `test_every_outcome_is_a_designer_stage`'s product with `has_current_review` in `(False, True)`.

Replace `tests/unit/test_plo_report_graph.py`'s `test_review_plo_report_*` tests (the node is removed) and add to it:

```python
from curriculum_agent.graph import DESIGNER_STAGES, REVIEW_NODE_STAGE, build_graph


def _edges() -> set[tuple[str, str]]:
    g = build_graph().get_graph()
    return {(e.source, e.target) for e in g.edges}


def test_report_then_qa_then_end_with_no_checkpoint_after_the_plos():
    edges = _edges()
    assert ("review_plos_node", "plo_report") in edges
    assert ("plo_report", "plo_review") in edges
    assert ("plo_review", "__end__") in edges
    assert not any("review_plo_report" in (a, b) for a, b in edges)


def test_qa_is_the_sixth_designer_stage_and_no_checkpoint_maps_to_it():
    assert DESIGNER_STAGES[-2:] == ("plo_report", "plo_review")
    assert "review_plo_report" not in REVIEW_NODE_STAGE
```

(Keep `test_graph_wires_plo_report_and_detaches_ylo` if it still holds; adjust only the parts naming the removed node.)

In `tests/unit/test_plo_review_wiring.py`, delete the tests about the review sitting before the report, the report carrying a review, and the report route running the review (`test_plo_review_sits_between_*`, `test_plo_review_is_not_a_designer_stage_*`, `test_the_report_carries_the_review_*`, `test_a_report_without_a_review_says_so`, `test_report_route_runs_the_review_first`, `test_report_route_re_reads_the_plos_after_the_review_call`, `test_report_route_review_enabled_true_when_the_slot_is_on`); Task 5 adds their replacements on the route side.

In `tests/unit/test_plo_report.py` (it already has `_need`, `_plo` and `pr = plo_report`) add:

```python
async def test_the_report_no_longer_carries_a_review(monkeypatch: pytest.MonkeyPatch):
    """The QA review is stage 06 and runs after the report; the report neither
    reads nor returns one, even when an old one is on the state."""
    monkeypatch.setattr(pr.NeedRepository, "list_by_program", AsyncMock(return_value=[_need("N1")]))
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", AsyncMock())
    state = await pr.run(
        {
            "program_id": "cs-test",
            "plos": [_plo("PLO1", ["N1"]).model_dump(mode="json")],
            "plo_review": {"summary_th": "เก่า"},
        }
    )
    assert "review" not in state["report"]
    assert "review_stale" not in state["report"]
```

In `tests/unit/test_program_repository.py` add a `list_all` test (follow the file's existing mocking of `AsyncSessionLocal`/`_programs_with_rows`) in which program `p` has PLOs, Needs and a stored review whose fingerprint matches → `current_stage == "plo_review"`; a mismatched fingerprint → `"plo_synthesis"`; a review read that raises → `"plo_synthesis"` and `list_all` still returns.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_stage_reached.py tests/unit/test_plo_report_graph.py tests/unit/test_session_stage_mapping.py tests/unit/test_plo_review_wiring.py tests/unit/test_program_repository.py -q`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Change the graph** — `src/curriculum_agent/graph.py`:
  - Delete `review_plo_report` (the function) and its node.
  - Rename `stage_4b_plo_review` → `stage_6_plo_review` (body unchanged).
  - Edges: replace

    ```python
    g.add_edge("review_plos_node", "plo_review")
    g.add_edge("plo_review", "plo_report")
    g.add_edge("plo_report", "review_plo_report")
    g.add_edge("review_plo_report", END)
    ```
    with
    ```python
    # No checkpoint after the PLOs (immutable rule 7, waived for this segment by
    # the designer, 2026-10-12): the report re-persists the approved set and the
    # QA agent only advises, so a checkpoint between or after them gates nothing.
    g.add_edge("review_plos_node", "plo_report")
    g.add_edge("plo_report", "plo_review")
    g.add_edge("plo_review", END)
    ```
  - `DESIGNER_STAGES` gains `"plo_review"` after `"plo_report"`.
  - `REVIEW_NODE_STAGE` drops `"review_plo_report": "plo_report"`.
  - `stage_reached` gains keyword `has_current_review: bool = False`; first line of the body `if has_current_review: return "plo_review"`. Rewrite its docstring paragraph about `plo_report` to: the report leaves no artifact of its own; the QA agent's review does, and only a review current for the stored set counts — a stale one means the set changed after it and the next thing to do is the report.

- [ ] **Step 4: Compute `has_current_review` in `list_all`** — `src/curriculum_agent/data/repositories.py`. Add a module-level helper

```python
async def _programs_with_a_current_review(program_ids: Iterable[str]) -> set[str]:
    """Programs whose stored QA review matches their current PLOs and Needs.

    A read or parse failure counts as "not current" for that program and is
    logged — the program list must never fail over advisory data.
    """
    from curriculum_agent.stages.plo_review_facts import is_stale, need_demands  # noqa: PLC0415

    current: set[str] = set()
    for pid in program_ids:
        try:
            review = await PLOReviewRepository().get(pid)
            if review is None:
                continue
            plos = await PLORepository().list_by_program(pid)
            needs = await NeedRepository().list_by_program(pid)
            if plos and not is_stale(review, plos, need_demands(needs)):
                current.add(pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"list_all: could not judge the QA review of {pid}: {exc!r}")
    return current
```

call it from `list_all` (after the `async with` block that reads the tables) as `current = await _programs_with_a_current_review(with_plos)` — only a program with PLOs can have a current review — and pass `has_current_review=p.program_id in current` to `stage_reached`. If `logger` or `Iterable` are not yet imported in `repositories.py`, import them. Existing `list_all` tests that mock the session should patch `_programs_with_a_current_review` to return `set()` so they never reach a real database.

- [ ] **Step 5: Take the review out of the report** — `src/curriculum_agent/stages/plo_report.py`: delete the `review_dict`/`review` lines, the `"review"` and `"review_stale"` keys, and the `PLOSetReview`/`is_stale` imports. Update the docstring if it mentions the review. `models.StageCheckpoint.stage` gains `"plo_review"`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/unit/test_stage_reached.py tests/unit/test_plo_report_graph.py tests/unit/test_session_stage_mapping.py tests/unit/test_plo_review_wiring.py tests/unit/test_program_repository.py tests/unit/test_plo_report.py tests/unit/test_graph_hitl.py -q`
Expected: PASS.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/
git add src/curriculum_agent/graph.py src/curriculum_agent/data/repositories.py src/curriculum_agent/stages/plo_report.py src/curriculum_agent/models.py tests/unit/test_stage_reached.py tests/unit/test_plo_report_graph.py tests/unit/test_session_stage_mapping.py tests/unit/test_plo_review_wiring.py tests/unit/test_program_repository.py tests/unit/test_plo_report.py
git commit -m "feat(graph): the QA review is stage 06, after the report, with no checkpoint after the PLOs"
```

---

### Task 5: Routes — the report stops reviewing; the review runs even with the slot off

**Files:**
- Modify: `src/curriculum_agent/api/routes/plos.py:236-355` (`run_plo_report`, `PLOReportResponse`, `get_plo_review`, `run_plo_review`)
- Modify: `src/curriculum_agent/api/jobs.py:~60` (`JOB_KIND_LABEL_TH["plo_review"] = "ตรวจคุณภาพชุด PLO"`)
- Test: `tests/unit/test_plos_jobs.py`, `tests/unit/test_plo_review_wiring.py` (route parts)

**Interfaces:**
- Consumes: `plo_review.fresh_review(program_id, plos) -> PLOSetReview` (Task 3), `plo_review_facts.is_stale`, `need_demands` (Task 1).
- Produces: `PLOReportResponse` without `review`, `review_stale`, `review_enabled`; `POST /plos/review/run` → 202 always when PLOs exist (no 503); its job result `PLOReviewResponse{review, stale, review_enabled}`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_plos_jobs.py` (reuse its `env`, `jobs_store`, `spawned`, `_finish` helpers):

```python
def test_the_report_job_never_runs_the_review(env, jobs_store, spawned) -> None:
    job = _finish(client.post(f"{BASE}/report/run"), jobs_store, spawned)
    assert job.status == "succeeded"
    env.review_run.assert_not_awaited()
    for key in ("review", "review_stale", "review_enabled"):
        assert key not in job.result


def test_review_with_the_slot_off_is_still_a_job(env, jobs_store, spawned, monkeypatch) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "")
    r = client.post(f"{BASE}/review/run")
    assert r.status_code == 202
    job = _finish(r, jobs_store, spawned)
    assert job.status == "succeeded"
    env.fresh_review.assert_awaited_once()
    assert job.result["review_enabled"] is False
```

Delete or rewrite the tests this contradicts: `test_review_switched_off_is_a_synchronous_503`, `test_a_review_that_came_back_empty_fails_the_job` (`fresh_review` no longer returns `None` — replace with: `fresh_review` raising `RuntimeError("db")` fails the job with that text), the report-runs-review assertions near line 239-252, and `test_report_re_reads_the_plos_inside_the_job_after_the_review` (the re-read existed only because of the review call; drop it). In `env`, `fresh_review`'s return value stays `_review()`; give `_review()` a fingerprint and keep `stale` computed by the route. In `tests/unit/test_plo_review_wiring.py`, `test_review_run_503_when_switched_off` and `test_review_run_job_fails_when_the_review_failed` change the same way; `test_get_review_reports_staleness` now needs `NeedRepository.list_by_program` patched (the staleness check reads the Needs).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_plos_jobs.py tests/unit/test_plo_review_wiring.py -q`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Change the routes** — `src/curriculum_agent/api/routes/plos.py`:

`PLOReportResponse`: remove `review`, `review_stale`, `review_enabled` (and any import that becomes unused).

`run_plo_report`:

```python
@router.post("/report/run", response_model=JobInfo, status_code=202)
async def run_plo_report(program_id: str) -> JobInfo:
    """Assemble the report. Answers 202; the result (a `PLOReportResponse`)
    arrives through `GET /jobs`. The QA review is stage 06 and runs on its own
    (`POST /plos/review/run`), never from here."""
    from curriculum_agent.stages.plo_report import run  # noqa: PLC0415

    plos = await _repo.list_by_program(program_id)
    if not plos:
        raise HTTPException(
            status_code=422,
            detail="ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน",
        )
    state: AgentState = {
        "program_id": program_id,
        "plos": [p.model_dump(mode="json") for p in plos],
    }

    async def work() -> PLOReportResponse:
        result_state = await run(state)
        report = result_state["report"]
        return PLOReportResponse(
            plos=[PLO.model_validate(p) for p in report["plos"]],
            counts=report["counts"],
            needs_by_id={k: Need.model_validate(v) for k, v in report["needs_by_id"].items()},
            needs_not_synthesized=report["needs_not_synthesized"],
        )

    return await start_job_or_409(program_id, "plo_report", {}, work)
```

`get_plo_review`: after reading the review, load `needs = await NeedRepository().list_by_program(program_id)` inside the same `try`, and compute `stale=review is not None and is_stale(review, plos, need_demands(needs))`; import `is_stale`, `need_demands` from `curriculum_agent.stages.plo_review_facts`.

`run_plo_review`: delete the 503 block; update the docstring (a switched-off slot runs the code facts); the work becomes

```python
    async def work() -> PLOReviewResponse:
        try:
            review = await plo_review.fresh_review(program_id, plos)
        except plo_review.ReviewAlreadyRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # The agent can run for up to plo_review_timeout_seconds (300s); judge
        # staleness against whatever landed on this program meanwhile.
        plos_now = await _repo.list_by_program(program_id)
        needs_now = await NeedRepository().list_by_program(program_id)
        return PLOReviewResponse(
            review=review,
            stale=is_stale(review, plos_now, need_demands(needs_now)),
            review_enabled=bool(settings.plo_review_provider),
        )
```

`src/curriculum_agent/api/jobs.py`: `"plo_review": "ตรวจคุณภาพชุด PLO"`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest -q`
Expected: PASS, whole suite.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/ tests/ && uv run ruff format src/ tests/ && uv run mypy src/
git add src/curriculum_agent/api/routes/plos.py src/curriculum_agent/api/jobs.py tests/unit/test_plos_jobs.py tests/unit/test_plo_review_wiring.py
git commit -m "feat(api): the report stops running the review; the QA job runs with the slot off"
```

---

### Task 6: Frontend — the stage 06 page

**Files:**
- Create: `frontend/src/pages/PloReview.tsx`
- Modify: `frontend/src/constants/stages.ts` (sixth stage), `frontend/src/App.tsx` or wherever routes are declared (route `/plo-review`), `frontend/src/api/jobs.ts` (`JOB_PAGE.plo_review = { path: '/plo-review' }`), `frontend/src/pages/PloReport.tsx`, `frontend/src/pages/Pipeline.tsx`, `frontend/src/mock/handlers.ts`, `frontend/src/mock/db.ts` (and `scenarios.ts` if the mock keeps reviews there)
- Test: `npm run lint`, `npm run build` (no frontend test runner exists)

**Interfaces (API this page reads):**
- `GET /programs/{id}/plos/review` → `{ review: PLOSetReview | null, stale: boolean, review_enabled: boolean }` where `PLOSetReview` is:

```ts
interface PLOSetReview {
  program_id: string
  plo_fingerprint: string
  model: string                      // "" for code_only
  created_at: string                 // naive UTC, no offset: parse as UTC (append "Z")
  redundancies: { plo_ids: string[]; reason_th: string; suggestion_th: string }[]
  ksec: { plo_id: string; current: string[]; suggested: string[]; agrees: boolean; reason_th: string }[]
  bloom: { plo_id: string; declared: string; suggested_level: string | null; reason_th: string }[]
  bloom_distribution_th: string
  summary_th: string
  ksec_coverage: { counts: Record<string, number>; missing: string[]; flags: string[] }
  bloom_histogram: { counts: Record<string, number>; degree_level: string; flags: string[] }
  coverage_th: string
  unused_needs: {
    need_id: string; statement_th: string; demand_score: number; ksec_category: string
    stakeholder_types: string[]; exclusion: string; verdict: string | null; reason_th: string
  }[]
  reviewed_by: string                // "agent" | "code_only"
  code_only_reason: string | null    // "disabled" | "failed" | "timeout"
  tool_calls: { tool: string; arg: string }[]
}
```
- `POST /programs/{id}/plos/review/run` → 202 `JobInfo` (kind `plo_review`); 422 (no PLOs) and 409 (program busy) carry a Thai `detail` to show as-is.

- [ ] **Step 1: Stage list** — `constants/stages.ts`, append:

```ts
  {
    key: 'plo_review',
    route: '/plo-review',
    ordinal: 6,
    label: 'ตรวจคุณภาพชุด PLO',
    summary: 'QA agent อ่าน PLO ทั้งชุด แนะนำเรื่องซ้ำ KSEC Bloom และ Need ที่ตกหล่น',
  },
```

Update the file's top comment ("Six stages run in the engine; five of them have a page") to the new counts. Register the route `/plo-review` → `PloReview` beside `/plo-report` in the router file.

- [ ] **Step 2: The page** — `pages/PloReview.tsx`, following `PloReport.tsx`'s structure (`useProgram`, `useJobs`, `useReloadOnJobs`, `startJob`, `RunProgress`/`RunFailure`, `LoadingLine`). Requirements, top to bottom (Thai strings verbatim):

  1. Header: eyebrow `ขั้นที่ 6`, `h1.page-title` `ตรวจคุณภาพชุด PLO`, sub `QA agent อ่าน PLO ทั้งชุดที่ทำเสร็จแล้ว แล้วให้คำแนะนำ — ไม่ได้แก้ PLO ให้`. No program selected → the same empty state `PloReport` uses.
  2. Run button: `ตรวจชุด PLO` when there is no review, `ตรวจใหม่` when there is one. Disabled while `running !== null` or while starting. Click → `startJob(\`/programs/${programId}/plos/review/run\`)`, then `watch(job)` and `started(job)`; on error show `detail`; on 409 also `refresh()`. While `running?.kind === 'plo_review'` show `RunProgress` with `since = Date.parse(job.created_at)` and a plan of three lines: `เตรียมข้อมูลชุด PLO`, `agent ตรวจและเช็กข้อสงสัย`, `สรุปข้อเสนอแนะ` (follow how `PLO_REPORT_PLAN` is declared). A failed `plo_review` job → `RunFailure`.
  3. Reload: `useReloadOnJobs(['plo_review', 'plo_report', 'plo_synthesis', 'plo_revalidate', 'needs_pipeline', 'skill_extraction', 'need_combination'], reload)`. A failed `GET` shows `โหลดผลตรวจไม่สำเร็จ ตรวจว่า API ทำงานอยู่ แล้วลองใหม่` in `notice notice-error`.
  4. Status line:
     - `reviewed_by === 'agent'` → `ตรวจโดย agent · {model} · {date time th-TH}`;
     - `code_only` → `ตรวจด้วยโค้ดอย่างเดียว` + reason: `disabled` → `(ปิดการตรวจด้วย agent ไว้ใน .env)`, `failed` → `(agent ตอบไม่สำเร็จ)`, `timeout` → `(agent ใช้เวลาเกินกำหนด)`;
     - `stale` → a marker-ink notice `ผลนี้ตรวจจาก PLO ชุดก่อน — PLO หรือ Need เปลี่ยนหลังการตรวจ กดตรวจใหม่ให้ตรงกับชุดปัจจุบัน` (the old review stays shown under it);
     - no review → panel `ยังไม่ได้ตรวจชุด PLO นี้` with the run button; no PLOs (the run answers 422) → its detail plus a link `ไปสังเคราะห์ PLO` to `/plo-synthesis`.
  5. `summary_th` as a paragraph (skip when empty).
  6. Section `ภาพรวมทั้งชุด`: a line `ตัวเลขนับโดยระบบ (รวม PLO เสริม)`; KSEC counts `K · S · E · C` each with its number, a missing domain marked with `chip chip-mandate` text `ไม่มี`; legend `K ความรู้ · S ทักษะวิชาชีพ · E จริยธรรม · C คุณลักษณะบุคคล`; flag texts: `all_k` → `ทั้งชุดเป็นความรู้ (K) ล้วน`, `no_e_or_c` → `ไม่มี PLO ด้านจริยธรรม (E) หรือคุณลักษณะบุคคล (C)`; Bloom counts per level in level order using the Thai Bloom labels (reuse `BLOOM_LABEL` from `PloReport.tsx` — export it or move it to a shared module, the smaller clean change, never duplicate the map) with the degree level, flag `below_apply_majority` → `PLO เกินครึ่งอยู่ต่ำกว่าระดับประยุกต์ใช้`. Under the numbers, labelled `ความเห็นของ agent`: `coverage_th` and `bloom_distribution_th` (skip empty).
  7. Section `ความซ้ำซ้อน`: per group the ids joined ` · ` (`data`), `reason_th`, `ข้อเสนอ: {suggestion_th}`; then `รวม PLO ที่ซ้ำได้โดยรวม Need ที่หน้า` + link `สังเคราะห์ PLO` (`/plo-synthesis`). Empty → `ไม่พบ PLO ที่ซ้ำกัน`.
  8. Section `หมวดสมรรถนะรายข้อ (KSEC)`: table PLO | หมวดปัจจุบัน | หมวดที่เสนอ | เหตุผล; rows with `agrees === false` first, marked `chip` `ไม่ตรง`; agreeing rows inside `<details>` with summary `ตรงกับหมวดเดิม {n} ข้อ`; lists shown `S+E`, empty `—`; wrapper `overflow-x-auto` so the page itself never scrolls sideways. Empty → `ไม่มีข้อมูล KSEC`.
  9. Section `ระดับ Bloom รายข้อ`: per entry `plo_id`, declared label → suggested label (no arrow when `suggested_level` is null or equal), `reason_th`. Empty → `ระดับ Bloom ทุกข้อเหมาะกับกริยาและระดับปริญญา`.
  10. Section `Need สำคัญที่ไม่ได้เป็น PLO`: per Need `statement_th`, `demand {score.toFixed(2)}`, KSEC, stakeholder types, exclusion (`lost_on_demand` → `ไม่ติดอันดับ demand`, `out_of_scope` → `อยู่นอกขอบเขตหลักสูตร`, `unwritten` → `ประโยค Need ยังไม่ได้เขียน`), verdict (`consider` → `chip chip-marker` `ควรพิจารณา` plus a link `ไปที่สังเคราะห์ PLO`; `ok_to_leave` → `chip chip-neutral` `ปล่อยไว้ได้`; null → nothing), `reason_th`. Empty list → `ไม่มี Need สำคัญที่ตกหล่น`.
  11. `<details>` summary `agent ไปดูอะไรมาบ้าง ({n})`, list of `tool · arg` (`data` class). Hidden when the list is empty.

- [ ] **Step 3: The other pages.**
  - `api/jobs.ts`: `plo_review: { path: '/plo-review' }`.
  - `PloReport.tsx`: `PAGE_KINDS = ['plo_report']` with its comment updated; replace the footer `ตรวจเสร็จแล้ว อนุมัติและปิด session ได้ที่ รันทั้งชุด` with `<Link to="/plo-review" className="link">ไปตรวจคุณภาพชุด PLO →</Link>`.
  - `Pipeline.tsx` `CHECKPOINT_TH`: delete the `plo_report` entry; `plo_synthesis` becomes `'สังเคราะห์ PLO เสร็จแล้ว — ตรวจและแก้ PLO ก่อนสร้างรายงานและตรวจคุณภาพ'`.

- [ ] **Step 4: Mock layer.** `GET /programs/:pid/plos/review` answers `{ review, stale: false, review_enabled: true }` from the mock db; seed one review consistent with the mock PLO and Need ids: `reviewed_by: 'agent'`, one redundancy group of two PLOs, a KSEC entry for every mock PLO with at least one `agrees: false`, one Bloom entry with a suggested level, `ksec_coverage` with one missing domain and the `no_e_or_c` flag, a `bloom_histogram`, two `unused_needs` (one `consider`, one `ok_to_leave`), `coverage_th`, `bloom_distribution_th`, `summary_th`, and two `tool_calls`. The existing `POST …/review/run` mock stores and returns that review (keep its job mechanics; the job result is `{ review, stale: false, review_enabled: true }`). The `report/run` mock result drops `review`, `review_stale`, `review_enabled`.

- [ ] **Step 5: Verify**

Run (from `frontend/`): `npm run lint` — expected 0 errors (one pre-existing warning in `Pipeline.tsx` is fine); `npm run build` — expected success (writes `frontend/dist`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/PloReview.tsx frontend/src/constants/stages.ts frontend/src/api/jobs.ts frontend/src/pages/PloReport.tsx frontend/src/pages/Pipeline.tsx frontend/src/mock/handlers.ts frontend/src/mock/db.ts
# plus the router file and any shared module BLOOM_LABEL moved to
git commit -m "feat(ui): stage 06 page for the PLO QA agent"
```

---

### Task 7: Docs

**Files:**
- Modify: `CLAUDE.md`, `.claude/skills/curriculum-design-agent/references/data-schemas.md`, `docs/prompt-inventory.md` (regenerated), `docs/superpowers/specs/2026-10-04-plo-set-review-design.md` (note at top)

- [ ] **Step 1: `CLAUDE.md`**
  - Opening paragraph: the pipeline now ends intake → stakeholder needs → skill extraction → need combination → PLO synthesis → PLO report → PLO QA review; checkpoints at every boundary except skill_extraction/need_combination (one shared checkpoint) and after the PLO checkpoint, where the report and the QA review run straight to the end.
  - Immutable rule 7: replace the "plo_review → plo_report share the report's checkpoint" exception with: after the PLO checkpoint, `plo_report` and `plo_review` run through to the end of the session with no checkpoint — waived by the designer on 2026-10-12 because neither changes designer content (the report re-persists the approved set; the QA agent only writes its own review row).
  - The `PLO_REVIEW_PROVIDER` slot paragraph: stage 06, a tool-using agent (`stages/plo_review_agent.py`), runs after the report; up to 4 tool calls and 6 steps, reasoning bounded 1024 on every step, timeout 300s; disabled (`PLO_REVIEW_PROVIDER=`) still stores the code facts as `code_only`.
  - The pitfall "The set review advises; nothing reads it back": add the dossier limits (no evidence, skill names, shared-evidence share, old verdicts — and why: information bias), that every number is code's (`plo_review_facts.py`), the `code_only` rule, and that the fingerprint covers the Needs.
- [ ] **Step 2: `data-schemas.md`**: the new `PLOSetReview` fields and the four new models, one line each.
- [ ] **Step 3: Regenerate the prompt inventory**

Run: `uv run python scripts/dump_prompts.py` then `uv run python scripts/dump_prompts.py --check`
Expected: the second command exits 0.

- [ ] **Step 4: Old spec note** — first line under the title of `2026-10-04-plo-set-review-design.md`: `> Partly superseded by 2026-10-12-plo-qa-agent-design.md (placement, the single call, the 503, the rule 7 text).`
- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .claude/skills/curriculum-design-agent/references/data-schemas.md docs/prompt-inventory.md docs/superpowers/specs/2026-10-04-plo-set-review-design.md
git commit -m "docs: the PLO QA agent as stage 06, and rule 7's new exception"
```

---

### Controller after Task 7 (not a subagent task)

- Rebuild `frontend/dist` if Task 6's build is stale; restart a backend on a free port against the live DB.
- Run `POST /programs/program/plos/review/run` and `POST /programs/program-2/plos/review/run`; poll `GET /jobs/{id}` to the end. Record per program: wall time, `reviewed_by`, `tool_calls`, counts of each finding kind, and anything notable — in a new "Measured (2026-10-1x)" section of the spec. Confirm the rail shows six ● for a program with a current review.
