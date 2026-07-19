# Program History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A landing page listing every created curriculum (program) with its current pipeline stage, letting users resume work on any of them.

**Architecture:** Reuse existing `programs` + `sessions` tables (no migration). New `ProgramSummary` Pydantic model, `ProgramRepository.list_all()` that merges each program with its latest session, `GET /programs/` route, and a new `Programs.tsx` React page that becomes the index route (Intake moves to `/intake`).

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / Pydantic v2; React 19 + react-router-dom + axios.

**Spec:** `docs/superpowers/specs/2026-07-19-program-history-design.md`

## Global Constraints

- Type hints on every function signature; `from __future__ import annotations` at top of every Python file.
- Student-facing strings in Thai; code, comments, log messages in English.
- Repository pattern only — no SQL outside `src/curriculum_agent/data/repositories.py`.
- `GET /programs/` requires no API key (same policy as existing `GET /programs/{program_id}`).
- No pagination, no delete, no audit table (out of scope per spec).
- Tests: `asyncio_mode = "auto"` — `@pytest.mark.asyncio` not required (existing files sometimes carry it; new tests may omit).

---

### Task 1: `ProgramSummary` model

**Files:**
- Modify: `src/curriculum_agent/models.py` (after `ProgramMetadata`, ~line 139)
- Test: `tests/unit/test_models.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `ProgramSummary(BaseModel)` with fields `program_id: str`, `name_th: str`, `name_en: str`, `degree_level: str`, `created_at: datetime`, `current_stage: str | None = None`, `session_status: str | None = None`. Tasks 2–3 import it from `curriculum_agent.models`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_models.py`:

```python
def test_program_summary_minimal() -> None:
    from datetime import datetime

    from curriculum_agent.models import ProgramSummary

    s = ProgramSummary(
        program_id="computer-science",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        degree_level="bachelor",
        created_at=datetime(2026, 7, 1, 9, 0, 0),
    )
    assert s.current_stage is None
    assert s.session_status is None


def test_program_summary_with_session_fields() -> None:
    from datetime import datetime

    from curriculum_agent.models import ProgramSummary

    s = ProgramSummary(
        program_id="computer-science",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        degree_level="bachelor",
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        current_stage="skill_extraction",
        session_status="suspended",
    )
    assert s.current_stage == "skill_extraction"
    assert s.session_status == "suspended"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models.py -k program_summary -v`
Expected: FAIL with `ImportError: cannot import name 'ProgramSummary'`

- [ ] **Step 3: Write minimal implementation**

In `src/curriculum_agent/models.py`, directly after the `ProgramMetadata` class:

```python
class ProgramSummary(BaseModel):
    """List-page row: program metadata + latest-session state.

    current_stage/session_status are None when the program has no session yet.
    """

    program_id: str
    name_th: str
    name_en: str
    degree_level: str
    created_at: datetime
    current_stage: str | None = None
    session_status: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_models.py -k program_summary -v`
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/curriculum_agent/models.py tests/unit/test_models.py
git commit -m "feat(models): add ProgramSummary for program history list"
```

---

### Task 2: `ProgramRepository.list_all()`

**Files:**
- Modify: `src/curriculum_agent/data/repositories.py` (inside `ProgramRepository`, after `exists`, ~line 82)
- Test: Create `tests/unit/test_program_repository.py`

**Interfaces:**
- Consumes: `ProgramSummary` from Task 1; existing `ProgramTable`, `SessionTable` (already imported in repositories.py via `curriculum_agent.data.orm`? — **No**: only `SessionTable` needs adding to the existing `from curriculum_agent.data.orm import (...)` block if absent; check — it IS already imported for `SessionRepository`).
- Produces: `async def list_all(self) -> list[ProgramSummary]` — programs ordered `created_at` DESC, each merged with its latest session (max `created_at`), stage fields `None` when no session. Task 3 calls this.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_program_repository.py`:

```python
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_agent.data.orm import ProgramTable, SessionTable
from curriculum_agent.data.repositories import ProgramRepository


def _program_row(program_id: str, created_at: datetime) -> ProgramTable:
    return ProgramTable(
        program_id=program_id,
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="CS",
        degree_level="bachelor",
        duration_years=4,
        faculty="Engineering",
        university="Test University",
        vision_th="วิสัยทัศน์",
        mission_th="พันธกิจ",
        philosophy_th="ปรัชญา",
        program_goals_th=["เป้าหมาย 1"],
        program_objectives_th=["objective 1"],
        created_at=created_at,
    )


def _session_row(
    session_id: str, program_id: str, stage: str | None, status: str, created_at: datetime
) -> SessionTable:
    return SessionTable(
        session_id=session_id,
        program_id=program_id,
        thread_id=f"{program_id}:{session_id}",
        status=status,
        current_stage=stage,
        created_at=created_at,
        updated_at=created_at,
    )


def _mock_db(programs: list[ProgramTable], sessions: list[SessionTable]) -> MagicMock:
    """AsyncSessionLocal mock whose execute() returns programs then sessions."""
    prog_result = MagicMock()
    prog_result.scalars.return_value.all.return_value = programs
    sess_result = MagicMock()
    sess_result.scalars.return_value.all.return_value = sessions

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[prog_result, sess_result])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


async def test_list_all_empty() -> None:
    repo = ProgramRepository()
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_mock_db([], [])
    ):
        result = await repo.list_all()
    assert result == []


async def test_list_all_program_without_session_has_null_stage() -> None:
    repo = ProgramRepository()
    programs = [_program_row("cs", datetime(2026, 7, 1))]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, []),
    ):
        result = await repo.list_all()
    assert len(result) == 1
    assert result[0].program_id == "cs"
    assert result[0].current_stage is None
    assert result[0].session_status is None


async def test_list_all_uses_latest_session_per_program() -> None:
    repo = ProgramRepository()
    programs = [_program_row("cs", datetime(2026, 7, 1))]
    sessions = [
        _session_row("s1", "cs", "intake", "completed", datetime(2026, 7, 1, 10, 0)),
        _session_row("s2", "cs", "plo_synthesis", "suspended", datetime(2026, 7, 2, 10, 0)),
    ]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, sessions),
    ):
        result = await repo.list_all()
    assert result[0].current_stage == "plo_synthesis"
    assert result[0].session_status == "suspended"


async def test_list_all_preserves_program_order() -> None:
    """Rows come back in query order (created_at DESC handled by SQL)."""
    repo = ProgramRepository()
    programs = [
        _program_row("newer", datetime(2026, 7, 2)),
        _program_row("older", datetime(2026, 7, 1)),
    ]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, []),
    ):
        result = await repo.list_all()
    assert [p.program_id for p in result] == ["newer", "older"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_program_repository.py -v`
Expected: FAIL with `AttributeError: 'ProgramRepository' object has no attribute 'list_all'`

- [ ] **Step 3: Write minimal implementation**

In `src/curriculum_agent/data/repositories.py`:

1. Add `ProgramSummary` to the existing `from curriculum_agent.models import (...)` block.
2. Add to `ProgramRepository` (after `exists`):

```python
    async def list_all(self) -> list[ProgramSummary]:
        """All programs (created_at DESC), each with its latest session state."""
        async with AsyncSessionLocal() as session:
            prog_rows = (
                (
                    await session.execute(
                        select(ProgramTable).order_by(ProgramTable.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            sess_rows = (await session.execute(select(SessionTable))).scalars().all()

        latest: dict[str, SessionTable] = {}
        for s in sess_rows:
            cur = latest.get(s.program_id)
            if cur is None or s.created_at > cur.created_at:
                latest[s.program_id] = s

        return [
            ProgramSummary(
                program_id=p.program_id,
                name_th=p.name_th,
                name_en=p.name_en,
                degree_level=p.degree_level,
                created_at=p.created_at,
                current_stage=(
                    latest[p.program_id].current_stage if p.program_id in latest else None
                ),
                session_status=(
                    latest[p.program_id].status if p.program_id in latest else None
                ),
            )
            for p in prog_rows
        ]
```

(PoC scale: two simple queries + Python-side merge beats a window-function join for readability and testability.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_program_repository.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Run lint + typecheck**

Run: `uv run ruff check src/ tests/ && uv run mypy src/`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/data/repositories.py tests/unit/test_program_repository.py
git commit -m "feat(data): add ProgramRepository.list_all with latest-session merge"
```

---

### Task 3: `GET /programs/` route

**Files:**
- Modify: `src/curriculum_agent/api/routes/programs.py`
- Test: `tests/unit/test_api_programs.py` (append)

**Interfaces:**
- Consumes: `ProgramRepository.list_all()` (Task 2), `ProgramSummary` (Task 1).
- Produces: `GET /programs/` → `200` with JSON array of `ProgramSummary`. No API key. Frontend (Task 4) fetches this.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_api_programs.py`:

```python
def test_list_programs_empty() -> None:
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.list_all = AsyncMock(return_value=[])
        mock_repo_cls.return_value = mock_repo
        resp = client.get("/programs/")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json() == []


def test_list_programs_returns_summaries_without_api_key() -> None:
    from datetime import datetime

    from curriculum_agent.models import ProgramSummary

    summaries = [
        ProgramSummary(
            program_id="computer-science",
            name_th="วิทยาการคอมพิวเตอร์",
            name_en="Computer Science",
            degree_level="bachelor",
            created_at=datetime(2026, 7, 2, 9, 0, 0),
            current_stage="plo_synthesis",
            session_status="suspended",
        ),
        ProgramSummary(
            program_id="data-science",
            name_th="วิทยาการข้อมูล",
            name_en="Data Science",
            degree_level="master",
            created_at=datetime(2026, 7, 1, 9, 0, 0),
        ),
    ]
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.list_all = AsyncMock(return_value=summaries)
        mock_repo_cls.return_value = mock_repo
        resp = client.get("/programs/")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    body = resp.json()
    assert [p["program_id"] for p in body] == ["computer-science", "data-science"]
    assert body[0]["current_stage"] == "plo_synthesis"
    assert body[1]["current_stage"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_api_programs.py -k list_programs -v`
Expected: FAIL — `GET /programs/` returns 405 (only POST is registered on `/`)

- [ ] **Step 3: Write minimal implementation**

In `src/curriculum_agent/api/routes/programs.py`:

1. Add `ProgramSummary` to the `from curriculum_agent.models import (...)` block.
2. Add the route ABOVE `get_program` (`/{program_id}`) — keep declaration order explicit:

```python
@router.get("/", response_model=list[ProgramSummary])
async def list_programs() -> list[ProgramSummary]:
    """Program history: all programs with their latest pipeline state."""
    repo = ProgramRepository()
    return await repo.list_all()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_api_programs.py -v`
Expected: all PASSED (new + existing)

- [ ] **Step 5: Run lint + typecheck + full test suite**

Run: `uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest`
Expected: no errors, all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/api/routes/programs.py tests/unit/test_api_programs.py
git commit -m "feat(api): add GET /programs/ history endpoint"
```

---

### Task 4: Frontend history page + routing

**Files:**
- Create: `frontend/src/pages/Programs.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/StageLayout.tsx`

**Interfaces:**
- Consumes: `GET /programs/` (Task 3) via existing `frontend/src/api/client.ts` axios instance; existing `useProgram()` hook (`frontend/src/hooks/useProgram.ts`) exposing `{ programId, setProgramId }`.
- Produces: index route `/` renders `Programs`; `Intake` moves to `/intake`; row click resumes a program.

No frontend test runner exists in this repo — verification is `npm run lint && npm run build` plus manual check.

- [ ] **Step 1: Create `frontend/src/pages/Programs.tsx`**

```tsx
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useProgram } from '../hooks/useProgram'

interface ProgramSummary {
  program_id: string
  name_th: string
  name_en: string
  degree_level: string
  created_at: string
  current_stage: string | null
  session_status: string | null
}

const STAGE_ROUTES: Record<string, string> = {
  intake: '/intake',
  stakeholder_needs: '/stakeholder-needs',
  skill_extraction: '/skill-extraction',
  plo_synthesis: '/plo-synthesis',
  plo_report: '/plo-report',
}

const STAGE_LABELS: Record<string, string> = {
  intake: 'ขั้นที่ 1: ข้อมูลหลักสูตร',
  stakeholder_needs: 'ขั้นที่ 2: ความต้องการผู้มีส่วนได้ส่วนเสีย',
  skill_extraction: 'ขั้นที่ 3: สกัดทักษะ',
  plo_synthesis: 'ขั้นที่ 4: สังเคราะห์ PLO',
  plo_report: 'ขั้นที่ 5: รายงาน PLO',
}

const DEGREE_LABELS: Record<string, string> = {
  bachelor: 'ปริญญาตรี',
  master: 'ปริญญาโท',
  doctoral: 'ปริญญาเอก',
}

const STATUS_LABELS: Record<string, string> = {
  running: 'กำลังทำงาน',
  suspended: 'รอตรวจสอบ',
  completed: 'เสร็จสิ้น',
  rejected: 'ถูกปฏิเสธ',
  failed: 'ล้มเหลว',
}

function stageRoute(stage: string | null): string {
  if (!stage) return '/intake'
  return STAGE_ROUTES[stage] ?? '/pipeline'
}

export default function Programs() {
  const [programs, setPrograms] = useState<ProgramSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { setProgramId } = useProgram()
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<ProgramSummary[]>('/programs/')
      setPrograms(res.data)
    } catch {
      setError('โหลดรายการหลักสูตรไม่สำเร็จ')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const openProgram = (p: ProgramSummary) => {
    setProgramId(p.program_id)
    navigate(stageRoute(p.current_stage))
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">หลักสูตรทั้งหมด</h1>
        <button
          onClick={() => navigate('/intake')}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700"
        >
          + สร้างหลักสูตรใหม่
        </button>
      </div>

      {loading && <p className="text-gray-500 text-sm">กำลังโหลด...</p>}

      {error && (
        <div className="text-sm text-red-600">
          {error}{' '}
          <button onClick={load} className="underline">
            ลองใหม่
          </button>
        </div>
      )}

      {!loading && !error && programs.length === 0 && (
        <p className="text-gray-500 text-sm">ยังไม่มีหลักสูตร — เริ่มสร้างหลักสูตรแรกได้เลย</p>
      )}

      {!loading && !error && programs.length > 0 && (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="text-left border-b text-gray-500">
              <th className="py-2 pr-4">ชื่อหลักสูตร</th>
              <th className="py-2 pr-4">ระดับ</th>
              <th className="py-2 pr-4">วันที่สร้าง</th>
              <th className="py-2 pr-4">สถานะ</th>
            </tr>
          </thead>
          <tbody>
            {programs.map((p) => (
              <tr
                key={p.program_id}
                onClick={() => openProgram(p)}
                className="border-b cursor-pointer hover:bg-gray-50"
              >
                <td className="py-2 pr-4">
                  <div className="font-medium">{p.name_th}</div>
                  <div className="text-xs text-gray-400">
                    {p.name_en} · {p.program_id}
                  </div>
                </td>
                <td className="py-2 pr-4">{DEGREE_LABELS[p.degree_level] ?? p.degree_level}</td>
                <td className="py-2 pr-4">
                  {new Date(p.created_at).toLocaleDateString('th-TH', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                  })}
                </td>
                <td className="py-2 pr-4">
                  <span className="inline-block bg-gray-100 rounded px-2 py-0.5 text-xs">
                    {p.current_stage
                      ? (STAGE_LABELS[p.current_stage] ?? p.current_stage)
                      : 'ยังไม่เริ่ม'}
                  </span>
                  {p.session_status && (
                    <span className="ml-2 text-xs text-gray-400">
                      {STATUS_LABELS[p.session_status] ?? p.session_status}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Update `frontend/src/App.tsx`**

```tsx
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import StageLayout from './components/StageLayout'
import Programs from './pages/Programs'
import Intake from './pages/Intake'
import StakeholderNeeds from './pages/StakeholderNeeds'
import SkillExtraction from './pages/SkillExtraction'
import PloSynthesis from './pages/PloSynthesis'
import PloReport from './pages/PloReport'
import Pipeline from './pages/Pipeline'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<StageLayout />}>
          <Route index element={<Programs />} />
          <Route path="intake" element={<Intake />} />
          <Route path="stakeholder-needs" element={<StakeholderNeeds />} />
          <Route path="skill-extraction" element={<SkillExtraction />} />
          <Route path="plo-synthesis" element={<PloSynthesis />} />
          <Route path="plo-report" element={<PloReport />} />
          <Route path="pipeline" element={<Pipeline />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
```

- [ ] **Step 3: Update `frontend/src/components/StageLayout.tsx` nav list**

Replace the `stages` array:

```tsx
const stages = [
  { path: '/', label: '📋 หลักสูตรทั้งหมด' },
  { path: '/intake', label: 'Stage 1: Intake' },
  { path: '/stakeholder-needs', label: 'Stage 2: Stakeholder Needs' },
  { path: '/skill-extraction', label: 'Stage 3: Skill Extraction' },
  { path: '/plo-synthesis', label: 'Stage 4: PLO Synthesis' },
  { path: '/plo-report', label: 'Stage 5: PLO Report' },
  { path: '/pipeline', label: '🔁 Pipeline' },
]
```

(`end={s.path === '/'}` already handles exact matching for the index link — no other change needed.)

- [ ] **Step 4: Lint + build**

Run: `cd frontend && npm run lint && npm run build`
Expected: no errors

- [ ] **Step 5: Manual verification (requires services running)**

With `.\scripts\start-dev.ps1` and `npm run dev` running:
1. Open http://localhost:5173/ → history page renders (empty state or rows).
2. Click "+ สร้างหลักสูตรใหม่" → lands on `/intake`.
3. Create a program → return to `/` → new row appears with stage badge.
4. Click the row → localStorage `ca_program_id` updates and the app navigates to the mapped stage page.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Programs.tsx frontend/src/App.tsx frontend/src/components/StageLayout.tsx
git commit -m "feat(ui): program history landing page; move Intake to /intake"
```
