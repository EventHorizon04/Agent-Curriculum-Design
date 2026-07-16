# Stakeholder Needs — Cancel Upload + Delete Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** เพิ่มขั้นตอนตรวจสอบก่อนอัปโหลดไฟล์หลักฐาน (ยกเลิกได้ก่อนส่ง) และเพิ่มปุ่มลบหลักฐานที่ persist ไปแล้ว (พร้อมกันลบถ้าถูกใช้สกัดทักษะแล้ว)

**Architecture:** Backend เพิ่ม `EvidenceRepository.delete(evidence_id) -> bool` + route `DELETE /programs/{program_id}/evidence/{evidence_id}` — FK บน `skills.source_evidence_id` กันการลบที่ถูกใช้แล้วโดยธรรมชาติ (ยืนยันแล้วด้วยการทดสอบจริงกับ ca-postgres: SQLAlchemy async + asyncpg โยน `sqlalchemy.exc.IntegrityError` แน่นอน) — route แค่ catch แล้วแปลงเป็น 409 ภาษาไทย ไม่ต้องเช็ก reference เองล่วงหน้า. Frontend เปลี่ยน flow อัปโหลดไฟล์จาก auto-submit เป็น staging (เลือกไฟล์ → ปุ่มยกเลิก/อัปโหลด) และเพิ่มปุ่มลบต่อการ์ดหลักฐาน พร้อม inline confirm 2 คลิก

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async + asyncpg, pytest, React 19 + TypeScript + Tailwind

**Spec:** `docs/superpowers/specs/2026-07-16-stakeholder-needs-cancel-delete-design.md`

## Global Constraints

- ทุกไฟล์ `.py` ขึ้นต้นด้วย `from __future__ import annotations`; type hints ทุก function signature
- `loguru` เท่านั้นสำหรับ logging (ห้าม stdlib `logging`)
- Thai สำหรับ string ที่ผู้ใช้เห็น (รวม HTTPException detail); code/comment/variable อังกฤษ
- FK violation เมื่อลบ evidence ที่มี skill อ้างอิงอยู่ ยืนยันแล้วว่าโยน `sqlalchemy.exc.IntegrityError` (ทดสอบจริงกับ ca-postgres, ข้อความ asyncpg ภายใน: `ForeignKeyViolationError` บน constraint `skills_source_evidence_id_fkey`) — import `IntegrityError` จาก `sqlalchemy.exc`
- `evidence.py` ใช้ module-level singleton `_repo = EvidenceRepository()` (ไม่เหมือน `programs.py` ที่สร้างใหม่ต่อ request) — test ต้อง `patch.object` บน instance `_repo` ไม่ใช่ patch class
- ต้องผ่าน `uv run ruff check src/ tests/`, `uv run mypy src/` (มี pre-existing errors — ห้ามเพิ่ม category ใหม่), `uv run pytest`
- Frontend ผ่าน `npm run lint` + `npm run build` (ไม่มี test runner)

## File Structure

- `src/curriculum_agent/data/repositories.py` — เพิ่ม `EvidenceRepository.delete` (Task 1)
- `src/curriculum_agent/api/routes/evidence.py` — เพิ่ม route `DELETE /{evidence_id}` (Task 1)
- `tests/unit/test_evidence_routes.py` — ใหม่: repository + route tests (Task 1)
- `frontend/src/pages/StakeholderNeeds.tsx` — cancel-before-upload + ปุ่มลบ + confirm (Task 2)

---

### Task 1: Backend — `EvidenceRepository.delete` + route `DELETE /{evidence_id}`

**Files:**
- Modify: `src/curriculum_agent/data/repositories.py` (class `EvidenceRepository`, หลัง `list_by_program`)
- Modify: `src/curriculum_agent/api/routes/evidence.py`
- Create: `tests/unit/test_evidence_routes.py`

**Interfaces:**
- Produces:
  - `EvidenceRepository.delete(evidence_id: str) -> bool` — `True` ถ้าลบสำเร็จ, `False` ถ้าไม่พบ row; โยน `sqlalchemy.exc.IntegrityError` ต่อขึ้นไปถ้าถูก FK บล็อก (ไม่ catch ใน repository — route เป็นคนแปลง)
  - `DELETE /programs/{program_id}/evidence/{evidence_id}` — 204 สำเร็จ, 404 ไม่พบ, 409 ถูก FK บล็อก, 401 ไม่มี/ผิด API key

- [ ] **Step 1: เขียน failing tests**

สร้าง `tests/unit/test_evidence_routes.py`:

```python
# tests/unit/test_evidence_routes.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import evidence as evidence_module

client = TestClient(app)


def test_delete_evidence_success() -> None:
    with patch.object(evidence_module._repo, "delete", new=AsyncMock(return_value=True)):
        resp = client.delete("/programs/cs-2025/evidence/ev-1")
    assert resp.status_code == 204, f"got {resp.status_code}: {resp.text}"


def test_delete_evidence_not_found_returns_404() -> None:
    with patch.object(evidence_module._repo, "delete", new=AsyncMock(return_value=False)):
        resp = client.delete("/programs/cs-2025/evidence/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "ไม่พบหลักฐานนี้"


def test_delete_evidence_blocked_by_fk_returns_409() -> None:
    fk_error = IntegrityError("DELETE FROM evidence ...", {}, Exception("FK violation"))
    with patch.object(evidence_module._repo, "delete", new=AsyncMock(side_effect=fk_error)):
        resp = client.delete("/programs/cs-2025/evidence/ev-used-by-skill")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "ลบไม่ได้ — หลักฐานนี้ถูกใช้ในการสกัดทักษะแล้ว"


def test_delete_evidence_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")
    resp = client.delete("/programs/cs-2025/evidence/ev-1")
    assert resp.status_code == 401
```

- [ ] **Step 2: รัน test ยืนยัน fail**

Run: `uv run pytest tests/unit/test_evidence_routes.py -v`
Expected: FAIL — 405 Method Not Allowed (route ยังไม่มี) สำหรับ 3 test แรก; test API key ก็ fail เช่นกัน (405 ≠ 401)

- [ ] **Step 3: เพิ่ม `delete` ใน `EvidenceRepository`**

ใน `repositories.py` เพิ่มหลัง method `list_by_program` (ในคลาส `EvidenceRepository`):

```python
    async def delete(self, evidence_id: str) -> bool:
        """Delete one evidence row. Returns False if it didn't exist.

        Propagates sqlalchemy.exc.IntegrityError unchanged if a skill's
        source_evidence_id FK still references this row — the route maps
        that to a 409 for the caller. Confirmed empirically: SQLAlchemy
        async + asyncpg raises IntegrityError (wrapping asyncpg's
        ForeignKeyViolationError) on this exact constraint.
        """
        async with AsyncSessionLocal() as session:
            row = await session.get(EvidenceTable, evidence_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True
```

(`AsyncSessionLocal`, `EvidenceTable` ต้อง import อยู่แล้วที่หัวไฟล์ — ตรวจว่ามีจริงก่อนแก้)

- [ ] **Step 4: เพิ่ม route ใน `evidence.py`**

เพิ่ม import ที่หัวไฟล์:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
```

(แก้บรรทัด `from fastapi import APIRouter, Depends` เดิมให้มี `HTTPException` เพิ่ม)

เพิ่ม route ท้ายไฟล์ (หลัง `classify_evidence_stream`):

```python
@router.delete("/{evidence_id}", status_code=204, dependencies=[Depends(require_api_key)])
async def delete_evidence(program_id: str, evidence_id: str) -> None:
    try:
        deleted = await _repo.delete(evidence_id)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="ลบไม่ได้ — หลักฐานนี้ถูกใช้ในการสกัดทักษะแล้ว",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="ไม่พบหลักฐานนี้")
```

หมายเหตุ: `program_id` เป็น path param ที่ FastAPI bind จาก router prefix (`/programs/{program_id}/evidence`) เหมือน route อื่นในไฟล์นี้ — รับไว้เพื่อความชัดเจนของ path แม้ตัว logic จะใช้แค่ `evidence_id` (evidence_id เป็น PK เดี่ยวพอสำหรับ lookup)

- [ ] **Step 5: รัน test ยืนยัน pass + ไม่มี regression**

Run: `uv run pytest tests/unit/test_evidence_routes.py -v`
Expected: PASS ทั้งหมด (4 tests)

Run: `uv run pytest -q`
Expected: PASS ทั้งหมด

- [ ] **Step 6: lint + type check**

Run: `uv run ruff check src/ tests/; uv run mypy src/`
Expected: ruff clean; mypy ไม่มี error ใหม่

- [ ] **Step 7: Commit**

```bash
git add src/curriculum_agent/data/repositories.py src/curriculum_agent/api/routes/evidence.py tests/unit/test_evidence_routes.py
git commit -m "feat(api): DELETE /programs/{id}/evidence/{evidence_id} with FK-conflict guard"
```

---

### Task 2: Frontend — cancel-before-upload + delete button

**Files:**
- Modify: `frontend/src/pages/StakeholderNeeds.tsx`

**Interfaces:**
- Consumes: `DELETE /programs/{program_id}/evidence/{evidence_id}` (Task 1) — 204 สำเร็จ, error `detail` บน 404/409

- [ ] **Step 1: แทนที่ auto-submit ด้วย staging state**

ลบ `handleFileUpload` เดิม (StakeholderNeeds.tsx:108-121) แทนที่ด้วย:

```typescript
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    setPendingFile(file ?? null)
    setFileError('')
  }

  function handleCancelFile() {
    setPendingFile(null)
    setFileError('')
    if (fileRef.current) fileRef.current.value = ''
  }

  async function handleConfirmUpload() {
    if (!pendingFile || !programId) return
    const text = await pendingFile.text()
    if (!text.trim()) { setFileError('ไฟล์ว่างเปล่า'); return }
    await postEvidence({
      evidence_id: crypto.randomUUID(),
      program_id: programId,
      stakeholder_type: stakeholderType,
      source_name: pendingFile.name,
      raw_text_th: text,
    })
    setPendingFile(null)
    if (fileRef.current) fileRef.current.value = ''
  }
```

เพิ่ม state ทั้งสองบรรทัดนี้ไว้ใกล้ `fileRef` ที่ประกาศอยู่แล้ว (StakeholderNeeds.tsx:54)

- [ ] **Step 2: แก้ JSX ส่วนอัปโหลดไฟล์**

แทนที่ block `<label>...อัปโหลดเอกสาร...</label>` (StakeholderNeeds.tsx:286-300) ด้วย:

```tsx
              {!pendingFile ? (
                <label className="flex items-center gap-2 text-sm text-gray-500 hover:text-blue-600 cursor-pointer transition-colors group">
                  <svg
                    className="w-4 h-4 group-hover:text-blue-600"
                    fill="none" stroke="currentColor" viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                  </svg>
                  อัปโหลดเอกสาร
                  <span className="text-xs text-gray-400">(.txt, .md, .csv)</span>
                  <input
                    ref={fileRef} type="file" accept=".txt,.md,.csv"
                    onChange={handleFileSelect} className="hidden"
                  />
                </label>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-gray-600 truncate max-w-[200px]">
                      📄 {pendingFile.name}
                    </span>
                    <button
                      type="button" onClick={handleCancelFile}
                      className="text-xs text-gray-500 hover:text-gray-700 underline cursor-pointer"
                    >
                      ยกเลิก
                    </button>
                    <button
                      type="button" onClick={handleConfirmUpload} disabled={submitting}
                      className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-xs font-medium px-3 py-1 rounded-lg transition-colors cursor-pointer disabled:cursor-not-allowed"
                    >
                      {submitting ? 'กำลังอัปโหลด...' : 'อัปโหลด'}
                    </button>
                  </div>
                  {fileError && <p className="text-xs text-red-600">{fileError}</p>}
                </div>
              )}
```

- [ ] **Step 3: เพิ่ม delete state + handler**

เพิ่มหลัง state `classifyProgress` (StakeholderNeeds.tsx:53):

```typescript
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  const confirmRevertTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  function handleDeleteClick(evidenceId: string) {
    if (confirmingDeleteId === evidenceId) {
      if (confirmRevertTimer.current) clearTimeout(confirmRevertTimer.current)
      setConfirmingDeleteId(null)
      handleDelete(evidenceId)
      return
    }
    if (confirmRevertTimer.current) clearTimeout(confirmRevertTimer.current)
    setConfirmingDeleteId(evidenceId)
    confirmRevertTimer.current = setTimeout(() => setConfirmingDeleteId(null), 3000)
  }

  async function handleDelete(evidenceId: string) {
    if (!programId) return
    setError('')
    setSuccess('')
    try {
      await api.delete(`/programs/${programId}/evidence/${evidenceId}`)
      setItems(prev => prev.filter(item => item.evidence_id !== evidenceId))
      setSuccess('ลบหลักฐานสำเร็จ')
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail ?? 'ลบหลักฐานไม่สำเร็จ')
    }
  }
```

หมายเหตุ: `useRef` ต้อง import อยู่แล้ว (StakeholderNeeds.tsx:1 มี `useRef` อยู่แล้วสำหรับ `fileRef`)

- [ ] **Step 4: เพิ่มปุ่มลบในการ์ดหลักฐาน**

แก้ `<summary>` block (StakeholderNeeds.tsx:358-367) — เพิ่มปุ่มลบก่อน badge classification ปิดท้าย และกัน `<details>` toggle ตอนกดปุ่ม:

```tsx
                    <summary className="flex items-center justify-between px-4 py-3 cursor-pointer list-none select-none">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-medium text-gray-700 text-sm shrink-0">{typeLabel}</span>
                        <span className="text-gray-300">—</span>
                        <span className="text-gray-600 text-sm truncate">{item.source_name}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0 ml-3">
                        <button
                          type="button"
                          onClick={e => { e.preventDefault(); e.stopPropagation(); handleDeleteClick(item.evidence_id) }}
                          className={`text-xs font-medium px-2 py-0.5 rounded-full transition-colors cursor-pointer ${
                            confirmingDeleteId === item.evidence_id
                              ? 'bg-red-600 text-white hover:bg-red-700'
                              : 'text-red-400 hover:bg-red-50 hover:text-red-600'
                          }`}
                        >
                          {confirmingDeleteId === item.evidence_id ? 'ยืนยันลบ?' : 'ลบ'}
                        </button>
                        <span className={`text-xs font-medium px-2.5 py-0.5 rounded-full ${cs.cls}`}>
                          {cs.label}
                        </span>
                      </div>
                    </summary>
```

(`<summary>` เป็น native disclosure element — `e.preventDefault()` บนปุ่มลบกัน browser toggle `<details>` เปิด/ปิดตอนคลิกปุ่ม เพราะ default click บน `<summary>` หรือลูกของมันจะ toggle เสมอถ้าไม่ preventDefault)

- [ ] **Step 5: verify build + lint**

Run: `cd frontend; npm run build; npm run lint`
Expected: build สำเร็จ, eslint 0 errors (warning เดิมใน Pipeline.tsx ยอมรับได้)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/StakeholderNeeds.tsx
git commit -m "feat(ui): cancel-before-upload staging + delete-evidence button with confirm"
```

---

## Self-Review

**Spec coverage:**
- Cancel-before-upload (staging, ปุ่มยกเลิก/อัปโหลด) → Task 2 Step 1-2 ✓
- ปุ่มลบ + inline confirm 2 คลิก + auto-revert 3 วิ → Task 2 Step 3-4 ✓
- Backend delete + FK guard 409 → Task 1 ✓
- 404 ไม่พบ, 401 ไม่มี API key → Task 1 tests ✓
- Non-goals (ไม่แตะฟอร์ม manual, ไม่ cascade, ไม่ bulk/undo/soft-delete, ไม่ preview เนื้อหาไฟล์) → ไม่มี task ✓ (ตั้งใจ)

**Placeholder scan:** ไม่มี TBD/TODO; ทุก step มี code/command จริง; exception type + constraint name ยืนยันจากการทดสอบจริงกับ ca-postgres ไม่ใช่การเดา

**Type consistency:** `EvidenceRepository.delete` (Task 1) signature `(evidence_id: str) -> bool` ตรงกับที่ route เรียกใช้; module-level `_repo` singleton ที่ route ใช้ตรงกับที่ test patch (`evidence_module._repo`); frontend `handleDelete`/`handleDeleteClick` (Task 2) เรียก endpoint ตรงกับ path Task 1 กำหนด (`/programs/{program_id}/evidence/{evidence_id}`)
