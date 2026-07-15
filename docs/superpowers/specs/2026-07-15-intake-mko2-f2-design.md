# F2 — Document Upload → LLM Extract (prefill intake)

**วันที่:** 2026-07-15
**Stage:** 0 (intake)
**Branch:** `feature/intake-mko2-f2`
**ต่อจาก:** F1 (merged `ae524f8`) — intake มคอ.2 schema+form

## Overview

ให้ผู้ใช้อัปโหลดเอกสารของมหาวิทยาลัย (มคอ.2 เดิม, ธรรมนูญ, SAR, แผนยุทธศาสตร์ ฯลฯ) ในหน้า Intake แล้วให้ LLM สกัด vision / mission / เอกลักษณ์สถาบัน / อัตลักษณ์บัณฑิต มา **prefill ฟอร์ม** ให้ผู้ใช้ตรวจและแก้ก่อน submit — ไม่ผูกกับ program ใด (เกิดก่อน program_id จะถูก generate)

## Goals

- Endpoint stateless `POST /programs/extract-metadata` รับไฟล์ → คืน field ที่สกัดได้
- Frontend หน้า Intake มีปุ่มอัปโหลด → เติมค่าลงช่องฟอร์มที่ยังว่าง
- LLM ห้ามแต่งข้อมูล — field ที่หาไม่เจอในเอกสารต้องเป็น `null`

## Non-goals (นอก scope)

- ไม่เก็บไฟล์ (ไม่แตะ MinIO/DB) — ไฟล์ parse แล้วทิ้ง
- ไม่ทำ evidence ingestion (นั่นคืองาน stage 1 stakeholder_needs)
- ไม่ extract `philosophy_th` / `program_goals_th` / `program_objectives_th`
- F3 (ISCED classification / name suggestion) — รอบถัดไป

## Field ที่สกัด (4 field, ทุกตัว nullable)

| field | ความหมาย |
|---|---|
| `vision_th` | วิสัยทัศน์ |
| `mission_th` | พันธกิจ |
| `institutional_identity_th` | เอกลักษณ์สถาบัน |
| `student_identity_th` | อัตลักษณ์บัณฑิต/นักศึกษา |

## Design

### 1. Data flow

```
[Intake.tsx] ปุ่ม "อัปโหลดเอกสารมหาลัย" (PDF/DOCX/TXT)
  → multipart POST /programs/extract-metadata (require_api_key)
    → UploadFile → temp file → parse_file() [unstructured] → plain text
      → truncate 8,000 chars → complete_light(ExtractedMetadata, prompt)
    → temp file ถูกลบใน finally เสมอ
  → ExtractedMetadata JSON
→ frontend เติมเฉพาะ field ที่ (ก) ค่าไม่ null และ (ข) ช่องฟอร์มยังว่าง
  — ไม่ทับค่าที่ผู้ใช้พิมพ์แล้ว
```

### 2. Components

**`src/curriculum_agent/models.py`** — เพิ่ม:

```python
class ExtractedMetadata(BaseModel):
    """LLM-extracted university metadata from an uploaded document.

    Every field is None when the document does not state it — the
    extraction prompt forbids fabrication.
    """
    vision_th: str | None = None
    mission_th: str | None = None
    institutional_identity_th: str | None = None
    student_identity_th: str | None = None
```

ไม่ inherit จาก `ProgramCreateRequest` — คนละ concern (extraction result ≠ program entity)

**`src/curriculum_agent/prompts/extract_metadata.py`** — ไฟล์ใหม่:

- `build_extract_metadata_prompt(doc_text: str) -> list[dict[str, Any]]`
- system prompt (ไทย): บทบาทผู้ช่วยสกัดข้อมูลจากเอกสารมหาวิทยาลัย, สกัด 4 field, **กติกา: คัดลอก/เรียบเรียงจากเนื้อหาที่มีในเอกสารเท่านั้น ถ้าไม่พบให้เป็น null ห้ามแต่งเอง**, ตอบภาษาไทยตามต้นฉบับ
- user message: เนื้อหาเอกสาร (truncated)

**`src/curriculum_agent/stages/intake.py`** — เพิ่ม helper (อยู่กับ stage 0 ตามความหมาย):

```python
DOC_TEXT_LIMIT = 8_000  # chars fed to the light model

async def extract_metadata_from_text(text: str) -> ExtractedMetadata:
    messages = build_extract_metadata_prompt(text[:DOC_TEXT_LIMIT])
    return await complete_light(ExtractedMetadata, messages)
```

แยกจาก route เพื่อ test ได้โดยไม่ผ่าน HTTP/ไฟล์

**`src/curriculum_agent/api/routes/programs.py`** — route ใหม่:

- `POST /extract-metadata` (นำหน้า `GET /{program_id}` ใน declaration order — กัน path capture)
- `dependencies=[Depends(require_api_key)]`, รับ `UploadFile`
- ขั้นตอน: ตรวจนามสกุล → ตรวจขนาด → เขียน temp file (`tempfile.NamedTemporaryFile`, suffix ตามไฟล์จริง) → `parse_file()` (sync CPU — เรียกผ่าน `asyncio.to_thread`) → ตรวจ text ไม่ว่าง → `extract_metadata_from_text` → return
- `finally`: ลบ temp file

### 3. Error handling

| กรณี | Response |
|---|---|
| นามสกุลไม่รองรับ (นอกจาก .pdf .docx .doc .txt) | 422 `"รองรับเฉพาะไฟล์ PDF, DOCX, TXT"` |
| ไฟล์ใหญ่เกิน 10 MB | 413 `"ไฟล์ต้องไม่เกิน 10 MB"` |
| parse แล้ว text ว่าง/สั้นกว่า 50 chars | 422 `"อ่านเนื้อหาจากไฟล์ไม่ได้"` |
| `parse_file` โยน exception | 422 `"อ่านเนื้อหาจากไฟล์ไม่ได้"` (log ตัวจริงด้วย loguru) |
| LLM ล้มเหลว (timeout/validation) | 502 `"สกัดข้อมูลไม่สำเร็จ กรุณาลองใหม่หรือกรอกเอง"` |

Error detail เป็นไทย (user-facing) ตาม convention โปรเจกต์

### 4. Frontend (`Intake.tsx`)

- ส่วนหัวฟอร์ม (ก่อนช่อง vision): กล่อง "อัปโหลดเอกสารมหาวิทยาลัยเพื่อเติมข้อมูลอัตโนมัติ" — `<input type="file" accept=".pdf,.docx,.doc,.txt">` + ปุ่ม
- ระหว่างรอ: ปุ่ม disabled + ข้อความ "กำลังสกัดข้อมูล…"
- สำเร็จ: merge ผลลง form state — เฉพาะ field ไม่ null และช่องปัจจุบันว่าง; แสดงสรุป เช่น "เติมข้อมูลแล้ว 3 รายการ (วิสัยทัศน์, พันธกิจ, เอกลักษณ์สถาบัน)" / ถ้า null หมด: "ไม่พบข้อมูลในเอกสาร"
- ล้มเหลว: แสดง error message จาก response
- ส่ง multipart ผ่าน axios instance เดิม (`api`) — ต้องไม่ set `Content-Type` เอง (ให้ browser ใส่ boundary)

### 5. Dependencies

- `python-multipart` — จำเป็นสำหรับ FastAPI `UploadFile`; ตรวจตอน implement (`uv run python -c "import multipart"`) ถ้าไม่มีให้ `uv add python-multipart`
- `unstructured` มีแล้ว (ใช้ใน `tika_parser.py`)

### 6. Testing (TDD)

Unit (`tests/unit/`, LLM + parse mocked):
- `extract_metadata_from_text`: mock `complete_light` → คืนครบ 4 field; ยืนยัน text ถูก truncate ที่ `DOC_TEXT_LIMIT` ก่อนส่งเข้า prompt
- prompt builder: มีคำสั่งห้ามแต่ง/null ใน system message; doc_text อยู่ใน user message
- route (mock `parse_file` + `extract_metadata_from_text`):
  - POST .pdf → 200 + JSON ครบ field
  - นามสกุล .exe → 422
  - ไฟล์เกิน 10 MB → 413
  - parse คืน text ว่าง → 422
  - `complete_light` โยน exception → 502
  - ไม่มี API key (เมื่อ config) → 401

ไม่ test `unstructured` parse จริงใน CI (ช้า/dependency หนัก) — mock เสมอ

## ไฟล์ที่กระทบ

- `src/curriculum_agent/models.py` — `ExtractedMetadata`
- `src/curriculum_agent/prompts/extract_metadata.py` — ใหม่
- `src/curriculum_agent/stages/intake.py` — `extract_metadata_from_text` + `DOC_TEXT_LIMIT`
- `src/curriculum_agent/api/routes/programs.py` — route `POST /extract-metadata`
- `frontend/src/pages/Intake.tsx` — upload UI + merge logic
- `tests/unit/test_extract_metadata.py` — ใหม่
- `pyproject.toml` — `python-multipart` (ถ้ายังไม่มี)

## Open questions / ความเสี่ยง

- เอกสารยาว (มคอ.2 ทั้งเล่ม) — vision/mission มักอยู่หมวด 1 ช่วงต้น จึง truncate หัว 8k chars น่าจะพอสำหรับ PoC; ถ้าพบว่าอยู่ท้ายเอกสารบ่อย ค่อยทำ section detection ภายหลัง
- คุณภาพ extraction ขึ้นกับ light model — สลับไป heavy ได้ผ่าน config โดยเปลี่ยนจุดเรียกเดียว (`complete_light` → `complete_heavy`) ถ้าผลไม่ดี
- `.doc` (เก่า) unstructured อาจ parse ไม่ได้ในบางเครื่อง — ยอมรับ: error path 422 ครอบอยู่
