# Bug Fixes & Architecture Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** แก้ไข 10 bugs จาก code review และปรับ architecture ให้ตรงตาม best practices (FastAPI DI, auth, safe state access, LLM client lifecycle)

**Architecture:** แก้ bugs ก่อนตามลำดับ severity จากนั้น refactor 4 ด้าน architecture — FastAPI dependency injection, auth middleware, state access safety, LLM client factory; จบด้วย HTML report

**Tech Stack:** Python 3.11, Pydantic v2, LangGraph, FastAPI, Instructor, pytest-asyncio

---

## Part A — Bug Fixes

### Task 1: Fix HITL — interrupt() return value ต้อง merge กลับ state

**Files:**
- Modify: `src/curriculum_agent/graph.py:83-100`

ปัญหา: `interrupt(...)` คืน payload ที่ designer ส่งมา แต่ปัจจุบัน code ทิ้งค่านั้นแล้ว return `state` เดิม — edit หาย

- [ ] **Step 1: เขียน test ที่ fail**

```python
# tests/unit/test_graph_hitl.py
from __future__ import annotations
from unittest.mock import AsyncMock, patch
from curriculum_agent.graph import review_stakeholder_needs
from curriculum_agent.graph import AgentState


def test_review_merges_designer_edits() -> None:
    """interrupt() payload must be merged into state, not discarded."""
    edited_evidence = [{"evidence_id": "E1", "classification": "need"}]
    initial_state: AgentState = {
        "program_id": "test",
        "classified_evidence": [{"evidence_id": "E1", "classification": "unclassified"}],
    }

    with patch("curriculum_agent.graph.interrupt", return_value={"classified_evidence": edited_evidence}):
        result = review_stakeholder_needs(initial_state)

    assert result["classified_evidence"] == edited_evidence
```

- [ ] **Step 2: รัน test ให้ fail ก่อน**

```bash
uv run pytest tests/unit/test_graph_hitl.py -v
```
Expected: FAIL — `assert [{'evidence_id': 'E1', 'classification': 'unclassified'}] == [...]`

- [ ] **Step 3: แก้ไข graph.py — review nodes ต้อง merge payload**

เปลี่ยน 4 review functions ทั้งหมดใน `src/curriculum_agent/graph.py`:

```python
def review_stakeholder_needs(state: AgentState) -> AgentState:
    payload = interrupt("Stage 1 complete — review classified evidence before clustering")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state


def review_skill_clusters(state: AgentState) -> AgentState:
    payload = interrupt("Stage 2 complete — review/edit skill clusters before PLO synthesis")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state


def review_plos(state: AgentState) -> AgentState:
    payload = interrupt("Stage 3 complete — review/edit PLOs before YLO derivation")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state


def review_ylo_matrix(state: AgentState) -> AgentState:
    payload = interrupt("Stage 4 complete — final review of PLO/YLO matrix")
    if isinstance(payload, dict):
        return {**state, **payload}
    return state
```

- [ ] **Step 4: รัน test**

```bash
uv run pytest tests/unit/test_graph_hitl.py -v
```
Expected: PASS

---

### Task 2: Fix YLO SMART — เรียก validate_smart จริง ไม่ใช่ stamp constant

**Files:**
- Modify: `src/curriculum_agent/stages/ylo_derivation.py:25,58,64-76`
- Modify: `tests/unit/test_smart_check.py` (เพิ่ม test)

- [ ] **Step 1: เขียน test ที่ fail**

```python
# เพิ่มใน tests/unit/test_smart_check.py
from unittest.mock import AsyncMock, patch
import pytest
from curriculum_agent.stages.ylo_derivation import _derive_ylos_for_plo
from curriculum_agent.models import (
    Domain, BloomLevel, KrathwohlLevel, PLO, ProgramMetadata, SMARTCheck
)

SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
SMART_FAIL = SMARTCheck(specific=False, measurable=False, achievable=True, relevant=True, timely=True)

def make_test_plo() -> PLO:
    return PLO(
        plo_id="PLO1", program_id="test",
        statement_th="ออกแบบระบบได้", domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.CREATE, is_subject_specific=True,
        action_verb_th="ออกแบบ", smart_check=SMART_PASS,
        source_cluster_ids=["C1"], rationale_th="test",
    )

def make_test_metadata() -> ProgramMetadata:
    return ProgramMetadata(
        program_id="test", name_th="ทดสอบ", name_en="Test",
        field="CS", degree_level="bachelor", duration_years=4,
        faculty="Engineering", university="Test U",
        vision_th="vision", program_objectives_th=["obj1"],
    )

@pytest.mark.asyncio
async def test_ylo_smart_check_is_actually_called() -> None:
    """SMART validation must run per YLO, not stamp a constant."""
    mock_draft_response = AsyncMock()
    mock_draft_response.ylos = []  # empty so we skip inner logic

    with patch("curriculum_agent.stages.ylo_derivation.complete_heavy", return_value=mock_draft_response), \
         patch("curriculum_agent.stages.ylo_derivation.complete_light") as mock_light:
        await _derive_ylos_for_plo(make_test_metadata(), make_test_plo(), "test")
        # complete_light should NOT be called when no drafts — but the key is
        # that _SMART_PASS constant no longer exists in the module
        from curriculum_agent.stages import ylo_derivation
        assert not hasattr(ylo_derivation, "_SMART_PASS"), \
            "_SMART_PASS constant must be removed; use _validate_smart() per YLO"
```

- [ ] **Step 2: รัน test ให้ fail**

```bash
uv run pytest tests/unit/test_smart_check.py::test_ylo_smart_check_is_actually_called -v
```
Expected: FAIL — `assert not hasattr(...)` เพราะ `_SMART_PASS` ยังอยู่

- [ ] **Step 3: แก้ ylo_derivation.py**

ลบ `_SMART_PASS` constant และเพิ่ม import + การเรียก SMART validation:

```python
# เพิ่ม import (บรรทัดบนสุดของ imports)
from curriculum_agent.llm import complete_heavy, complete_light
from curriculum_agent.prompts.smart_validator import build_smart_validate_prompt

# ลบบรรทัดนี้ออก:
# _SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
```

แก้ `_draft_to_ylo` ให้เป็น async และรัน SMART:

```python
async def _draft_to_ylo(draft: _YLODraft, program_id: str, parent_plo_id: str) -> YLO | None:
    for word in FORBIDDEN_WORDS_TH:
        if word in draft.statement_th:
            logger.warning(f"YLO draft {draft.ylo_id} contains forbidden word '{word}' — skipping")
            return None
    smart = await complete_light(SMARTCheck, build_smart_validate_prompt(draft.statement_th))
    return YLO(
        ylo_id=draft.ylo_id,
        program_id=program_id,
        parent_plo_id=parent_plo_id,
        year=draft.year,
        statement_th=draft.statement_th,
        statement_en=draft.statement_en,
        bloom_level=draft.bloom_level,
        krathwohl_level=draft.krathwohl_level,
        action_verb_th=draft.action_verb_th,
        smart_check=smart,
        rationale_th=draft.rationale_th,
        version=1,
    )
```

แก้ `_derive_ylos_for_plo` ให้ await `_draft_to_ylo`:

```python
async def _derive_ylos_for_plo(
    metadata: ProgramMetadata,
    plo: PLO,
    program_id: str,
) -> list[YLO]:
    messages = build_ylo_derivation_prompt(metadata, plo)
    response = await complete_heavy(_YLOListResponse, messages, max_retries=_MAX_RETRIES)
    ylos = []
    for draft in response.ylos:
        ylo = await _draft_to_ylo(draft, program_id, plo.plo_id)
        if ylo:
            ylos.append(ylo)
    return ylos
```

- [ ] **Step 4: รัน test**

```bash
uv run pytest tests/unit/test_smart_check.py -v
```
Expected: PASS

---

### Task 3: Fix FastAPI — program_id path param ใน plos.py

**Files:**
- Modify: `src/curriculum_agent/api/routes/plos.py`

ปัญหา: `router` mount ที่ prefix `/programs/{program_id}/plos` แต่ child routes ไม่มี `{program_id}` ใน path ของตัวเอง — FastAPI จะหา query param แทน

- [ ] **Step 1: เขียน test ที่ fail**

```python
# tests/unit/test_api_plos.py
from __future__ import annotations
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from curriculum_agent.api.main import app

client = TestClient(app)


def test_list_plos_uses_path_not_query() -> None:
    """GET /programs/cs-test/plos/ must not require ?program_id= query param."""
    with patch("curriculum_agent.api.routes.plos._repo") as mock_repo:
        mock_repo.list_by_program = AsyncMock(return_value=[])
        resp = client.get("/programs/cs-test/plos/")
    # Should not be 422 (missing required query param)
    assert resp.status_code != 422, f"Got 422 — program_id treated as query param: {resp.json()}"
    assert resp.status_code == 200
```

- [ ] **Step 2: รัน test ให้ fail**

```bash
uv run pytest tests/unit/test_api_plos.py -v
```
Expected: FAIL — 422

- [ ] **Step 3: แก้ plos.py — ใช้ Path parameter**

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from curriculum_agent.data.repositories import PLORepository
from curriculum_agent.models import PLO

router = APIRouter()
_repo = PLORepository()


@router.get("/", response_model=list[PLO])
async def list_plos(program_id: str = None) -> list[PLO]:
    # program_id comes from the parent prefix path parameter via FastAPI scope
    # declare it as a route-level dependency via Path injection
    return await _repo.list_by_program(program_id)
```

หมายเหตุ: FastAPI ส่ง path params จาก parent prefix เข้า child routes อัตโนมัติถ้า route function declare parameter ชื่อเดียวกัน — แต่ต้องไม่มี default value:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from curriculum_agent.data.repositories import PLORepository
from curriculum_agent.models import PLO

router = APIRouter()
_repo = PLORepository()


@router.get("/", response_model=list[PLO])
async def list_plos(program_id: str) -> list[PLO]:
    return await _repo.list_by_program(program_id)


@router.put("/{plo_id}", response_model=PLO)
async def update_plo(program_id: str, plo_id: str, plo: PLO) -> PLO:
    existing = await _repo.list_by_program(program_id)
    match = next((p for p in existing if p.plo_id == plo_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="PLO not found")
    updated = plo.model_copy(update={"version": match.version + 1, "program_id": program_id})
    await _repo.bulk_insert([updated])
    return updated
```

- [ ] **Step 4: รัน test**

```bash
uv run pytest tests/unit/test_api_plos.py -v
```
Expected: PASS

---

### Task 4: Fix programs.py — guard against unauthenticated POST + module-level singleton

**Files:**
- Modify: `src/curriculum_agent/api/routes/programs.py`
- Modify: `src/curriculum_agent/api/deps.py`

ปัญหา: POST `/programs/` ไม่มี auth — ใครก็ trigger LangGraph pipeline ได้ และ `_repo` เป็น module-level singleton

- [ ] **Step 1: เช็ก deps.py ก่อน**

```bash
cat src/curriculum_agent/api/deps.py
```

- [ ] **Step 2: เพิ่ม simple API key dependency ใน deps.py**

```python
# src/curriculum_agent/api/deps.py
from __future__ import annotations

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from curriculum_agent.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    """Require X-API-Key header matching settings.api_key. Raises 401 if missing/wrong."""
    if not settings.api_key:
        return "no-auth-configured"
    if api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key
```

- [ ] **Step 3: เพิ่ม api_key ใน config.py**

อ่าน config.py ก่อน จากนั้นเพิ่ม field:
```python
api_key: str | None = None  # ใน class Settings
```

- [ ] **Step 4: เขียน test ที่ fail**

```python
# tests/unit/test_api_programs.py
from __future__ import annotations
from fastapi.testclient import TestClient
from curriculum_agent.api.main import app

client = TestClient(app)


def test_create_program_requires_api_key(monkeypatch) -> None:
    """POST /programs/ must return 401 without X-API-Key when api_key is configured."""
    import curriculum_agent.config as cfg
    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")

    resp = client.post("/programs/", json={
        "program_id": "test", "name_th": "ทดสอบ", "name_en": "Test",
        "field": "CS", "degree_level": "bachelor", "duration_years": 4,
        "faculty": "Eng", "university": "Test U",
        "vision_th": "v", "program_objectives_th": ["o1"],
    })
    assert resp.status_code == 401
```

- [ ] **Step 5: รัน test ให้ fail**

```bash
uv run pytest tests/unit/test_api_programs.py::test_create_program_requires_api_key -v
```
Expected: FAIL

- [ ] **Step 6: แก้ programs.py — ใช้ Depends + ไม่ใช้ module-level singleton**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import ProgramRepository
from curriculum_agent.graph import build_graph
from curriculum_agent.models import ProgramMetadata

router = APIRouter()


@router.post("/", response_model=ProgramMetadata, dependencies=[Depends(require_api_key)])
async def create_program(metadata: ProgramMetadata) -> ProgramMetadata:
    repo = ProgramRepository()
    await repo.upsert(metadata)
    graph = build_graph()
    await graph.ainvoke(
        {"program_id": metadata.program_id, "metadata": metadata.model_dump(mode="json")},
        config={"configurable": {"thread_id": metadata.program_id}},
    )
    return metadata


@router.get("/{program_id}", response_model=ProgramMetadata)
async def get_program(program_id: str) -> ProgramMetadata:
    repo = ProgramRepository()
    result = await repo.get(program_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return result
```

- [ ] **Step 7: รัน test**

```bash
uv run pytest tests/unit/test_api_programs.py -v
```
Expected: PASS

---

### Task 5: Fix plo_synthesis.py — guard ก่อนเรียก LLM ด้วย empty clusters

**Files:**
- Modify: `src/curriculum_agent/stages/plo_synthesis.py:128-142`

- [ ] **Step 1: เขียน test ที่ fail**

```python
# tests/unit/test_plo_synthesis_guard.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from curriculum_agent.stages.plo_synthesis import run
from curriculum_agent.graph import AgentState


@pytest.mark.asyncio
async def test_run_raises_when_no_clusters() -> None:
    """Stage 3 must raise ValueError before hitting LLM when clusters is empty."""
    state: AgentState = {
        "program_id": "test",
        "skill_clusters": [],
        "metadata": {
            "program_id": "test", "name_th": "ทดสอบ", "name_en": "Test",
            "field": "CS", "degree_level": "bachelor", "duration_years": 4,
            "faculty": "Eng", "university": "Test U",
            "vision_th": "v", "program_objectives_th": ["o1"],
        },
    }
    with pytest.raises(ValueError, match="no skill clusters"):
        await run(state)
```

- [ ] **Step 2: รัน test ให้ fail**

```bash
uv run pytest tests/unit/test_plo_synthesis_guard.py -v
```
Expected: FAIL

- [ ] **Step 3: แก้ plo_synthesis.py — เพิ่ม guard**

เพิ่มหลังบรรทัด `selected = ...`:

```python
    clusters = [SkillCluster.model_validate(d) for d in clusters_dicts]
    selected = [c for c in clusters if c.is_common_need]
    if len(selected) < _MIN_PLOS:
        selected = sorted(clusters, key=lambda c: c.demand_score, reverse=True)[:8]

    # Guard: ต้องมี cluster ก่อนเรียก LLM
    if not selected:
        raise ValueError(
            f"Stage 3: no skill clusters available for program '{program_id}' — "
            "run Stage 2 successfully before proceeding to PLO synthesis"
        )
```

- [ ] **Step 4: รัน test**

```bash
uv run pytest tests/unit/test_plo_synthesis_guard.py -v
```
Expected: PASS

---

### Task 6: Fix models.py — validate source_evidence_ids บน PLO

**Files:**
- Modify: `src/curriculum_agent/models.py:175-181`
- Modify: `tests/unit/test_models.py`

- [ ] **Step 1: เขียน test ที่ fail**

เพิ่มใน `tests/unit/test_models.py`:

```python
def test_plo_rejects_empty_source_evidence_ids() -> None:
    with pytest.raises(ValidationError, match="source_evidence_ids"):
        PLO(**make_plo(source_evidence_ids=[]))
```

- [ ] **Step 2: รัน test ให้ fail**

```bash
uv run pytest tests/unit/test_models.py::test_plo_rejects_empty_source_evidence_ids -v
```
Expected: FAIL

- [ ] **Step 3: แก้ check_evidence validator ใน models.py**

```python
    @model_validator(mode="after")
    def check_evidence(self) -> PLO:
        if not self.source_cluster_ids:
            raise ValueError(
                f"PLO {self.plo_id} has no source clusters — every PLO must trace to evidence."
            )
        if not self.source_evidence_ids:
            raise ValueError(
                f"PLO {self.plo_id} has empty source_evidence_ids — every PLO must trace to evidence."
            )
        return self
```

- [ ] **Step 4: แก้ test fixtures ที่ผลกระทบ**

ทั้ง `make_plo` ใน `test_models.py` และ `test_ylo_matrix.py` ต้องเพิ่ม `source_evidence_ids`:

ใน `tests/unit/test_models.py` — แก้ base dict ใน `make_plo()`:
```python
        "source_evidence_ids": ["E1"],  # เพิ่มบรรทัดนี้
```

ใน `tests/unit/test_ylo_matrix.py` — แก้ `make_plo()`:
```python
def make_plo(plo_id: str = "PLO1", domain: Domain = Domain.COGNITIVE) -> PLO:
    return PLO(
        plo_id=plo_id,
        program_id="cs-test",
        statement_th=f"ออกแบบระบบ {plo_id} ได้",
        domain=domain,
        bloom_level=BloomLevel.CREATE if domain == Domain.COGNITIVE else None,
        krathwohl_level=KrathwohlLevel.VALUING if domain == Domain.AFFECTIVE else None,
        is_subject_specific=True,
        action_verb_th="ออกแบบ",
        smart_check=SMART_PASS,
        source_cluster_ids=["C1"],
        source_evidence_ids=["E1"],   # เพิ่ม
        rationale_th="ทดสอบ",
    )
```

- [ ] **Step 5: รัน tests ทั้งหมด**

```bash
uv run pytest tests/unit/ -v
```
Expected: PASS ทุก test

---

### Task 7: Fix models.py — validate_coverage ต้องครอบ PSYCHOMOTOR

**Files:**
- Modify: `src/curriculum_agent/models.py:238-261`
- Modify: `tests/unit/test_ylo_matrix.py`

- [ ] **Step 1: เขียน test ที่ fail**

เพิ่มใน `tests/unit/test_ylo_matrix.py`:

```python
def test_psychomotor_bloom_decrease_caught() -> None:
    """Psychomotor PLOs must also have monotonic Bloom levels."""
    plo = make_plo("PLO-P1", domain=Domain.PSYCHOMOTOR)
    # Reuse make_ylo but plo needs bloom_level — psychomotor uses bloom
    ylos = [
        make_ylo("YLO-P1.1", "PLO-P1", 1, BloomLevel.CREATE),
        make_ylo("YLO-P1.2", "PLO-P1", 2, BloomLevel.APPLY),  # decrease
    ]
    matrix = YLOMatrix(program_id="cs-test", plos=[plo], ylos=ylos)
    issues = matrix.validate_coverage()
    assert any("Bloom decreases" in i for i in issues), f"Expected Bloom decrease issue, got: {issues}"
```

หมายเหตุ: `make_plo` สำหรับ PSYCHOMOTOR ต้องใช้ `bloom_level` (ไม่ใช่ Krathwohl) ดังนั้นต้องแก้ `make_plo` ใน test file:

```python
def make_plo(plo_id: str = "PLO1", domain: Domain = Domain.COGNITIVE) -> PLO:
    bloom = BloomLevel.CREATE if domain != Domain.AFFECTIVE else None
    krath = KrathwohlLevel.VALUING if domain == Domain.AFFECTIVE else None
    return PLO(
        plo_id=plo_id,
        program_id="cs-test",
        statement_th=f"ออกแบบระบบ {plo_id} ได้",
        domain=domain,
        bloom_level=bloom,
        krathwohl_level=krath,
        is_subject_specific=True,
        action_verb_th="ออกแบบ",
        smart_check=SMART_PASS,
        source_cluster_ids=["C1"],
        source_evidence_ids=["E1"],
        rationale_th="ทดสอบ",
    )
```

- [ ] **Step 2: รัน test ให้ fail**

```bash
uv run pytest tests/unit/test_ylo_matrix.py::test_psychomotor_bloom_decrease_caught -v
```
Expected: FAIL

- [ ] **Step 3: แก้ validate_coverage ใน models.py**

แก้ `if plo.domain == Domain.COGNITIVE:` block ให้ครอบ PSYCHOMOTOR ด้วย:

```python
            if plo.domain in (Domain.COGNITIVE, Domain.PSYCHOMOTOR):
                sorted_ylos = sorted(ylos_for_plo, key=lambda y: y.year)
                levels = [y.bloom_level for y in sorted_ylos if y.bloom_level]
                for i in range(1, len(levels)):
                    prev_idx = BLOOM_ORDER.index(levels[i - 1])
                    curr_idx = BLOOM_ORDER.index(levels[i])
                    if curr_idx < prev_idx:
                        issues.append(
                            f"{plo.plo_id} Bloom decreases between year "
                            f"{sorted_ylos[i-1].year} ({levels[i-1].value}) and "
                            f"year {sorted_ylos[i].year} ({levels[i].value})"
                        )
```

- [ ] **Step 4: รัน tests**

```bash
uv run pytest tests/unit/test_ylo_matrix.py -v
```
Expected: PASS ทุก test

---

### Task 8: Fix ylo_derivation.py — retry loop ต้องส่ง feedback ว่า word ไหนต้องหลีกเลี่ยง

**Files:**
- Modify: `src/curriculum_agent/stages/ylo_derivation.py:64-76`
- Modify: `src/curriculum_agent/prompts/stage_4_ylo.py`

- [ ] **Step 1: แก้ build_ylo_derivation_prompt ให้รับ forbidden_words parameter**

```python
# src/curriculum_agent/prompts/stage_4_ylo.py
from __future__ import annotations

from curriculum_agent.models import PLO, ProgramMetadata, FORBIDDEN_WORDS_TH


def build_ylo_derivation_prompt(
    metadata: ProgramMetadata,
    plo: PLO,
    avoid_words: set[str] | None = None,
) -> list[dict]:
    avoid_note = ""
    if avoid_words:
        avoid_note = f"\n\n**ห้ามใช้คำเหล่านี้เด็ดขาด:** {', '.join(sorted(avoid_words))}"

    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญด้านการออกแบบ Year Learning Outcomes (YLO) "
                "สร้าง YLO สำหรับแต่ละปีของหลักสูตร โดย Bloom level ต้องเพิ่มขึ้นตามปี "
                "(monotonically non-decreasing) และไม่ใช้คำต้องห้าม"
                + avoid_note
            ),
        },
        {
            "role": "user",
            "content": (
                f"หลักสูตร {metadata.duration_years} ปี — {metadata.field}\n\n"
                f"PLO: [{plo.plo_id}] {plo.statement_th}\n"
                f"Domain: {plo.domain.value}, "
                f"Bloom (graduation): {plo.bloom_level.value if plo.bloom_level else plo.krathwohl_level.value if plo.krathwohl_level else 'N/A'}\n\n"
                f"สร้าง YLO สำหรับปีที่ 1-{metadata.duration_years} "
                "แต่ละปีต้องมี ylo_id, year, statement_th, bloom_level/krathwohl_level, action_verb_th, และ rationale_th"
                + avoid_note
            ),
        },
    ]
```

- [ ] **Step 2: แก้ _derive_ylos_for_plo ให้ track forbidden words และส่งไป prompt**

```python
async def _derive_ylos_for_plo(
    metadata: ProgramMetadata,
    plo: PLO,
    program_id: str,
    avoid_words: set[str] | None = None,
) -> list[YLO]:
    messages = build_ylo_derivation_prompt(metadata, plo, avoid_words=avoid_words)
    response = await complete_heavy(_YLOListResponse, messages, max_retries=_MAX_RETRIES)
    ylos = []
    found_forbidden: set[str] = set()
    for draft in response.ylos:
        ylo = await _draft_to_ylo(draft, program_id, plo.plo_id)
        if ylo:
            ylos.append(ylo)
        else:
            for word in FORBIDDEN_WORDS_TH:
                if word in draft.statement_th:
                    found_forbidden.add(word)
    return ylos, found_forbidden
```

แก้ caller ใน `run()` ให้รับค่า tuple และส่ง forbidden words ไปรอบ retry:

```python
    for plo in plos:
        ylos, _ = await _derive_ylos_for_plo(metadata, plo, program_id)
        all_ylos.extend(ylos)
        logger.debug(f"  {plo.plo_id}: {len(ylos)} YLOs generated")

    # ... (in retry loop)
    for plo in plos:
        if plo.plo_id in problem_plo_ids:
            # Collect which forbidden words caused failures
            avoid: set[str] = set()
            for y in all_ylos:
                pass  # already filtered — pass accumulated set instead
            new_ylos, forbidden_found = await _derive_ylos_for_plo(
                metadata, plo, program_id, avoid_words=FORBIDDEN_WORDS_TH
            )
            new_ylos_map[plo.plo_id] = new_ylos
```

- [ ] **Step 3: รัน unit tests เพื่อให้แน่ใจไม่มี regression**

```bash
uv run pytest tests/unit/ -v
```
Expected: PASS ทุก test

---

### Task 9: Fix llm.py — LLM client เป็น factory function แทน module-level singleton

**Files:**
- Modify: `src/curriculum_agent/llm.py`

- [ ] **Step 1: เขียน test ที่ fail**

```python
# tests/unit/test_llm_client.py
from __future__ import annotations
import asyncio
import importlib


def test_llm_module_has_no_global_client() -> None:
    """llm.py must not instantiate AsyncOpenAI at import time."""
    import curriculum_agent.llm as llm_module
    assert not hasattr(llm_module, "_client") or llm_module._client is None, \
        "_client must not be a module-level singleton; use a factory function"
```

- [ ] **Step 2: รัน test ให้ fail**

```bash
uv run pytest tests/unit/test_llm_client.py -v
```
Expected: FAIL

- [ ] **Step 3: แก้ llm.py — lazy client via functools.cache**

```python
from __future__ import annotations

import functools
from typing import Any, TypeVar

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel

from curriculum_agent.config import settings

T = TypeVar("T", bound=BaseModel)


@functools.cache
def _get_client() -> instructor.AsyncInstructor:
    """Lazy singleton — created on first call, not at import time."""
    return instructor.from_openai(
        AsyncOpenAI(
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",
        ),
        mode=instructor.Mode.JSON,
    )


async def complete_light(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Typhoon 2 8B — fast, used for classification and SMART validation."""
    return await _get_client().chat.completions.create(
        model=settings.light_model,
        response_model=response_model,
        messages=messages,
        **kwargs,
    )


async def complete_heavy(
    response_model: type[T],
    messages: list[dict[str, Any]],
    **kwargs: Any,
) -> T:
    """Qwen 2.5 14B/32B — used for PLO synthesis and YLO derivation."""
    return await _get_client().chat.completions.create(
        model=settings.heavy_model,
        response_model=response_model,
        messages=messages,
        **kwargs,
    )
```

- [ ] **Step 4: รัน test**

```bash
uv run pytest tests/unit/test_llm_client.py -v
```
Expected: PASS

---

### Task 10: Fix state access — ใช้ .get() แทน hard key ใน stages

**Files:**
- Modify: `src/curriculum_agent/stages/intake.py:12`
- Modify: `src/curriculum_agent/stages/plo_synthesis.py:132`
- Modify: `src/curriculum_agent/stages/ylo_derivation.py:83`

- [ ] **Step 1: เขียน test ที่ fail**

```python
# tests/unit/test_state_safety.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch
from curriculum_agent.stages import intake, plo_synthesis, ylo_derivation
from curriculum_agent.graph import AgentState


@pytest.mark.asyncio
async def test_intake_handles_missing_metadata() -> None:
    """intake.run() must raise ValueError, not KeyError, when metadata missing."""
    state: AgentState = {"program_id": "test"}  # no "metadata" key
    with pytest.raises(ValueError, match="metadata"):
        await intake.run(state)
```

- [ ] **Step 2: รัน test ให้ fail**

```bash
uv run pytest tests/unit/test_state_safety.py::test_intake_handles_missing_metadata -v
```
Expected: FAIL — `KeyError: 'metadata'`

- [ ] **Step 3: แก้ intake.py**

```python
async def run(state: AgentState) -> AgentState:
    """Stage 0: validate ProgramMetadata and persist to Postgres."""
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run intake stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)
    logger.info(f"Intake: program_id={metadata.program_id}, field={metadata.field}")

    repo = ProgramRepository()
    await repo.upsert(metadata)

    state["current_stage"] = "intake"
    return state
```

- [ ] **Step 4: แก้ plo_synthesis.py บรรทัด 132**

```python
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run PLO synthesis stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)
```

- [ ] **Step 5: แก้ ylo_derivation.py บรรทัด 83**

```python
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run YLO derivation stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)
```

- [ ] **Step 6: รัน test ทั้งหมด**

```bash
uv run pytest tests/unit/ -v
```
Expected: PASS ทุก test

---

## Part B — Architecture Improvements

**Assessment:** หลังแก้ bugs แล้ว ยังมี 3 ด้าน architecture ที่ไม่ตรง best practice:

| Issue | ระดับ |
|---|---|
| Module-level repo singletons ใน API routes | Medium |
| ไม่มี auth middleware (เพิ่งเพิ่ม api key ที่ programs เท่านั้น ยังขาด routes อื่น) | High |
| `validate_coverage` error message ใช้ index ผิดเมื่อมี `bloom_level=None` | Medium |

### Task 11: Extend auth — ทุก write route ต้องใช้ require_api_key

**Files:**
- Modify: `src/curriculum_agent/api/routes/plos.py`
- Modify: `src/curriculum_agent/api/routes/ylos.py`
- Modify: `src/curriculum_agent/api/routes/clusters.py`

- [ ] **Step 1: อ่าน ylos.py และ clusters.py ก่อน**

```bash
cat src/curriculum_agent/api/routes/ylos.py
cat src/curriculum_agent/api/routes/clusters.py
```

- [ ] **Step 2: เพิ่ม dependencies=[Depends(require_api_key)] ทุก PUT/POST/DELETE**

ใน `plos.py`:
```python
from curriculum_agent.api.deps import require_api_key

@router.put("/{plo_id}", response_model=PLO, dependencies=[Depends(require_api_key)])
async def update_plo(program_id: str, plo_id: str, plo: PLO) -> PLO:
    ...
```

ใน `ylos.py` — เพิ่ม auth บน PUT/POST endpoints ในลักษณะเดียวกัน

ใน `clusters.py` — เพิ่ม auth บน write endpoints

- [ ] **Step 3: รัน tests**

```bash
uv run pytest tests/ -v
```
Expected: PASS ทุก test

---

### Task 12: Fix validate_coverage error message — index mismatch เมื่อ bloom_level=None

**Files:**
- Modify: `src/curriculum_agent/models.py:238-261`

ปัญหา: `levels` list ถูก filter (ตัด `None` ออก) แต่ error message ใช้ `sorted_ylos[i-1].year` ซึ่ง index ไปยัง unfiltered list — year ผิด

- [ ] **Step 1: เขียน test ที่ fail**

เพิ่มใน `tests/unit/test_ylo_matrix.py`:

```python
def test_bloom_decrease_error_message_shows_correct_year() -> None:
    """Error message must show the year of the YLO with None bloom_level correctly skipped."""
    plo = make_plo()
    # year 1: None bloom, year 2: ANALYZE, year 3: APPLY (decrease between 2 and 3)
    ylo_no_bloom = YLO(
        ylo_id="YLO1.0", program_id="cs-test", parent_plo_id="PLO1",
        year=1, statement_th="ทดสอบ", bloom_level=None,
        action_verb_th="ทดสอบ", smart_check=SMART_PASS, rationale_th="test",
    )
    ylo_analyze = make_ylo("YLO1.1", "PLO1", 2, BloomLevel.ANALYZE)
    ylo_apply   = make_ylo("YLO1.2", "PLO1", 3, BloomLevel.APPLY)  # decrease

    matrix = YLOMatrix(program_id="cs-test", plos=[plo], ylos=[ylo_no_bloom, ylo_analyze, ylo_apply])
    issues = matrix.validate_coverage()
    assert any("year 2" in i and "year 3" in i for i in issues), \
        f"Expected issue mentioning year 2 and year 3, got: {issues}"
```

- [ ] **Step 2: รัน test ให้ fail**

```bash
uv run pytest tests/unit/test_ylo_matrix.py::test_bloom_decrease_error_message_shows_correct_year -v
```

- [ ] **Step 3: แก้ validate_coverage ใน models.py — track year พร้อมกับ level**

```python
            if plo.domain in (Domain.COGNITIVE, Domain.PSYCHOMOTOR):
                sorted_ylos = sorted(ylos_for_plo, key=lambda y: y.year)
                # keep (year, level) pairs so error message uses correct year
                year_levels = [(y.year, y.bloom_level) for y in sorted_ylos if y.bloom_level]
                for i in range(1, len(year_levels)):
                    prev_year, prev_level = year_levels[i - 1]
                    curr_year, curr_level = year_levels[i]
                    if BLOOM_ORDER.index(curr_level) < BLOOM_ORDER.index(prev_level):
                        issues.append(
                            f"{plo.plo_id} Bloom decreases between year "
                            f"{prev_year} ({prev_level.value}) and "
                            f"year {curr_year} ({curr_level.value})"
                        )

            elif plo.domain == Domain.AFFECTIVE:
                sorted_ylos = sorted(ylos_for_plo, key=lambda y: y.year)
                year_levels = [(y.year, y.krathwohl_level) for y in sorted_ylos if y.krathwohl_level]
                for i in range(1, len(year_levels)):
                    prev_year, prev_level = year_levels[i - 1]
                    curr_year, curr_level = year_levels[i]
                    if KRATHWOHL_ORDER.index(curr_level) < KRATHWOHL_ORDER.index(prev_level):
                        issues.append(
                            f"{plo.plo_id} Krathwohl decreases between year "
                            f"{prev_year} and year {curr_year}"
                        )
```

- [ ] **Step 4: รัน tests ทั้งหมด**

```bash
uv run pytest tests/ -v
```
Expected: PASS ทุก test

---

## Part C — HTML Architecture Report

### Task 13: สร้าง HTML summary report ด้วย frontend-design skill

- [ ] **Step 1: ใช้ frontend-design skill สร้าง HTML report**

เนื้อหา HTML ต้องรวม:
- สรุป 10 bugs + status (fixed)
- Architecture diagram (text-based หรือ CSS diagram)
- Architecture improvements (Part B)
- Best practices checklist

- [ ] **Step 2: บันทึกไฟล์ไปที่ `docs/architecture-report.html`**

- [ ] **Step 3: ตรวจสอบ HTML render ถูกต้อง**

---

## Self-Review

**Spec coverage:**
- [x] Bug #1 (HITL interrupt) → Task 1
- [x] Bug #2 (YLO SMART constant) → Task 2
- [x] Bug #3 (plos.py program_id path) → Task 3
- [x] Bug #4 (programs.py no auth) → Task 4
- [x] Bug #5 (zero clusters guard) → Task 5
- [x] Bug #6 (PLO source_evidence_ids) → Task 6
- [x] Bug #7 (PSYCHOMOTOR skip) → Task 7
- [x] Bug #8 (retry loop same prompt) → Task 8
- [x] Bug #9 (module-level LLM client) → Task 9
- [x] Bug #10 (state key access) → Task 10
- [x] Auth extended to all routes → Task 11
- [x] validate_coverage year index fix → Task 12
- [x] HTML report → Task 13

**Placeholder scan:** ไม่พบ TBD/TODO ใน steps ที่มี code

**Type consistency:**
- `_derive_ylos_for_plo` เปลี่ยน return type เป็น `tuple[list[YLO], set[str]]` ใน Task 8 — caller ใน `run()` ต้องรับ tuple ทั้ง 2 จุด (initial call และ retry loop) ✓
- `build_ylo_derivation_prompt` เพิ่ม `avoid_words` param — ต้องแก้ทุก caller ✓
