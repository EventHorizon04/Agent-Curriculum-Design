# Delete Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user permanently delete a program and all its data (evidence, skills, clusters, PLOs, checkpoints, sessions) from the program history page.

**Architecture:** A new `ProgramRepository.delete_cascade()` method deletes the six FK-dependent tables then the `programs` row itself, in one transaction, in an order that respects the one cross-dependency (`skills.source_evidence_id` → `evidence`). A new `DELETE /programs/{program_id}` route exposes it. `Programs.tsx` gets a delete button per row, gated by `window.confirm`.

**Spec:** `docs/superpowers/specs/2026-07-24-delete-program-design.md`

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / Pydantic v2; React 19 + axios.

## Global Constraints

- Type hints on every function signature; `from __future__ import annotations` at top of every Python file.
- Student-facing strings in Thai; code, comments, log messages in English.
- Repository pattern only — no SQL outside `src/curriculum_agent/data/repositories.py`.
- `DELETE /programs/{program_id}` requires `require_api_key`, matching every other mutating route (`POST /programs/`, `DELETE /evidence/{id}`). `GET /programs/` and `GET /programs/{id}` stay key-free — unchanged.
- Hard delete only. No soft-delete flag, no audit table, no undo (out of scope per spec).
- Tests: `asyncio_mode = "auto"` — `@pytest.mark.asyncio` not required.
- No frontend test runner in this repo — frontend verification is `npm run lint && npm run build` plus manual click-through.

---

### Task 1: `ProgramRepository.delete_cascade()`

**Files:**
- Modify: `src/curriculum_agent/data/repositories.py` (import line 6, and inside `ProgramRepository` after `list_all`, ~line 119)
- Test: `tests/unit/test_program_repository.py` (append)

**Interfaces:**
- Consumes: `ProgramTable`, `EvidenceTable`, `SkillTable`, `ClusterTable`, `PLOTable`, `CheckpointTable`, `SessionTable` (all already imported in `repositories.py`); `AsyncSessionLocal` (already imported).
- Produces: `async def delete_cascade(self, program_id: str) -> bool` — `True` if a program row was deleted, `False` if `program_id` didn't exist. Task 2 calls this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_program_repository.py`:

```python
async def test_delete_cascade_deletes_tables_in_fk_safe_order() -> None:
    """skills must be deleted before evidence: SkillTable.source_evidence_id
    is a FK into EvidenceTable. Everything else has no cross-dependency."""
    repo = ProgramRepository()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=1) for _ in range(7)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx
    ):
        result = await repo.delete_cascade("cs")

    assert result is True
    executed_sql = [str(c.args[0]) for c in mock_session.execute.call_args_list]
    assert executed_sql[0].startswith("DELETE FROM skills")
    assert executed_sql[1].startswith("DELETE FROM clusters")
    assert executed_sql[2].startswith("DELETE FROM plos")
    assert executed_sql[3].startswith("DELETE FROM checkpoints")
    assert executed_sql[4].startswith("DELETE FROM sessions")
    assert executed_sql[5].startswith("DELETE FROM evidence")
    assert executed_sql[6].startswith("DELETE FROM programs")


async def test_delete_cascade_returns_false_when_program_missing() -> None:
    repo = ProgramRepository()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=0) for _ in range(7)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx
    ):
        result = await repo.delete_cascade("missing")

    assert result is False


async def test_delete_cascade_commits_once() -> None:
    repo = ProgramRepository()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=1) for _ in range(7)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx
    ):
        await repo.delete_cascade("cs")

    mock_session.commit.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_program_repository.py -k delete_cascade -v`
Expected: FAIL with `AttributeError: 'ProgramRepository' object has no attribute 'delete_cascade'`

- [ ] **Step 3: Write minimal implementation**

In `src/curriculum_agent/data/repositories.py`, change the import line (line 6):

```python
from sqlalchemy import delete, select, update
```

Then add to `ProgramRepository`, directly after `list_all`:

```python
    async def delete_cascade(self, program_id: str) -> bool:
        """Hard-delete a program and everything under it, in one transaction.

        Deletes skills before evidence because SkillTable.source_evidence_id
        is a FK into EvidenceTable. Returns False (no-op) if program_id
        doesn't exist — the six prior deletes affect zero rows either way.
        """
        async with AsyncSessionLocal() as session:
            await session.execute(delete(SkillTable).where(SkillTable.program_id == program_id))
            await session.execute(
                delete(ClusterTable).where(ClusterTable.program_id == program_id)
            )
            await session.execute(delete(PLOTable).where(PLOTable.program_id == program_id))
            await session.execute(
                delete(CheckpointTable).where(CheckpointTable.program_id == program_id)
            )
            await session.execute(
                delete(SessionTable).where(SessionTable.program_id == program_id)
            )
            await session.execute(
                delete(EvidenceTable).where(EvidenceTable.program_id == program_id)
            )
            result = await session.execute(
                delete(ProgramTable).where(ProgramTable.program_id == program_id)
            )
            await session.commit()
            return result.rowcount > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_program_repository.py -v`
Expected: 7 PASSED (4 existing `list_all` tests + 3 new `delete_cascade` tests)

- [ ] **Step 5: Run lint + typecheck**

Run: `uv run ruff check src/ tests/ && uv run mypy src/`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/data/repositories.py tests/unit/test_program_repository.py
git commit -m "feat(data): add ProgramRepository.delete_cascade"
```

---

### Task 2: `DELETE /programs/{program_id}` route

**Files:**
- Modify: `src/curriculum_agent/api/routes/programs.py` (append after `get_program`, end of file)
- Test: `tests/unit/test_api_programs.py` (append)

**Interfaces:**
- Consumes: `ProgramRepository.delete_cascade()` (Task 1).
- Produces: `DELETE /programs/{program_id}` → `204` on success, `404` with `detail="ไม่พบหลักสูตรนี้"` when not found. Requires `X-API-Key` when `settings.api_key` is configured (same as `POST /programs/`). Task 3 (frontend) calls this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_api_programs.py`:

```python
def test_delete_program_success() -> None:
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.delete_cascade = AsyncMock(return_value=True)
        mock_repo_cls.return_value = mock_repo
        resp = client.delete("/programs/computer-science")
    assert resp.status_code == 204, f"got {resp.status_code}"


def test_delete_program_not_found() -> None:
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.delete_cascade = AsyncMock(return_value=False)
        mock_repo_cls.return_value = mock_repo
        resp = client.delete("/programs/missing-program")
    assert resp.status_code == 404, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"] == "ไม่พบหลักสูตรนี้"


def test_delete_program_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")
    resp = client.delete("/programs/computer-science")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"] == "API key ไม่ถูกต้องหรือไม่ได้ระบุ"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_api_programs.py -k delete_program -v`
Expected: FAIL — `DELETE /programs/{program_id}` returns 405 (no DELETE route registered yet)

- [ ] **Step 3: Write minimal implementation**

Append to `src/curriculum_agent/api/routes/programs.py` (end of file, after `get_program`):

```python
@router.delete("/{program_id}", status_code=204, dependencies=[Depends(require_api_key)])
async def delete_program(program_id: str) -> None:
    repo = ProgramRepository()
    deleted = await repo.delete_cascade(program_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")
```

No new imports needed — `Depends`, `HTTPException`, `require_api_key`, and `ProgramRepository` are already imported in this file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_api_programs.py -v`
Expected: all PASSED (new + existing)

- [ ] **Step 5: Run lint + typecheck + full test suite**

Run: `uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest`
Expected: no errors, all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/curriculum_agent/api/routes/programs.py tests/unit/test_api_programs.py
git commit -m "feat(api): add DELETE /programs/{program_id}"
```

---

### Task 3: Frontend delete button + confirm

**Files:**
- Modify: `frontend/src/pages/Programs.tsx`

**Interfaces:**
- Consumes: `DELETE /programs/{program_id}` (Task 2) via the existing `api` axios instance (`frontend/src/api/client.ts`); existing `load()` function in this file to refresh the list after delete.
- Produces: a "ลบ" button per row; no new exported interface (leaf UI change).

No frontend test runner exists in this repo — verification is `npm run lint && npm run build` plus manual check.

- [ ] **Step 1: Add the delete handler and table column**

In `frontend/src/pages/Programs.tsx`, add a `handleDelete` function directly after `openProgram` (currently ending at line 78):

```tsx
  const handleDelete = async (e: React.MouseEvent, p: ProgramSummary) => {
    e.stopPropagation()
    if (!window.confirm(`ลบหลักสูตร "${p.name_th}" ทั้งหมด? ข้อมูลจะหายถาวรและกู้คืนไม่ได้`)) {
      return
    }
    try {
      await api.delete(`/programs/${p.program_id}`)
      await load()
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail ?? 'ลบหลักสูตรไม่สำเร็จ')
    }
  }
```

Then update the table `<thead>` (currently lines 109-116) to add a header cell:

```tsx
          <thead>
            <tr className="text-left border-b text-gray-500">
              <th className="py-2 pr-4">ชื่อหลักสูตร</th>
              <th className="py-2 pr-4">ระดับ</th>
              <th className="py-2 pr-4">วันที่สร้าง</th>
              <th className="py-2 pr-4">สถานะ</th>
              <th className="py-2 pr-4"></th>
            </tr>
          </thead>
```

And add a cell at the end of the row body (currently the `<td>` block ends at line 149, right before the closing `</tr>` on line 150):

```tsx
                <td className="py-2 pr-4">
                  <button
                    onClick={(e) => handleDelete(e, p)}
                    className="text-red-600 hover:underline text-xs"
                  >
                    ลบ
                  </button>
                </td>
```

- [ ] **Step 2: Lint + build**

Run: `cd frontend && npm run lint && npm run build`
Expected: no errors

- [ ] **Step 3: Manual verification (requires services running)**

With `.\scripts\start-dev.ps1` and `npm run dev` running:
1. Open http://localhost:5173/ — each row shows a "ลบ" button.
2. Click "ลบ" on a row → browser confirm dialog appears with the program's Thai name.
3. Cancel the dialog → row still present, nothing happened.
4. Confirm the dialog → row disappears from the list, program is gone from `GET /programs/`.
5. Click a row's name (not the delete button) → still navigates to resume the program (delete button didn't interfere with row click).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Programs.tsx
git commit -m "feat(ui): add delete button to program history page"
```
