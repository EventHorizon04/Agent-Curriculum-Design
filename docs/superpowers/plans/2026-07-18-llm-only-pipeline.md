# LLM-Only Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the NLP stack (PyThaiNLP, KeyBERT, BGE-M3, KMeans, Qdrant) with pure-LLM clustering in the skill-extraction stage.

**Architecture:** Skill extraction already uses the LLM per evidence item. The KeyBERT backup signal, embedding+KMeans clustering, and all Qdrant writes are removed. A new `llm_clustering` module dedupes skill names in pure code, then asks the heavy model (Qwen) to group them — single pass for ≤150 unique names, batch+merge above that. Everything downstream (cluster naming, Bloom tagging, demand score) is unchanged.

**Tech Stack:** Python 3.11, Pydantic v2, Instructor → Ollama (existing `complete_heavy`), pytest (asyncio_mode=auto), uv.

**Spec:** `docs/superpowers/specs/2026-07-18-llm-only-pipeline-design.md`

## Global Constraints

- Branch: `experiment/llm-only-pipeline` (already checked out)
- `from __future__ import annotations` + full type hints in every Python file
- `loguru` for logging, never stdlib `logging`
- LLM output only via Instructor + Pydantic — no hand-parsing JSON
- Thai for LLM prompt content; English for code/comments/log messages
- `extraction_method` Literal in `models.py` keeps `"keybert"` value (existing DB rows) — do NOT change `models.py`
- `SkillCluster` schema and `_compute_demand_score` are unchanged
- Tests: `uv run pytest` — no `@pytest.mark.asyncio` needed (asyncio_mode=auto)
- Commit messages end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: Pure clustering helpers

**Files:**
- Create: `src/curriculum_agent/stages/llm_clustering.py`
- Test: `tests/unit/test_llm_clustering.py`

**Interfaces:**
- Produces (used by Tasks 3, 4):
  - `normalize_name(name: str) -> str`
  - `dedupe_names(names: list[str]) -> tuple[list[str], list[list[int]]]`
  - `split_batches(items: list[str], size: int = BATCH_SIZE) -> list[list[str]]`
  - `validate_assignments(clusters: list[tuple[str, list[int]]], names: list[str]) -> list[tuple[str, list[int]]]`
  - Constants `SINGLE_PASS_MAX = 150`, `BATCH_SIZE = 100`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_llm_clustering.py`:

```python
from __future__ import annotations

from curriculum_agent.stages.llm_clustering import (
    dedupe_names,
    normalize_name,
    split_batches,
    validate_assignments,
)


def test_normalize_name_lowercases_and_collapses_whitespace():
    assert normalize_name("  Python   Programming ") == "python programming"
    assert normalize_name("การสื่อสาร") == "การสื่อสาร"


def test_dedupe_names_collapses_duplicates_and_tracks_indices():
    names = ["Python", "  python ", "SQL", "การสื่อสาร", "sql"]
    unique, groups = dedupe_names(names)
    # sorted by normalized form; Thai sorts after latin here
    assert unique == ["Python", "SQL", "การสื่อสาร"]
    assert groups == [[0, 1], [2, 4], [3]]


def test_dedupe_names_empty():
    assert dedupe_names([]) == ([], [])


def test_split_batches_splits_at_size():
    items = [str(i) for i in range(250)]
    batches = split_batches(items, size=100)
    assert [len(b) for b in batches] == [100, 100, 50]
    assert batches[2][0] == "200"


def test_validate_assignments_passes_clean_input_through():
    names = ["a", "b", "c"]
    clusters = [("g1", [0, 2]), ("g2", [1])]
    assert validate_assignments(clusters, names) == [("g1", [0, 2]), ("g2", [1])]


def test_validate_assignments_drops_hallucinated_and_duplicate_indices():
    names = ["a", "b"]
    clusters = [("g1", [0, 5, -1]), ("g2", [0, 1])]
    # index 5 and -1 out of range; second 0 already seen
    assert validate_assignments(clusters, names) == [("g1", [0]), ("g2", [1])]


def test_validate_assignments_missing_index_becomes_singleton():
    names = ["a", "b", "c"]
    clusters = [("g1", [0])]
    result = validate_assignments(clusters, names)
    assert ("g1", [0]) in result
    assert ("b", [1]) in result
    assert ("c", [2]) in result
    assert len(result) == 3


def test_validate_assignments_empty_group_dropped():
    names = ["a"]
    clusters = [("empty", []), ("g1", [0])]
    assert validate_assignments(clusters, names) == [("g1", [0])]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_llm_clustering.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.stages.llm_clustering'`

- [ ] **Step 3: Write the implementation**

Create `src/curriculum_agent/stages/llm_clustering.py`:

```python
from __future__ import annotations

import re

from loguru import logger

SINGLE_PASS_MAX = 150
BATCH_SIZE = 100

_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Lowercase, trim, collapse internal whitespace."""
    return _WS.sub(" ", name.strip()).lower()


def dedupe_names(names: list[str]) -> tuple[list[str], list[list[int]]]:
    """Collapse duplicate skill names by normalized form.

    Returns (unique_names, groups). unique_names is sorted by normalized form
    so prompts and cache keys are deterministic regardless of input order;
    groups[i] lists the indices in `names` that normalize to unique_names[i].
    The first-seen raw spelling (trimmed) is kept as the display name.
    """
    by_norm: dict[str, list[int]] = {}
    display: dict[str, str] = {}
    for i, raw in enumerate(names):
        norm = normalize_name(raw)
        by_norm.setdefault(norm, []).append(i)
        display.setdefault(norm, raw.strip())
    ordered = sorted(by_norm)
    return [display[k] for k in ordered], [by_norm[k] for k in ordered]


def split_batches(items: list[str], size: int = BATCH_SIZE) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def validate_assignments(
    clusters: list[tuple[str, list[int]]], names: list[str]
) -> list[tuple[str, list[int]]]:
    """Enforce that every index into `names` is assigned exactly once.

    Out-of-range and already-assigned indices are dropped; indices the LLM
    never assigned become singleton clusters labeled with the skill name —
    skills are never silently dropped.
    """
    n = len(names)
    seen: set[int] = set()
    dropped = 0
    cleaned: list[tuple[str, list[int]]] = []
    for label, indices in clusters:
        keep = [i for i in indices if 0 <= i < n and i not in seen]
        dropped += len(indices) - len(keep)
        seen.update(keep)
        if keep:
            cleaned.append((label, keep))
    missing = [i for i in range(n) if i not in seen]
    cleaned.extend((names[i], [i]) for i in missing)
    if dropped:
        logger.warning(f"LLM clustering: dropped {dropped} invalid/duplicate indices")
    if missing:
        logger.warning(
            f"LLM clustering: {len(missing)} skills unassigned — added as singletons"
        )
    return cleaned
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_llm_clustering.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/stages/llm_clustering.py tests/unit/test_llm_clustering.py
git commit -m "feat(clustering): pure helpers for LLM-based skill clustering

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Clustering prompt builders

**Files:**
- Create: `src/curriculum_agent/prompts/cluster_skills.py`
- Test: `tests/unit/test_cluster_skills_prompt.py`

**Interfaces:**
- Produces (used by Task 3):
  - `build_cluster_skills_prompt(skill_names: list[str]) -> list[dict[str, str]]`
  - `build_merge_clusters_prompt(cluster_labels: list[str]) -> list[dict[str, str]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cluster_skills_prompt.py`:

```python
from __future__ import annotations

from curriculum_agent.prompts.cluster_skills import (
    build_cluster_skills_prompt,
    build_merge_clusters_prompt,
)


def test_cluster_prompt_numbers_every_skill():
    msgs = build_cluster_skills_prompt(["Python", "SQL", "การสื่อสาร"])
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    assert "0: Python" in user
    assert "1: SQL" in user
    assert "2: การสื่อสาร" in user
    # system prompt must state the exactly-once rule and JSON shape
    system = msgs[0]["content"]
    assert "member_indices" in system
    assert "label_th" in system


def test_merge_prompt_numbers_every_label():
    msgs = build_merge_clusters_prompt(["โปรแกรมมิ่ง", "Programming", "สื่อสาร"])
    user = msgs[1]["content"]
    assert "0: โปรแกรมมิ่ง" in user
    assert "2: สื่อสาร" in user
    assert "groups" in msgs[0]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_cluster_skills_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curriculum_agent.prompts.cluster_skills'`

- [ ] **Step 3: Write the implementation**

Create `src/curriculum_agent/prompts/cluster_skills.py` (follows the same builder pattern as `name_cluster.py`):

```python
from __future__ import annotations


def build_cluster_skills_prompt(skill_names: list[str]) -> list[dict[str, str]]:
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ทักษะแรงงาน\n"
        "จงจัดกลุ่มทักษะต่อไปนี้ตามความหมายและบริบทการใช้งาน "
        "ทักษะที่ใช้ในงานลักษณะเดียวกันหรือความหมายใกล้เคียงกันควรอยู่กลุ่มเดียวกัน\n\n"
        "กติกา:\n"
        "- ทุก index ต้องถูกจัดเข้ากลุ่มครั้งเดียวเท่านั้น ห้ามซ้ำ ห้ามตกหล่น\n"
        "- ห้ามใช้ index ที่ไม่มีในรายการ\n"
        "- จำนวนกลุ่มตามความเหมาะสมของข้อมูล (โดยทั่วไป 4-12 กลุ่ม)\n\n"
        "ตอบเป็น JSON object:\n"
        "{ clusters: [ { label_th: ชื่อกลุ่มภาษาไทยสั้นๆ, "
        "member_indices: [index ของทักษะในกลุ่มนี้] } ] }"
    )
    numbered = "\n".join(f"{i}: {name}" for i, name in enumerate(skill_names))
    user = f"รายการทักษะ (index: ชื่อทักษะ):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_merge_clusters_prompt(cluster_labels: list[str]) -> list[dict[str, str]]:
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ทักษะแรงงาน\n"
        "รายการต่อไปนี้คือชื่อกลุ่มทักษะที่ได้จากการจัดกลุ่มทีละชุด "
        "บางกลุ่มมีความหมายเดียวกันและควรรวมเป็นกลุ่มเดียว\n\n"
        "กติกา:\n"
        "- ทุก index ต้องปรากฏใน groups ครั้งเดียวเท่านั้น\n"
        "- กลุ่มที่ไม่ซ้ำกับกลุ่มอื่นให้อยู่เดี่ยวๆ เป็น group ของตัวเอง\n\n"
        "ตอบเป็น JSON object:\n"
        "{ groups: [ [index ของกลุ่มที่ควรรวมเข้าด้วยกัน] ] }"
    )
    numbered = "\n".join(f"{i}: {label}" for i, label in enumerate(cluster_labels))
    user = f"รายการกลุ่มทักษะ (index: ชื่อกลุ่ม):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_cluster_skills_prompt.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/prompts/cluster_skills.py tests/unit/test_cluster_skills_prompt.py
git commit -m "feat(prompts): cluster_skills and merge_clusters prompt builders

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `cluster_skill_names` orchestrator

**Files:**
- Modify: `src/curriculum_agent/stages/llm_clustering.py` (append to Task 1 file)
- Test: `tests/unit/test_llm_clustering.py` (append)

**Interfaces:**
- Consumes: Task 1 helpers, Task 2 prompt builders, existing `complete_heavy` from `curriculum_agent.llm`, existing `LLMCacheRepository` (`await get(key) -> tuple[model, json_str] | None`, `await set(key, model, json_str)`)
- Produces (used by Task 4): `async cluster_skill_names(names: list[str]) -> list[list[int]]` — groups of indices into `names`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_llm_clustering.py`:

```python
from unittest.mock import AsyncMock, patch

from curriculum_agent.config import settings
from curriculum_agent.stages.llm_clustering import (
    ClusterAssignment,
    ClusterAssignmentsResponse,
    MergeGroupsResponse,
    cluster_skill_names,
)


def _mock_cache(hit: str | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get = AsyncMock(
        return_value=(settings.heavy_model, hit) if hit is not None else None
    )
    repo.set = AsyncMock()
    return repo


async def test_cluster_skill_names_empty_and_singleton_short_circuit():
    with patch(
        "curriculum_agent.stages.llm_clustering.complete_heavy", new=AsyncMock()
    ) as llm:
        assert await cluster_skill_names([]) == []
        assert await cluster_skill_names(["Python"]) == [[0]]
    llm.assert_not_called()


async def test_single_pass_clusters_validates_and_caches():
    resp = ClusterAssignmentsResponse(
        clusters=[
            ClusterAssignment(label_th="โปรแกรมมิ่ง", member_indices=[0, 1]),
            ClusterAssignment(label_th="สื่อสาร", member_indices=[2, 99]),  # 99 hallucinated
        ]
    )
    cache = _mock_cache()
    with (
        patch(
            "curriculum_agent.stages.llm_clustering.complete_heavy",
            new=AsyncMock(return_value=resp),
        ) as llm,
        patch(
            "curriculum_agent.stages.llm_clustering.LLMCacheRepository",
            return_value=cache,
        ),
    ):
        groups = await cluster_skill_names(["Python", "SQL", "การสื่อสาร"])

    assert groups == [[0, 1], [2]]
    assert llm.call_args.kwargs.get("temperature") == 0
    cache.set.assert_called_once()


async def test_cache_hit_skips_llm():
    cache = _mock_cache(hit="[[0, 2], [1]]")
    with (
        patch(
            "curriculum_agent.stages.llm_clustering.complete_heavy", new=AsyncMock()
        ) as llm,
        patch(
            "curriculum_agent.stages.llm_clustering.LLMCacheRepository",
            return_value=cache,
        ),
    ):
        groups = await cluster_skill_names(["a", "b", "c"])
    assert groups == [[0, 2], [1]]
    llm.assert_not_called()
    cache.set.assert_not_called()


async def test_map_reduce_path_batches_then_merges():
    names = [f"skill-{i}" for i in range(160)]  # > SINGLE_PASS_MAX → 2 batches (100+60)
    batch_sizes = iter([100, 60])

    async def dispatch(response_model, messages, **kwargs):
        if response_model is ClusterAssignmentsResponse:
            size = next(batch_sizes)
            return ClusterAssignmentsResponse(
                clusters=[
                    ClusterAssignment(label_th="กลุ่ม", member_indices=list(range(size)))
                ]
            )
        if response_model is MergeGroupsResponse:
            return MergeGroupsResponse(groups=[[0, 1]])
        raise AssertionError(f"unexpected response_model {response_model}")

    cache = _mock_cache()
    with (
        patch(
            "curriculum_agent.stages.llm_clustering.complete_heavy",
            new=AsyncMock(side_effect=dispatch),
        ) as llm,
        patch(
            "curriculum_agent.stages.llm_clustering.LLMCacheRepository",
            return_value=cache,
        ),
    ):
        groups = await cluster_skill_names(names)

    assert llm.call_count == 3  # 2 batch passes + 1 merge
    assert groups == [sorted(range(160))]
    cache.set.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_llm_clustering.py -v`
Expected: new tests FAIL — `ImportError: cannot import name 'ClusterAssignment'`

- [ ] **Step 3: Write the implementation**

Append to `src/curriculum_agent/stages/llm_clustering.py`. Add these imports at the top of the file:

```python
import hashlib
import json

from pydantic import BaseModel, Field

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import LLMCacheRepository
from curriculum_agent.llm import complete_heavy
from curriculum_agent.prompts.cluster_skills import (
    build_cluster_skills_prompt,
    build_merge_clusters_prompt,
)
```

Then append:

```python
class ClusterAssignment(BaseModel):
    label_th: str
    member_indices: list[int] = Field(default_factory=list)


class ClusterAssignmentsResponse(BaseModel):
    clusters: list[ClusterAssignment]


class MergeGroupsResponse(BaseModel):
    groups: list[list[int]]


async def _cluster_pass(names: list[str]) -> list[tuple[str, list[int]]]:
    """One heavy-model clustering call over `names`, validated."""
    result = await complete_heavy(
        ClusterAssignmentsResponse,
        build_cluster_skills_prompt(names),
        temperature=0,
    )
    return validate_assignments(
        [(c.label_th, c.member_indices) for c in result.clusters], names
    )


async def _cluster_map_reduce(names: list[str]) -> list[list[int]]:
    """Cluster per batch, then merge equivalent cluster labels across batches."""
    labelled: list[tuple[str, list[int]]] = []
    offset = 0
    for batch in split_batches(names):
        for label, indices in await _cluster_pass(batch):
            labelled.append((label, [offset + i for i in indices]))
        offset += len(batch)

    labels = [label for label, _ in labelled]
    merge = await complete_heavy(
        MergeGroupsResponse,
        build_merge_clusters_prompt(labels),
        temperature=0,
    )
    merged = validate_assignments([("", g) for g in merge.groups], labels)
    return [
        sorted(i for ci in group for i in labelled[ci][1]) for _, group in merged
    ]


async def cluster_skill_names(names: list[str]) -> list[list[int]]:
    """Group skill names by meaning using the heavy model.

    Returns groups of indices into `names`. Single pass when the list fits in
    one prompt; batch + merge otherwise. Results are cached keyed on the full
    name list + model, so re-runs on identical input are deterministic.
    """
    if not names:
        return []
    if len(names) == 1:
        return [[0]]

    cache = LLMCacheRepository()
    cache_key = hashlib.sha256(
        "\x00".join([*names, settings.heavy_model]).encode()
    ).hexdigest()
    cached = await cache.get(cache_key)
    if cached is not None and cached[0] == settings.heavy_model:
        return [[int(i) for i in g] for g in json.loads(cached[1])]

    if len(names) <= SINGLE_PASS_MAX:
        groups = [indices for _, indices in await _cluster_pass(names)]
    else:
        groups = await _cluster_map_reduce(names)

    await cache.set(cache_key, settings.heavy_model, json.dumps(groups))
    return groups
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_llm_clustering.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/stages/llm_clustering.py tests/unit/test_llm_clustering.py
git commit -m "feat(clustering): LLM cluster orchestrator with cache and map-reduce

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Rewire skill_extraction to LLM clustering

**Files:**
- Modify: `src/curriculum_agent/stages/skill_extraction.py`
- Modify: `tests/unit/test_skill_extraction_cache.py`
- Modify: `tests/unit/test_cluster_bloom.py`

**Interfaces:**
- Consumes: `dedupe_names`, `cluster_skill_names` from `curriculum_agent.stages.llm_clustering`
- Produces: `run(state)` keeps its exact existing signature and state keys (`extracted_skills`, `skill_clusters`, `current_stage`)

- [ ] **Step 1: Update the two test files first (failing tests)**

In `tests/unit/test_skill_extraction_cache.py`:
- Delete the `mock_qdrant = MagicMock()` block (lines 61-64) and the three `patch(...)` blocks for `extract_keywords`, `embed`, `get_qdrant` (lines 75-86).
- Change the import on line 4 to `from unittest.mock import AsyncMock, patch` (MagicMock no longer used).
- Add this patch block inside the same `with (...)` where the removed ones were:

```python
        patch(
            "curriculum_agent.stages.skill_extraction.cluster_skill_names",
            new=AsyncMock(return_value=[[0]]),
        ),
```

In `tests/unit/test_cluster_bloom.py` apply the same change inside `_run_stage_with_mocked_llm`:
- Delete the `mock_qdrant = MagicMock()` block (lines 95-98) and the `patch(...)` blocks for `extract_keywords`, `embed`, `get_qdrant` (lines 109-120).
- Change line 3 to `from unittest.mock import AsyncMock, patch`.
- Add the same `cluster_skill_names` patch block shown above.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_skill_extraction_cache.py tests/unit/test_cluster_bloom.py -v`
Expected: FAIL — `AttributeError: <module ...skill_extraction> does not have the attribute 'cluster_skill_names'`

- [ ] **Step 3: Rewrite skill_extraction.py**

Modify `src/curriculum_agent/stages/skill_extraction.py`:

**Replace the import block (lines 1-35)** with:

```python
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    ClusterRepository,
    LLMCacheRepository,
    SkillRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import (
    ExtractedSkill,
    SkillCluster,
    SkillType,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.prompts.classify_cluster_bloom import build_cluster_bloom_prompt
from curriculum_agent.prompts.name_cluster import build_name_cluster_prompt
from curriculum_agent.stages.llm_clustering import cluster_skill_names, dedupe_names
```

(Removed: `asyncio`, `numpy`, `qdrant_client.models`, `sklearn.cluster.KMeans`, `curriculum_agent.data.qdrant`, `curriculum_agent.nlp.*`, `_EMBED_DIM`.)

**Keep unchanged:** `_SkillItem`, `_ExtractedSkillsResponse`, `_ClusterNameResult`, `_ClusterBloomResult`, `_EXTRACT_SYSTEM`, `_WEIGHTED_CLASSES`, `_compute_demand_score`.

**Delete:** `_ensure_skill_collection` (lines 85-93).

**In `run()`:**

1. Update the docstring to: `"""Stage 2: extract skills from evidence, cluster with the heavy LLM, name clusters."""`
2. Delete the whole `# --- Step 2: KeyBERT backup signal ---` block (lines 174-194).
3. Replace the block from `skill_texts = [s.skill_name_th for s in extracted]` through `labels = kmeans.fit_predict(matrix)` (lines 221-232) with:

```python
    # --- Step 3: LLM clustering over deduped skill names ---
    unique_names, name_groups = dedupe_names([s.skill_name_th for s in extracted])
    logger.info(f"Clustering {len(unique_names)} unique skills via heavy model")
    unique_clusters = await cluster_skill_names(unique_names)
    member_indices_per_cluster = [
        sorted({orig for u in group for orig in name_groups[u]})
        for group in unique_clusters
    ]
```

4. Replace the cluster loop header (lines 243-249):

```python
    for cluster_idx in range(n_clusters):
        member_indices = [i for i, lbl in enumerate(labels) if lbl == cluster_idx]
        if not member_indices:
            continue

        member_skills = [extracted[i] for i in member_indices]
```

with:

```python
    for cluster_idx, member_indices in enumerate(member_indices_per_cluster):
        member_skills = [extracted[i] for i in member_indices]
```

The rest of the loop body is unchanged.

5. Delete the whole Qdrant centroid upsert block — from `# Upsert cluster centroids to Qdrant` through `await client.upsert(collection_name=SKILL_COLLECTION, points=points)` (lines 334-354). The Postgres `bulk_insert` calls above it stay.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_skill_extraction_cache.py tests/unit/test_cluster_bloom.py tests/unit/test_llm_clustering.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/stages/skill_extraction.py tests/unit/test_skill_extraction_cache.py tests/unit/test_cluster_bloom.py
git commit -m "refactor(skill-extraction): replace KeyBERT+KMeans+Qdrant with LLM clustering

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Remove embeddings/Qdrant from stakeholder_needs

**Files:**
- Modify: `src/curriculum_agent/stages/stakeholder_needs.py`
- Modify: `tests/integration/test_end_to_end.py`

**Interfaces:**
- Produces: `run(state)` and `classify_single(evidence)` keep their exact existing signatures

- [ ] **Step 1: Update the integration test first (failing test)**

In `tests/integration/test_end_to_end.py`, delete the three patch blocks for `stakeholder_needs._ensure_collection`, `stakeholder_needs.embed`, and `stakeholder_needs.get_qdrant` (lines 106-117).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_end_to_end.py -v`
Expected: FAIL — the graph run raises trying to reach Qdrant/BGE-M3 (connection or import error), because the stage still calls `_embed_and_upsert` unmocked

- [ ] **Step 3: Clean up the stage**

Modify `src/curriculum_agent/stages/stakeholder_needs.py`:

- Delete imports: `qdrant_client.models` (line 7), `curriculum_agent.data.qdrant` (line 9), `curriculum_agent.nlp.embedding` (line 14), and the `_EMBED_DIM` constant (line 17).
- Delete `_ensure_collection` (lines 25-33) and `_embed_and_upsert` (lines 48-66).
- In `run()`, change the docstring to `"""Stage 1: classify unclassified evidence, persist to Postgres."""` and replace:

```python
    if newly_classified:
        repo = EvidenceRepository()
        await repo.bulk_insert(newly_classified)
        await _embed_and_upsert(newly_classified)
```

with:

```python
    if newly_classified:
        repo = EvidenceRepository()
        await repo.bulk_insert(newly_classified)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/test_end_to_end.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/stages/stakeholder_needs.py tests/integration/test_end_to_end.py
git commit -m "refactor(stakeholder-needs): drop write-only Qdrant/embedding step

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Delete nlp package, qdrant client, BGE warmup

**Files:**
- Delete: `src/curriculum_agent/nlp/` (entire directory)
- Delete: `src/curriculum_agent/data/qdrant.py`
- Modify: `src/curriculum_agent/api/main.py`
- Modify: `src/curriculum_agent/config.py`

- [ ] **Step 1: Verify nothing still imports the doomed modules**

Run: `grep -rn "curriculum_agent.nlp\|data.qdrant\|data import qdrant" src/ tests/ --include="*.py"`
Expected: only hits inside `src/curriculum_agent/nlp/` itself and `api/main.py` line 39 (fixed below). If any other file matches, fix it before deleting.

- [ ] **Step 2: Fix api/main.py warmup**

In `src/curriculum_agent/api/main.py`, replace lines 38-51:

```python
        from curriculum_agent.llm import warmup_models
        from curriculum_agent.nlp.embedding import get_model

        async def _warmup_bge() -> None:
            await asyncio.to_thread(get_model)
            logger.info("BGE-M3 embedding model loaded into RAM")

        warmup_results = await asyncio.gather(
            _warmup_bge(), warmup_models(), return_exceptions=True
        )
        for _r in warmup_results:
            if isinstance(_r, BaseException):
                logger.warning(f"Startup warm-up failed: {_r}")
        logger.info("Model pre-warm complete")
```

with:

```python
        from curriculum_agent.llm import warmup_models

        try:
            await warmup_models()
        except Exception as exc:
            logger.warning(f"Startup warm-up failed: {exc}")
        logger.info("Model pre-warm complete")
```

Keep the `import asyncio` at the top — it is still used for the Windows event-loop policy.

- [ ] **Step 3: Remove qdrant_url from config**

In `src/curriculum_agent/config.py`, delete the line:

```python
    qdrant_url: str = "http://localhost:6333"
```

- [ ] **Step 4: Delete the modules**

```bash
git rm -r src/curriculum_agent/nlp
git rm src/curriculum_agent/data/qdrant.py
```

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest`
Expected: all pass, no ImportError anywhere

- [ ] **Step 6: Commit**

```bash
git add -A src/curriculum_agent
git commit -m "refactor: delete nlp package, qdrant client, and BGE-M3 warmup

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Dependencies, infra, docs, final verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `docker-compose.yml`
- Modify: `scripts/start-dev.ps1`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Trim pyproject.toml**

Remove from `[project.dependencies]`: `qdrant-client>=1.8`, `pythainlp>=5.0`, `sentence-transformers>=2.5`, `keybert>=0.8`, `bertopic>=0.16` (unused — nothing imports it), `scikit-learn>=1.4`.

Delete the whole `gpu` optional-dependency group (torch was only for embeddings):

```toml
[project.optional-dependencies]
gpu = [
    "torch>=2.1",
]
```

becomes just `[project.optional-dependencies]` with the `dev` group. Also delete the mypy override block:

```toml
# No published stubs or py.typed marker for these libraries.
[[tool.mypy.overrides]]
module = ["keybert", "keybert.*", "sklearn", "sklearn.*"]
ignore_missing_imports = true
```

- [ ] **Step 2: Trim docker-compose.yml**

Delete the `qdrant:` service block (lines 15-23) and the `qdrant-data:` volume line.

- [ ] **Step 3: Update start-dev.ps1**

- Line 6: `Checks prerequisites, starts postgres/qdrant/minio via Docker Compose,` → `Checks prerequisites, starts postgres/minio via Docker Compose,`
- Line 45: `Write-Step "Starting DB services (postgres, qdrant, minio)..."` → `Write-Step "Starting DB services (postgres, minio)..."`
- Delete line 83: `Write-Host "  Qdrant:        http://localhost:6333"`

- [ ] **Step 4: Update CLAUDE.md for this branch**

In the Stack section:
- Change the Thai NLP line `- **Thai NLP:** PyThaiNLP for tokenization, BGE-M3 for embeddings` and the skill-extraction line `- **Skill extraction:** KeyBERT + scikit-learn` and the vector-store line `- **Vector store:** Qdrant` to a single line: `- **Clustering:** LLM-based (heavy model) — no embeddings/KeyBERT/Qdrant on this branch; see docs/superpowers/specs/2026-07-18-llm-only-pipeline-design.md`
- In Deployment line, drop `qdrant` from the Docker services list.
- In Project layout, remove the `nlp/` line and add `llm_clustering` next to the stages entry.

- [ ] **Step 5: Sync and full verification**

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/
```

Expected: lockfile updated (packages removed), all tests pass, ruff clean, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock docker-compose.yml scripts/start-dev.ps1 CLAUDE.md
git commit -m "chore: drop NLP/Qdrant dependencies and services for LLM-only branch

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Verification checklist (end of plan)

- `uv run pytest` — all green
- `uv run ruff check src/ tests/` and `uv run mypy src/` — clean
- `docker compose config --services` lists only postgres, minio, pgadmin
- `grep -rn "keybert\|sklearn\|pythainlp\|sentence_transformers\|qdrant" src/ tests/ --include="*.py"` — only the harmless `"keybert"` Literal value in `models.py`
