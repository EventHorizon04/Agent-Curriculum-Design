# PLO Report & Generic/Specific Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Stage 5 (YLO Derivation) in the *active* pipeline with a PLO Report stage that classifies each PLO as generic/specific (structured-field heuristic first, LLM fallback), with HITL review and a list + PLO×Cluster matrix UI.

**Architecture:** A new `plo_report` LangGraph node runs after `review_plos_node`, classifies each PLO using the source clusters' `is_subject_specific` fraction (clear → field-based; ambiguous → light-model LLM), syncs `PLO.is_subject_specific` with a new `classification` field, and suspends at a `review_plo_report` interrupt. YLO nodes are detached from the graph but their code is retained. The frontend gets a new `PloReport.tsx` with grouped-list and matrix views composed from existing `/plos/` and `/clusters/` endpoints.

**Tech Stack:** Python 3.11, Pydantic v2, LangGraph, SQLAlchemy + Alembic, FastAPI, Instructor/Ollama (`complete_light`), React 19 + Vite + TypeScript + Tailwind.

**Spec:** `docs/superpowers/specs/2026-06-15-plo-report-classification-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/curriculum_agent/models.py` | modify | add 3 optional classification fields to `PLO` |
| `tests/unit/test_plo_classification_fields.py` | create | PLO model field defaults + Literal validation |
| `src/curriculum_agent/data/orm.py` | modify | add 3 nullable columns to `PLOTable` |
| `migrations/versions/<rev>_add_plo_classification.py` | create | Alembic migration for the 3 columns |
| `src/curriculum_agent/prompts/plo_classify.py` | create | typed prompt builder for LLM fallback |
| `tests/unit/test_plo_classify_prompt.py` | create | prompt builder shape |
| `src/curriculum_agent/stages/plo_report.py` | create | method-D classification stage |
| `tests/unit/test_plo_report.py` | create | field-clear, ambiguous→LLM, no-cluster, sync invariant |
| `src/curriculum_agent/graph.py` | modify | add `plo_report`/`review_plo_report` nodes, detach YLO |
| `tests/unit/test_plo_report_graph.py` | create | review node merge + graph structure |
| `src/curriculum_agent/api/routes/plos.py` | modify | `POST /report/run` + PUT sync logic |
| `tests/unit/test_plo_report_router.py` | create | report/run + PUT classification sync |
| `frontend/src/pages/PloReport.tsx` | create | list + matrix report UI |
| `frontend/src/components/StageLayout.tsx` | modify | swap nav: YLO → PLO Report |
| `frontend/src/App.tsx` | modify | add `/plo-report` route (keep `/ylo-derivation`) |
| `frontend/src/pages/PloSynthesis.tsx` | modify | "ดำเนินการต่อ" link → `/plo-report` |

---

## Task 1: Add classification fields to the PLO model

**Files:**
- Modify: `src/curriculum_agent/models.py`
- Test: `tests/unit/test_plo_classification_fields.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plo_classification_fields.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from curriculum_agent.models import PLO, BloomLevel, Domain, SMARTCheck

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _make_plo(**overrides) -> PLO:
    base = dict(
        plo_id="PLO1",
        program_id="cs-test",
        statement_th="ออกแบบและพัฒนาซอฟต์แวร์ที่มีคุณภาพได้",
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.CREATE,
        is_subject_specific=True,
        action_verb_th="ออกแบบ",
        smart_check=_SMART,
        source_cluster_ids=["C1"],
        source_evidence_ids=["E1"],
        rationale_th="ทักษะหลักที่นายจ้างต้องการ",
    )
    base.update(overrides)
    return PLO(**base)


def test_classification_fields_default_none():
    plo = _make_plo()
    assert plo.classification is None
    assert plo.classification_method is None
    assert plo.classification_rationale_th is None


def test_classification_fields_accept_valid_values():
    plo = _make_plo(
        classification="generic",
        classification_method="llm",
        classification_rationale_th="เป็นทักษะที่ถ่ายโอนข้ามสาขาได้",
    )
    assert plo.classification == "generic"
    assert plo.classification_method == "llm"


def test_classification_rejects_invalid_literal():
    with pytest.raises(ValidationError):
        _make_plo(classification="cross-cutting")


def test_classification_method_rejects_invalid_literal():
    with pytest.raises(ValidationError):
        _make_plo(classification_method="guess")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_plo_classification_fields.py -v`
Expected: FAIL — `test_classification_fields_accept_valid_values` raises `ValidationError` (PLO has no `classification` field, extra inputs ignored or model lacks attribute → `AttributeError`/assertion fails).

- [ ] **Step 3: Add the fields to PLO**

In `src/curriculum_agent/models.py`, inside `class PLO(BaseModel):`, add these three fields immediately after the `version: int = 1` line (line 163) and before the first `@model_validator`:

```python
    version: int = 1
    classification: Literal["generic", "specific"] | None = None
    classification_method: Literal["skill_type", "llm", "manual"] | None = None
    classification_rationale_th: str | None = None
```

`Literal` is already imported at the top of `models.py` (`from typing import Literal`). No new import needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_plo_classification_fields.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Run the existing model suite to confirm no regression**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/models.py tests/unit/test_plo_classification_fields.py
git commit -m "feat: add classification fields to PLO model"
```

---

## Task 2: Add PLOTable columns and Alembic migration

**Files:**
- Modify: `src/curriculum_agent/data/orm.py`
- Create: `migrations/versions/<rev>_add_plo_classification.py` (autogenerated)

- [ ] **Step 1: Add columns to PLOTable**

In `src/curriculum_agent/data/orm.py`, inside `class PLOTable(Base):`, add three columns immediately after `version: Mapped[int] = mapped_column(Integer, default=1)` (line 100):

```python
    version: Mapped[int] = mapped_column(Integer, default=1)
    classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_rationale_th: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`String` and `Text` are already imported at the top of `orm.py`. No new import needed.

- [ ] **Step 2: Ensure Docker DB is up and at head**

Run: `docker compose up -d postgres` then `uv run alembic upgrade head`
Expected: `alembic` reports the current head with no errors (needed so autogenerate diffs against the live schema).

- [ ] **Step 3: Generate the migration**

Run: `uv run alembic revision --autogenerate -m "add_plo_classification"`
Expected: a new file appears in `migrations/versions/` containing `add_plo_classification` in its name.

- [ ] **Step 4: Review the generated migration**

Open the generated file. Confirm `upgrade()` contains exactly three `op.add_column('plos', sa.Column('classification', ...))`, `classification_method`, and `classification_rationale_th`, all `nullable=True`. Confirm `downgrade()` drops the same three columns. **Delete any unrelated `op.*` lines** autogenerate may have added for other tables.

- [ ] **Step 5: Apply the migration**

Run: `uv run alembic upgrade head`
Expected: `Running upgrade ... -> <rev>, add_plo_classification` with no errors.

- [ ] **Step 6: Verify current revision is head**

Run: `uv run alembic current`
Expected: line ending with `(head)`

- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/data/orm.py migrations/
git commit -m "feat: add plo classification columns and migration"
```

---

## Task 3: Classification prompt builder

**Files:**
- Create: `src/curriculum_agent/prompts/plo_classify.py`
- Test: `tests/unit/test_plo_classify_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plo_classify_prompt.py`:

```python
from __future__ import annotations

from curriculum_agent.prompts.plo_classify import build_plo_classify_prompt


def test_prompt_has_system_and_user_messages():
    msgs = build_plo_classify_prompt(
        "ออกแบบและพัฒนาระบบซอฟต์แวร์",
        "cognitive",
        ["Programming (skill_type=knowledge, เฉพาะสาขา)"],
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "generic" in msgs[0]["content"]
    assert "specific" in msgs[0]["content"]


def test_prompt_includes_statement_and_clusters():
    msgs = build_plo_classify_prompt(
        "วิเคราะห์ข้อมูล",
        "cognitive",
        ["Data Analysis (skill_type=knowledge, เฉพาะสาขา)"],
    )
    user = msgs[1]["content"]
    assert "วิเคราะห์ข้อมูล" in user
    assert "Data Analysis" in user


def test_prompt_handles_no_clusters():
    msgs = build_plo_classify_prompt("สื่อสารอย่างมีประสิทธิภาพ", "affective", [])
    assert len(msgs) == 2
    assert isinstance(msgs[1]["content"], str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_plo_classify_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.prompts.plo_classify'`

- [ ] **Step 3: Create the prompt builder**

Create `src/curriculum_agent/prompts/plo_classify.py`:

```python
from __future__ import annotations


def build_plo_classify_prompt(
    statement_th: str,
    domain: str,
    cluster_summaries: list[str],
) -> list[dict]:
    """Light-model prompt to classify a PLO as generic vs specific.

    cluster_summaries: each ≤200-token line describing one source cluster.
    Returns OpenAI-style messages for Instructor structured output.
    """
    summary_block = "\n".join(f"- {s}" for s in cluster_summaries) or "(ไม่มีข้อมูล cluster)"
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE ทำหน้าที่จำแนกประเภทของ PLO "
                "ว่าเป็น 'generic' (ทักษะทั่วไปที่ถ่ายโอนข้ามสาขาได้ เช่น การสื่อสาร "
                "การคิดวิเคราะห์ การทำงานเป็นทีม) หรือ 'specific' "
                "(ทักษะ/ความรู้เฉพาะสาขาหรือวิชาชีพ) "
                "ตอบเป็น JSON ที่มี field 'classification' (ค่า 'generic' หรือ 'specific') "
                "และ 'rationale_th' (เหตุผลสั้น ๆ เป็นภาษาไทย)"
            ),
        },
        {
            "role": "user",
            "content": (
                f"PLO statement:\n{statement_th}\n\n"
                f"Domain: {domain}\n\n"
                f"Skill clusters ที่เกี่ยวข้อง:\n{summary_block}"
            ),
        },
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_plo_classify_prompt.py -v`
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/prompts/plo_classify.py tests/unit/test_plo_classify_prompt.py
git commit -m "feat: add PLO generic/specific classification prompt builder"
```

---

## Task 4: PLO report stage (method D)

**Files:**
- Create: `src/curriculum_agent/stages/plo_report.py`
- Test: `tests/unit/test_plo_report.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plo_report.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    Domain,
    SMARTCheck,
    SkillCluster,
    SkillType,
)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _plo(cluster_ids: list[str]) -> dict:
    return PLO(
        plo_id="PLO1",
        program_id="prog-1",
        statement_th="ออกแบบและพัฒนาระบบซอฟต์แวร์",
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.CREATE,
        is_subject_specific=False,
        action_verb_th="ออกแบบ",
        smart_check=_SMART,
        source_cluster_ids=cluster_ids,
        source_evidence_ids=["ev-1"],
        rationale_th="เหตุผล",
    ).model_dump(mode="json")


def _cluster(cid: str, subject_specific: bool) -> SkillCluster:
    return SkillCluster(
        cluster_id=cid,
        program_id="prog-1",
        canonical_name_th="ทักษะ",
        canonical_name_en="Skill",
        description_th="รายละเอียด",
        skill_type=SkillType.KNOWLEDGE,
        is_subject_specific=subject_specific,
        member_skill_ids=["s1"],
        source_evidence_ids=["ev-1"],
        demand_score=0.5,
    )


def _patch_ctx(clusters, light_mock):
    cluster_repo = AsyncMock()
    cluster_repo.list_by_program = AsyncMock(return_value=clusters)
    plo_repo = AsyncMock()
    plo_repo.bulk_insert = AsyncMock()
    return (
        patch("curriculum_agent.stages.plo_report.ClusterRepository", return_value=cluster_repo),
        patch("curriculum_agent.stages.plo_report.PLORepository", return_value=plo_repo),
        patch("curriculum_agent.stages.plo_report.complete_light", light_mock),
    )


async def test_field_clear_specific_skips_llm():
    from curriculum_agent.stages.plo_report import run

    clusters = [_cluster("c1", True), _cluster("c2", True), _cluster("c3", True)]
    light = AsyncMock()
    p1, p2, p3 = _patch_ctx(clusters, light)
    state = {"program_id": "prog-1", "plos": [_plo(["c1", "c2", "c3"])]}
    with p1, p2, p3:
        result = await run(state)

    plo = result["plos"][0]
    assert plo["classification"] == "specific"
    assert plo["classification_method"] == "skill_type"
    assert plo["is_subject_specific"] is True
    light.assert_not_called()


async def test_field_clear_generic_skips_llm():
    from curriculum_agent.stages.plo_report import run

    clusters = [_cluster("c1", False), _cluster("c2", False), _cluster("c3", False)]
    light = AsyncMock()
    p1, p2, p3 = _patch_ctx(clusters, light)
    state = {"program_id": "prog-1", "plos": [_plo(["c1", "c2", "c3"])]}
    with p1, p2, p3:
        result = await run(state)

    plo = result["plos"][0]
    assert plo["classification"] == "generic"
    assert plo["classification_method"] == "skill_type"
    assert plo["is_subject_specific"] is False
    light.assert_not_called()


async def test_ambiguous_uses_llm_fallback():
    from curriculum_agent.stages.plo_report import _ClassificationResult, run

    clusters = [_cluster("c1", True), _cluster("c2", False)]  # fraction 0.5 → ambiguous
    light = AsyncMock(
        return_value=_ClassificationResult(classification="generic", rationale_th="ทักษะทั่วไป")
    )
    p1, p2, p3 = _patch_ctx(clusters, light)
    state = {"program_id": "prog-1", "plos": [_plo(["c1", "c2"])]}
    with p1, p2, p3:
        result = await run(state)

    plo = result["plos"][0]
    assert plo["classification"] == "generic"
    assert plo["classification_method"] == "llm"
    assert plo["is_subject_specific"] is False
    assert plo["classification_rationale_th"] == "ทักษะทั่วไป"
    light.assert_called_once()


async def test_no_resolvable_clusters_uses_llm():
    from curriculum_agent.stages.plo_report import _ClassificationResult, run

    clusters = []  # PLO references c9 which does not exist
    light = AsyncMock(
        return_value=_ClassificationResult(classification="specific", rationale_th="เฉพาะสาขา")
    )
    p1, p2, p3 = _patch_ctx(clusters, light)
    state = {"program_id": "prog-1", "plos": [_plo(["c9"])]}
    with p1, p2, p3:
        result = await run(state)

    plo = result["plos"][0]
    assert plo["classification"] == "specific"
    assert plo["classification_method"] == "llm"
    light.assert_called_once()


async def test_raises_when_no_plos():
    from curriculum_agent.stages.plo_report import run

    light = AsyncMock()
    p1, p2, p3 = _patch_ctx([], light)
    state = {"program_id": "prog-1", "plos": []}
    with p1, p2, p3:
        try:
            await run(state)
            assert False, "expected ValueError"
        except ValueError:
            pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_plo_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.stages.plo_report'`

- [ ] **Step 3: Create the stage**

Create `src/curriculum_agent/stages/plo_report.py`:

```python
from __future__ import annotations

from typing import Literal

from loguru import logger
from pydantic import BaseModel

from curriculum_agent.data.repositories import ClusterRepository, PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import PLO, SkillCluster
from curriculum_agent.prompts.plo_classify import build_plo_classify_prompt

# specific_fraction thresholds for the field-based decision; the open interval
# (LO, HI) is treated as ambiguous and routed to the LLM fallback.
_SPECIFIC_HI = 0.67
_SPECIFIC_LO = 0.33


class _ClassificationResult(BaseModel):
    classification: Literal["generic", "specific"]
    rationale_th: str


def _cluster_summary(c: SkillCluster) -> str:
    spec = "เฉพาะสาขา" if c.is_subject_specific else "ทั่วไป"
    name = c.canonical_name_en or c.canonical_name_th
    return f"{name} (skill_type={c.skill_type.value}, {spec})"


async def _classify_one(
    plo: PLO, clusters_by_id: dict[str, SkillCluster]
) -> tuple[str, str, str]:
    """Return (classification, method, rationale_th) for a single PLO."""
    resolved = [
        clusters_by_id[cid] for cid in plo.source_cluster_ids if cid in clusters_by_id
    ]

    if resolved:
        n_specific = sum(1 for c in resolved if c.is_subject_specific)
        fraction = n_specific / len(resolved)
        rationale = (
            f"{n_specific}/{len(resolved)} source clusters เป็น subject-specific "
            f"(fraction {fraction:.2f})"
        )
        if fraction >= _SPECIFIC_HI:
            return "specific", "skill_type", rationale
        if fraction <= _SPECIFIC_LO:
            return "generic", "skill_type", rationale

    # Ambiguous fraction, or no resolvable clusters → LLM fallback.
    summaries = [_cluster_summary(c) for c in resolved]
    messages = build_plo_classify_prompt(plo.statement_th, plo.domain.value, summaries)
    result = await complete_light(_ClassificationResult, messages)
    return result.classification, "llm", result.rationale_th


async def run(state: AgentState) -> AgentState:
    """PLO Report stage: classify each PLO as generic/specific (method D)."""
    program_id = state.get("program_id", "unknown")
    plo_dicts = state.get("plos", [])
    if not plo_dicts:
        raise ValueError(
            f"PLO report: no PLOs for program '{program_id}' — run PLO synthesis first"
        )

    plos = [PLO.model_validate(d) for d in plo_dicts]
    clusters = await ClusterRepository().list_by_program(program_id)
    clusters_by_id = {c.cluster_id: c for c in clusters}

    logger.info(f"PLO report: classifying {len(plos)} PLOs (generic/specific)")

    classified: list[PLO] = []
    for plo in plos:
        classification, method, rationale = await _classify_one(plo, clusters_by_id)
        classified.append(
            plo.model_copy(
                update={
                    "classification": classification,
                    "classification_method": method,
                    "classification_rationale_th": rationale,
                    "is_subject_specific": classification == "specific",
                }
            )
        )

    await PLORepository().bulk_insert(classified)

    state["plos"] = [p.model_dump(mode="json") for p in classified]
    state["current_stage"] = "plo_report"
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_plo_report.py -v`
Expected: 5 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/stages/plo_report.py tests/unit/test_plo_report.py
git commit -m "feat: add plo_report stage with method-D generic/specific classification"
```

---

## Task 5: Wire the graph (add plo_report, detach YLO)

**Files:**
- Modify: `src/curriculum_agent/graph.py`
- Test: `tests/unit/test_plo_report_graph.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plo_report_graph.py`:

```python
from __future__ import annotations

from unittest.mock import patch

from curriculum_agent.graph import AgentState, build_graph, review_plo_report


def test_review_plo_report_merges_payload():
    edited = [{"plo_id": "PLO1", "classification": "generic"}]
    state: AgentState = {"program_id": "t", "plos": [{"plo_id": "PLO1", "classification": "specific"}]}
    with patch("curriculum_agent.graph.interrupt", return_value={"plos": edited}):
        result = review_plo_report(state)
    assert result["plos"] == edited


def test_review_plo_report_returns_state_when_no_payload():
    state: AgentState = {"program_id": "t", "plos": [{"plo_id": "PLO1"}]}
    with patch("curriculum_agent.graph.interrupt", return_value=None):
        result = review_plo_report(state)
    assert result == state


def test_graph_wires_plo_report_and_detaches_ylo():
    nodes = set(build_graph().get_graph().nodes)
    assert "plo_report" in nodes
    assert "review_plo_report" in nodes
    assert "ylo_derivation" not in nodes
    assert "review_ylo" not in nodes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_plo_report_graph.py -v`
Expected: FAIL — `ImportError: cannot import name 'review_plo_report' from 'curriculum_agent.graph'`

- [ ] **Step 3: Add the node functions**

In `src/curriculum_agent/graph.py`, add a stage wrapper after `stage_4_ylo_derivation` (after line 78):

```python
async def stage_5_plo_report(state: AgentState) -> AgentState:
    from curriculum_agent.stages.plo_report import run  # noqa: PLC0415
    return await run(state)
```

Then add a review node after `review_ylo_matrix` (after line 108):

```python
def review_plo_report(state: AgentState) -> AgentState:
    payload = interrupt("Stage 5 complete — review/edit PLO generic-specific classification")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state
```

Leave `stage_4_ylo_derivation` and `review_ylo_matrix` defined — they are retained, just unwired.

- [ ] **Step 4: Update `build_graph`**

In `src/curriculum_agent/graph.py`, replace the entire body of `build_graph` (lines 113-137) with:

```python
def build_graph(checkpointer=None):
    g = StateGraph(AgentState)

    g.add_node("intake", stage_0_intake)
    g.add_node("stakeholder_needs", stage_1_stakeholder_needs)
    g.add_node("review_evidence", review_stakeholder_needs)
    g.add_node("skill_extraction", stage_2_skill_extraction)
    g.add_node("review_clusters", review_skill_clusters)
    g.add_node("plo_synthesis", stage_3_plo_synthesis)
    g.add_node("review_plos_node", review_plos)
    g.add_node("plo_report", stage_5_plo_report)
    g.add_node("review_plo_report", review_plo_report)

    g.set_entry_point("intake")
    g.add_edge("intake", "stakeholder_needs")
    g.add_edge("stakeholder_needs", "review_evidence")
    g.add_edge("review_evidence", "skill_extraction")
    g.add_edge("skill_extraction", "review_clusters")
    g.add_edge("review_clusters", "plo_synthesis")
    g.add_edge("plo_synthesis", "review_plos_node")
    g.add_edge("review_plos_node", "plo_report")
    g.add_edge("plo_report", "review_plo_report")
    g.add_edge("review_plo_report", END)

    return g.compile(checkpointer=checkpointer)
```

This removes the `ylo_derivation` / `review_ylo` `add_node` calls and their edges; the node *functions* remain in the module.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_plo_report_graph.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Run the graph HITL regression test**

Run: `uv run pytest tests/unit/test_graph_hitl.py -v`
Expected: all PASS (the existing review nodes are unchanged)

- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/graph.py tests/unit/test_plo_report_graph.py
git commit -m "feat: wire plo_report stage and review node, detach YLO from graph"
```

---

## Task 6: API routes — report/run and PUT sync

**Files:**
- Modify: `src/curriculum_agent/api/routes/plos.py`
- Test: `tests/unit/test_plo_report_router.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_plo_report_router.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from curriculum_agent.api.routes.plos import router
from curriculum_agent.models import PLO, BloomLevel, Domain, SMARTCheck

app = FastAPI()
app.include_router(router, prefix="/programs/{program_id}/plos")
client = TestClient(app)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _plo(**overrides) -> PLO:
    base = dict(
        plo_id="PLO1",
        program_id="p1",
        statement_th="ออกแบบและพัฒนาระบบซอฟต์แวร์",
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.CREATE,
        is_subject_specific=True,
        action_verb_th="ออกแบบ",
        smart_check=_SMART,
        source_cluster_ids=["c1"],
        source_evidence_ids=["e1"],
        rationale_th="เหตุผล",
    )
    base.update(overrides)
    return PLO(**base)


def test_report_run_returns_classified_plos():
    classified = _plo(classification="specific", classification_method="skill_type")

    async def fake_run(state):
        return {"plos": [classified.model_dump(mode="json")]}

    with (
        patch("curriculum_agent.api.routes.plos._repo") as mock_repo,
        patch("curriculum_agent.stages.plo_report.run", side_effect=fake_run),
    ):
        mock_repo.list_by_program = AsyncMock(return_value=[_plo()])
        resp = client.post("/programs/p1/plos/report/run")

    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["classification"] == "specific"


def test_report_run_422_when_no_plos():
    with patch("curriculum_agent.api.routes.plos._repo") as mock_repo:
        mock_repo.list_by_program = AsyncMock(return_value=[])
        resp = client.post("/programs/p1/plos/report/run")
    assert resp.status_code == 422


def test_put_sets_method_manual_and_syncs_specific_flag():
    """Human flips to generic → method becomes manual, is_subject_specific False."""
    existing = _plo(is_subject_specific=True)
    edited = _plo(is_subject_specific=True, classification="generic")  # client may send stale flag

    captured: dict = {}

    async def capture_insert(plos):
        captured["plo"] = plos[0]

    with patch("curriculum_agent.api.routes.plos._repo") as mock_repo:
        mock_repo.list_by_program = AsyncMock(return_value=[existing])
        mock_repo.bulk_insert = AsyncMock(side_effect=capture_insert)
        resp = client.put(
            "/programs/p1/plos/PLO1",
            json=edited.model_dump(mode="json"),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["classification"] == "generic"
    assert body["classification_method"] == "manual"
    assert body["is_subject_specific"] is False
    assert captured["plo"].is_subject_specific is False
```

Note: `require_api_key` allows the request through because `settings.api_key` is `None` in the test environment (dev mode — see `deps.py`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_plo_report_router.py -v`
Expected: FAIL — `test_report_run_*` return 404/405 (no `/report/run` route) and `test_put_*` returns `classification_method` `None` (no sync logic yet).

- [ ] **Step 3: Add the `report/run` endpoint**

In `src/curriculum_agent/api/routes/plos.py`, add this handler immediately after the existing `run_plo_synthesis` handler (after line 73):

```python
@router.post("/report/run", response_model=list[PLO])
async def run_plo_report(program_id: str) -> list[PLO]:
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
    result_state = await run(state)
    return [PLO.model_validate(p) for p in result_state.get("plos", [])]
```

`AgentState` and `PLO` are already imported at the top of `plos.py` (lines 13-14). `HTTPException` is already imported (line 3).

- [ ] **Step 4: Update the PUT handler to sync classification**

In `src/curriculum_agent/api/routes/plos.py`, replace the body of `update_plo` (lines 77-84) with:

```python
async def update_plo(program_id: str, plo_id: str, plo: PLO) -> PLO:
    existing = await _repo.list_by_program(program_id)
    match = next((p for p in existing if p.plo_id == plo_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="PLO not found")

    update_fields: dict = {"version": match.version + 1, "program_id": program_id}
    if plo.classification is not None:
        # Human edit is the source of truth: mark manual and force the flag to match.
        update_fields["classification_method"] = "manual"
        update_fields["is_subject_specific"] = plo.classification == "specific"
    updated = plo.model_copy(update=update_fields)
    await _repo.bulk_insert([updated])
    return updated
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_plo_report_router.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Run the existing plos router test for regression**

Run: `uv run pytest tests/unit/test_api_plos.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/api/routes/plos.py tests/unit/test_plo_report_router.py
git commit -m "feat: add plos report/run endpoint and PUT classification sync"
```

---

## Task 7: Frontend — PloReport page, routing, nav

**Files:**
- Create: `frontend/src/pages/PloReport.tsx`
- Modify: `frontend/src/components/StageLayout.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/PloSynthesis.tsx`

- [ ] **Step 1: Create `frontend/src/pages/PloReport.tsx`**

```tsx
import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useProgram } from '../hooks/useProgram'
import api from '../api/client'

interface SMARTCheck {
  specific: boolean
  measurable: boolean
  achievable: boolean
  relevant: boolean
  timely: boolean
  notes_th: string | null
}

interface PLO {
  plo_id: string
  program_id: string
  statement_th: string
  statement_en: string | null
  domain: string
  bloom_level: string | null
  krathwohl_level: string | null
  is_subject_specific: boolean
  action_verb_th: string
  smart_check: SMARTCheck
  source_cluster_ids: string[]
  source_evidence_ids: string[]
  rationale_th: string
  distinctive_feature_th: string | null
  version: number
  classification: 'generic' | 'specific' | null
  classification_method: 'skill_type' | 'llm' | 'manual' | null
  classification_rationale_th: string | null
}

interface SkillCluster {
  cluster_id: string
  canonical_name_th: string
  canonical_name_en: string | null
}

const METHOD_LABEL: Record<string, string> = {
  skill_type: 'field',
  llm: 'LLM',
  manual: 'manual',
}

const METHOD_COLOR: Record<string, string> = {
  skill_type: 'bg-gray-100 text-gray-600',
  llm: 'bg-blue-100 text-blue-700',
  manual: 'bg-amber-100 text-amber-700',
}

function effectiveClass(p: PLO): 'generic' | 'specific' {
  if (p.classification) return p.classification
  return p.is_subject_specific ? 'specific' : 'generic'
}

export default function PloReport() {
  const { programId } = useProgram()
  const [plos, setPlos] = useState<PLO[]>([])
  const [clusters, setClusters] = useState<SkillCluster[]>([])
  const [view, setView] = useState<'list' | 'matrix'>('list')
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    if (!programId) return
    setLoading(true)
    setError('')
    try {
      const [ploRes, clusterRes] = await Promise.all([
        api.get<PLO[]>(`/programs/${programId}/plos/`),
        api.get<SkillCluster[]>(`/programs/${programId}/clusters/`),
      ])
      setPlos(ploRes.data)
      setClusters(clusterRes.data)
    } catch {
      setError('โหลดข้อมูลไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [programId])

  const runReport = useCallback(async () => {
    if (!programId) return
    setRunning(true)
    setError('')
    try {
      const res = await api.post<PLO[]>(`/programs/${programId}/plos/report/run`)
      setPlos(res.data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'รัน PLO Report ไม่สำเร็จ')
    } finally {
      setRunning(false)
    }
  }, [programId])

  useEffect(() => { fetchData() }, [fetchData])

  const flip = async (p: PLO) => {
    const next = effectiveClass(p) === 'specific' ? 'generic' : 'specific'
    const body: PLO = {
      ...p,
      classification: next,
      is_subject_specific: next === 'specific',
    }
    try {
      const res = await api.put<PLO>(`/programs/${programId}/plos/${p.plo_id}`, body)
      setPlos(prev => prev.map(x => (x.plo_id === p.plo_id ? res.data : x)))
    } catch {
      setError('สลับประเภทไม่สำเร็จ')
    }
  }

  if (!programId) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center">
        <p className="text-gray-500 mb-4">ยังไม่ได้เลือกโปรแกรม</p>
        <Link to="/" className="text-blue-600 hover:underline">ไปหน้า Intake</Link>
      </div>
    )
  }

  const generic = plos.filter(p => effectiveClass(p) === 'generic')
  const specific = plos.filter(p => effectiveClass(p) === 'specific')
  const referencedClusters = clusters.filter(c =>
    plos.some(p => p.source_cluster_ids.includes(c.cluster_id))
  )

  return (
    <div className="max-w-5xl mx-auto py-8 px-4">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Stage 5: PLO Report</h1>
        <p className="text-gray-500 text-sm">
          จำแนก PLO เป็นทักษะทั่วไป (generic) หรือเฉพาะสาขา (specific) — ตรวจสอบและแก้ไขได้
        </p>
        <p className="text-xs text-gray-400 mt-1 font-mono">{programId}</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-red-700 text-sm">{error}</div>
      )}

      {loading ? (
        <div className="text-center py-16 text-gray-400">กำลังโหลด...</div>
      ) : running ? (
        <div className="text-center py-20">
          <div className="text-4xl mb-4 animate-spin">⚙️</div>
          <p className="text-gray-600 font-medium mb-1">กำลังจำแนก PLO...</p>
        </div>
      ) : plos.length === 0 ? (
        <div className="text-center py-20">
          <div className="text-5xl mb-4">🗂️</div>
          <p className="text-gray-500 text-lg font-medium mb-1">ยังไม่มี PLO</p>
          <p className="text-gray-400 text-sm mb-6">รัน PLO Synthesis ก่อน แล้วกลับมาจำแนกที่นี่</p>
          <button
            onClick={runReport}
            className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 font-medium"
          >
            Run PLO Report
          </button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap justify-between items-center gap-3 mb-5">
            <div className="flex items-center gap-4 text-sm text-gray-500">
              <span><b className="text-gray-700">{generic.length}</b> generic</span>
              <span><b className="text-gray-700">{specific.length}</b> specific</span>
              <button onClick={runReport} className="text-xs text-gray-400 hover:text-blue-600 underline">
                Re-run
              </button>
            </div>
            <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
              <button
                onClick={() => setView('list')}
                className={`text-sm px-3 py-1 rounded-md ${view === 'list' ? 'bg-white shadow-sm font-medium' : 'text-gray-500'}`}
              >
                List
              </button>
              <button
                onClick={() => setView('matrix')}
                className={`text-sm px-3 py-1 rounded-md ${view === 'matrix' ? 'bg-white shadow-sm font-medium' : 'text-gray-500'}`}
              >
                Matrix
              </button>
            </div>
          </div>

          {view === 'list' ? (
            <div className="space-y-8">
              <ReportGroup title="Generic Skills" plos={generic} onFlip={flip} />
              <ReportGroup title="Specific Skills" plos={specific} onFlip={flip} />
            </div>
          ) : (
            <ReportMatrix plos={plos} clusters={referencedClusters} />
          )}

          <div className="mt-8 text-sm text-gray-500 border-t border-gray-100 pt-4">
            เมื่อตรวจสอบเสร็จ ไปที่{' '}
            <Link to="/pipeline" className="text-blue-600 hover:underline">หน้า Pipeline</Link>{' '}
            เพื่อ Approve และจบ session
          </div>
        </>
      )}
    </div>
  )
}

function ClassBadge({ value }: { value: 'generic' | 'specific' }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
      value === 'specific' ? 'bg-indigo-100 text-indigo-700' : 'bg-teal-100 text-teal-700'
    }`}>
      {value}
    </span>
  )
}

function ReportGroup({
  title,
  plos,
  onFlip,
}: {
  title: string
  plos: PLO[]
  onFlip: (p: PLO) => void
}) {
  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide mb-3">
        {title} ({plos.length})
      </h2>
      {plos.length === 0 ? (
        <p className="text-gray-400 text-sm">— ไม่มี —</p>
      ) : (
        <div className="space-y-3">
          {plos.map(p => {
            const cls = effectiveClass(p)
            return (
              <div key={p.plo_id} className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1.5">
                      <span className="text-xs font-mono text-gray-400 bg-gray-50 px-2 py-0.5 rounded">{p.plo_id}</span>
                      <ClassBadge value={cls} />
                      {p.classification_method && (
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${METHOD_COLOR[p.classification_method]}`}>
                          {METHOD_LABEL[p.classification_method]}
                        </span>
                      )}
                    </div>
                    <p className="text-gray-900 font-medium leading-relaxed">{p.statement_th}</p>
                    {p.classification_rationale_th && (
                      <p className="text-gray-500 text-sm mt-1 italic">{p.classification_rationale_th}</p>
                    )}
                  </div>
                  <button
                    onClick={() => onFlip(p)}
                    className="shrink-0 text-sm border border-gray-200 px-3 py-1.5 rounded-lg hover:bg-gray-50 text-gray-600"
                  >
                    → {cls === 'specific' ? 'generic' : 'specific'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function ReportMatrix({ plos, clusters }: { plos: PLO[]; clusters: SkillCluster[] }) {
  if (clusters.length === 0) {
    return <p className="text-gray-400 text-sm">ไม่มี cluster ที่ PLO อ้างอิง</p>
  }
  return (
    <div className="overflow-x-auto border border-gray-200 rounded-xl">
      <table className="text-sm border-collapse">
        <thead>
          <tr className="bg-gray-50">
            <th className="sticky left-0 bg-gray-50 text-left px-3 py-2 font-semibold text-gray-600 border-b border-gray-200">
              PLO
            </th>
            <th className="px-3 py-2 font-semibold text-gray-600 border-b border-gray-200">Class</th>
            {clusters.map(c => (
              <th
                key={c.cluster_id}
                className="px-3 py-2 font-medium text-gray-500 border-b border-gray-200 whitespace-nowrap text-xs"
                title={c.canonical_name_th}
              >
                {c.canonical_name_en ?? c.canonical_name_th}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {plos.map(p => (
            <tr key={p.plo_id} className="hover:bg-gray-50">
              <td className="sticky left-0 bg-white hover:bg-gray-50 px-3 py-2 font-mono text-xs text-gray-600 border-b border-gray-100 whitespace-nowrap">
                {p.plo_id}
              </td>
              <td className="px-3 py-2 border-b border-gray-100 text-center">
                <ClassBadge value={effectiveClass(p)} />
              </td>
              {clusters.map(c => (
                <td key={c.cluster_id} className="px-3 py-2 border-b border-gray-100 text-center">
                  {p.source_cluster_ids.includes(c.cluster_id)
                    ? <span className="text-green-600 font-bold">✓</span>
                    : <span className="text-gray-200">·</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 2: Swap the nav entry in `StageLayout.tsx`**

In `frontend/src/components/StageLayout.tsx`, replace the YLO line in the `stages` array (line 8):

```tsx
  { path: '/plo-report', label: 'Stage 5: PLO Report' },
```

(Replace `{ path: '/ylo-derivation', label: 'Stage 5: YLO Derivation' },` with the line above. The `/pipeline` entry stays.)

- [ ] **Step 3: Add the route in `App.tsx`**

Replace `frontend/src/App.tsx` with (adds `PloReport` import + `/plo-report` route, keeps `/ylo-derivation`):

```tsx
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import StageLayout from './components/StageLayout'
import Intake from './pages/Intake'
import StakeholderNeeds from './pages/StakeholderNeeds'
import SkillExtraction from './pages/SkillExtraction'
import PloSynthesis from './pages/PloSynthesis'
import PloReport from './pages/PloReport'
import YloDerivation from './pages/YloDerivation'
import Pipeline from './pages/Pipeline'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<StageLayout />}>
          <Route index element={<Intake />} />
          <Route path="stakeholder-needs" element={<StakeholderNeeds />} />
          <Route path="skill-extraction" element={<SkillExtraction />} />
          <Route path="plo-synthesis" element={<PloSynthesis />} />
          <Route path="plo-report" element={<PloReport />} />
          <Route path="ylo-derivation" element={<YloDerivation />} />
          <Route path="pipeline" element={<Pipeline />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
```

- [ ] **Step 4: Point the PLO Synthesis "next" link to the report**

In `frontend/src/pages/PloSynthesis.tsx`, change the `Link` target (line 185) and its label:

```tsx
            <Link
              to="/plo-report"
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm font-medium transition-colors"
            >
              ดำเนินการต่อ → PLO Report
            </Link>
```

- [ ] **Step 5: Verify the frontend builds**

Run: `cd frontend && npm run build`
Expected: build succeeds, no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/PloReport.tsx frontend/src/components/StageLayout.tsx frontend/src/App.tsx frontend/src/pages/PloSynthesis.tsx
git commit -m "feat: add PLO Report page with list and matrix views, swap nav from YLO"
```

---

## Task 8: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full Python test suite**

Run: `uv run pytest`
Expected: all PASS (new tests + existing 40+).

- [ ] **Step 2: Lint and type-check**

Run: `uv run ruff check src/ tests/` then `uv run ruff format --check src/ tests/` then `uv run mypy src/`
Expected: clean. Fix any reported issues and re-run.

- [ ] **Step 3: Commit any lint fixes**

```bash
git add -A
git commit -m "chore: lint and format for PLO report feature"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Detach YLO from graph, keep code | Task 5 (remove edges/add_node, keep functions) |
| New `plo_report` node + `review_plo_report` interrupt | Task 5 |
| PLO model: `classification`, `classification_method`, `classification_rationale_th` | Task 1 |
| PLOTable columns + migration | Task 2 |
| Method D: field fraction first, LLM fallback when ambiguous/no clusters | Task 4 |
| `is_subject_specific` ⟺ `classification` sync (stage) | Task 4 |
| Classification prompt builder (light model, cluster summaries) | Task 3 |
| `POST /plos/report/run` | Task 6 |
| `PUT /plos/{id}` sets method=manual + server-side sync | Task 6 |
| Frontend grouped list view | Task 7 (`ReportGroup`) |
| Frontend PLO×Cluster matrix view | Task 7 (`ReportMatrix`) |
| Inline flip generic⟷specific | Task 7 (`flip`) |
| Nav swap YLO→PLO Report, keep /ylo-derivation route | Task 7 |
| PLO Synthesis "next" → /plo-report | Task 7 |
| Sync-invariant + ambiguous/no-cluster tests | Task 4 |

**Placeholder scan:** none — every code step contains full content.

**Type consistency:** `_ClassificationResult(classification, rationale_th)` defined in Task 4 and imported in its tests; `classification`/`classification_method`/`classification_rationale_th` field names identical across model (Task 1), ORM (Task 2), stage (Task 4), route (Task 6), and TS interface (Task 7). `effectiveClass` used consistently in `PloReport`, `ReportGroup`, `ReportMatrix`. Stage wrapper `stage_5_plo_report` + `review_plo_report` names match between Task 5 definitions and `build_graph`.

**Note on YLO `AgentState.ylo_matrix`:** retained in state schema (unused) — no task removes it, consistent with "keep YLO code" decision.
