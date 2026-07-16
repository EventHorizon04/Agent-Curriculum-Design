# Stakeholder Needs — Cancel Upload + Delete Evidence

**วันที่:** 2026-07-16
**Stage:** 1 (stakeholder_needs)
**Branch:** `feature/stakeholder-needs-cancel-delete`

## Overview

หน้า "ขั้นตอนที่ 2 — หลักฐานผู้มีส่วนได้ส่วนเสีย" (`StakeholderNeeds.tsx`) ปัจจุบันเลือกไฟล์แล้วอัปโหลดทันที ไม่มีขั้นตอนตรวจสอบก่อน และไม่มีทางลบหลักฐานที่อัปโหลดผิดพลาดไปแล้ว งานนี้เพิ่มสองความสามารถ: (1) ยกเลิกไฟล์ที่เลือกไว้ก่อนกดอัปโหลดจริง (2) ลบหลักฐานที่ persist ไปแล้วในกรณีอัปโหลดผิด

## Goals

- เลือกไฟล์ → staging ก่อนส่ง (ไม่ auto-submit) — มีปุ่ม "อัปโหลด" / "ยกเลิก"
- แต่ละหลักฐานในลิสต์มีปุ่ม "ลบ" พร้อม inline confirm กันลบพลาด
- ลบหลักฐานที่ถูกใช้สกัดทักษะไปแล้ว (stage 2) ต้องถูกกันไว้ พร้อม error message ที่เข้าใจง่าย

## Non-goals

- ไม่แตะฟอร์มกรอกข้อความ manual (source_name + textarea) — cancel/delete นี้เกี่ยวกับ path อัปโหลดไฟล์และลิสต์หลักฐานเท่านั้น (ปุ่มลบใช้ได้กับหลักฐานทุกแหล่งที่มาในลิสต์ ทั้งจากไฟล์และจากฟอร์ม manual)
- ไม่ cascade ลบไปถึง skills/clusters/plos ที่อ้างอิงหลักฐานนี้แล้ว — ถ้ามีการอ้างอิงอยู่ ต้องบล็อกการลบ ไม่ใช่ลบทิ้งทั้งคู่
- ไม่ทำ bulk delete, undo, หรือ soft-delete
- ไม่ preview เนื้อหาไฟล์ก่อนอัปโหลด — โชว์แค่ชื่อไฟล์

## Design

### 1. Cancel-before-upload (frontend only)

**State เปลี่ยนจาก:**
```typescript
async function handleFileUpload(e) { /* อ่านไฟล์ + postEvidence ทันที */ }
```

**เป็น:**
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
  if (!text.trim()) { setFileError('ไฟล์ว่างเปล่า'); return }  // ไม่เคลียร์ pendingFile
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

**UI:** label "อัปโหลดเอกสาร" (Intake.tsx เดิม, บรรทัด ~286-300) แสดงเมื่อ `!pendingFile`; เมื่อมี `pendingFile` สลับเป็นแถบ:

```
[ไอคอนไฟล์] ชื่อไฟล์.txt        [ยกเลิก]  [อัปโหลด]
```

`fileError` แสดงเป็นบรรทัดเล็กสีแดงใต้แถบ (ไม่ใช้ `error` state ส่วนกลาง — เพื่อไม่ปนกับ error ของฟอร์ม manual/list)

### 2. Delete evidence (backend + frontend)

**Backend — `data/repositories.py`, class `EvidenceRepository`:**

```python
async def delete(self, evidence_id: str) -> bool:
    """Delete one evidence row. Returns False if it didn't exist.

    Raises the underlying DB exception (unchanged) if a skill's
    source_evidence_id FK still references this row — the route maps
    that to a 409 for the caller.
    """
    async with AsyncSessionLocal() as session:
        row = await session.get(EvidenceTable, evidence_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
```

**Route — `api/routes/evidence.py`:**

```python
from sqlalchemy.exc import IntegrityError

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

(เพิ่ม `HTTPException` เข้า import จาก `fastapi` ที่หัวไฟล์)

**Frontend — `StakeholderNeeds.tsx`:**

- state ใหม่: `confirmingDeleteId: string | null` (evidence_id ที่กำลังรอ confirm)
- ปุ่ม "ลบ" ต่อการ์ด (ในแถว `<summary>` ข้าง badge classification): คลิกครั้งแรก → `setConfirmingDeleteId(item.evidence_id)` เปลี่ยนปุ่มเป็น "ยืนยันลบ?" (สีแดงเข้ม) — คลิกอีกครั้งที่ปุ่มเดียวกัน → เรียก `handleDelete`
- auto-revert `confirmingDeleteId` กลับ `null` หลัง 3 วินาที (`setTimeout`, เคลียร์ timeout เมื่อ unmount/re-trigger) หรือเมื่อคลิกปุ่มลบของการ์ดอื่น
- `handleDelete(evidenceId)`: `await api.delete(`/programs/${programId}/evidence/${evidenceId}`)` → ลบออกจาก `items` (optimistic, ทันทีหลัง response 204) + `setSuccess('ลบหลักฐานสำเร็จ')`; ถ้า error (409/404) → `setError(err.response.data.detail)`, ไม่แตะ `items`
- ปุ่มลบต้อง `e.stopPropagation()` / อยู่นอก `<summary>` click target ไม่ให้ toggle `<details>` เปิด/ปิดพร้อมกับกดลบ (ปัจจุบัน `<summary>` ทั้งแถวคือ toggle — ต้องแยกปุ่มออกจาก click area ของ summary หรือใช้ `onClick` ที่ `stopPropagation`)

### 3. Testing

**Backend (`tests/unit/test_evidence_routes.py` — ใหม่, ไม่มีไฟล์ทดสอบ evidence routes อยู่ก่อน):**
- `EvidenceRepository.delete`: ลบ row ที่มีอยู่ → คืน `True`, row หายจริง (mock session หรือ integration ตาม convention เดิม); ลบ id ที่ไม่มี → คืน `False`
- Route: DELETE สำเร็จ → 204; DELETE id ไม่มี → 404; DELETE ที่ชน FK (mock `_repo.delete` raise `IntegrityError`) → 409 พร้อมข้อความไทย; ไม่มี API key (เมื่อ config) → 401

**Frontend:** ไม่มี test runner — verify ด้วย `npm run build` + `npm run lint`

## ไฟล์ที่กระทบ

- `src/curriculum_agent/data/repositories.py` — `EvidenceRepository.delete`
- `src/curriculum_agent/api/routes/evidence.py` — route `DELETE /{evidence_id}`
- `frontend/src/pages/StakeholderNeeds.tsx` — cancel-before-upload flow + ปุ่มลบ + confirm
- `tests/unit/test_evidence_routes.py` — ใหม่

## Open questions / ความเสี่ยง

- ต้องตรวจตอน implement ว่า SQLAlchemy async + asyncpg โยน `sqlalchemy.exc.IntegrityError` จริงสำหรับ FK violation (ไม่ใช่ exception ชนิดอื่น) — ถ้าไม่ตรงต้องปรับ `except` clause; ยืนยันได้ด้วย integration test จริงกับ ca-postgres (สร้าง evidence → skill ที่อ้างอิงมัน → ลอง delete evidence → ดู exception type จริง) ก่อน implement route
