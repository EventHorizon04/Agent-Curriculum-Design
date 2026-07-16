# F3 — ISCED Classification + Name Suggestion

**วันที่:** 2026-07-16
**Stage:** 0 (intake)
**Branch:** `feature/intake-mko2-f3`
**ต่อจาก:** F1 (merged `ae524f8`), F2 (merged `1f174a3`)

## Overview

ช่วยผู้ใช้ตั้งชื่อหลักสูตรให้สอดคล้องมาตรฐานสากล ISCED-F 2013 (UNESCO): ผู้ใช้กรอกชื่อ/สาขา → กดปุ่ม → LLM จำแนกเข้า ISCED detailed field (4 หลัก) จาก closed list ใน repo + แนะนำชื่อหลักสูตรมาตรฐาน 2-3 ชื่อ (TH/EN) ให้เลือกใช้ → `isced_code` ถูกเก็บลง program ตอน submit (CHECO ใช้ต่อได้)

## Goals

- Taxonomy ISCED-F 2013 (broad/narrow/detailed, code + name_en + name_th) เป็น static module ใน repo
- Endpoint stateless `POST /programs/suggest-isced` — classify + suggest names, **code ต้องมาจาก taxonomy เท่านั้น** (validate + retry 1 ครั้ง)
- ฟอร์ม Intake มีปุ่มเรียกใช้ การ์ดผลลัพธ์ ปุ่ม "ใช้ชื่อนี้" และเก็บ `isced_code` (optional) ลง DB

## Non-goals (นอก scope)

- ไม่ auto-classify ตอน submit — ผู้ใช้กดปุ่มเองเท่านั้น
- ไม่แตะ CHECO exporter (แค่เตรียม field ให้)
- ไม่ทำ ISCED-A (level of education) — เฉพาะ ISCED-F (field)
- ไม่ทำ autocomplete/dropdown taxonomy ใน UI (ทางเลือก B ที่ตัดไป)

## Design

### 1. Data flow

```
[Intake.tsx] name_th + name_en + field กรอกแล้ว → ปุ่ม "ตรวจสอบ ISCED / แนะนำชื่อ"
  → POST /programs/suggest-isced {name_th, name_en, field}  (require_api_key)
    → LLM light: classify จาก detailed list ใน prompt + แนะนำชื่อ
    → validate code กับ taxonomy:
        ไม่พบ → retry 1 ครั้ง (prompt บอกว่า code เดิมผิด ให้เลือกใหม่จาก list)
        ยังไม่พบ → 502
  → IscedSuggestion JSON
→ การ์ดผลลัพธ์: [code + ชื่อหมวด EN/TH] + เหตุผล + ชื่อแนะนำ (ปุ่ม "ใช้ชื่อนี้" ต่อรายการ)
→ "ใช้ชื่อนี้" เติม name_th + name_en ทับค่าเดิม (ผู้ใช้ตัดสินใจเองแล้ว)
→ submit: isced_code เข้า payload → Pydantic validate → เก็บ DB
```

Stateless เหมือน `/extract-metadata` — ไม่ผูก program_id, ไม่แตะ DB ใน endpoint

### 2. ISCED taxonomy module — `src/curriculum_agent/data/isced.py`

- Frozen dataclass หรือ plain tuple constants:

```python
class IscedField(NamedTuple):
    code: str        # "0613"
    name_en: str     # "Software and applications development and analysis"
    name_th: str     # "การพัฒนาและวิเคราะห์ซอฟต์แวร์และแอปพลิเคชัน"
```

- ข้อมูล 3 ระดับตาม ISCED-F 2013 official structure:
  - `BROAD_FIELDS` — 11 รายการ (00 Generic, 01 Education, …, 10 Services)
  - `NARROW_FIELDS` — ~29 รายการ (011, 021, …)
  - `DETAILED_FIELDS` — ~80 รายการ (0111, …, 1041) — **ระดับที่ใช้ classify**
- `name_th` แปลอิงเอกสาร อว./สกอ. ที่ใช้ ISCED; รายการที่ไม่มีคำแปลทางการ ใช้คำแปลตรงความหมาย
- Helpers:
  - `get_detailed_field(code: str) -> IscedField | None`
  - `all_detailed_fields() -> list[IscedField]` (สำหรับ prompt + validator)
- Integrity test บังคับ: code ไม่ซ้ำ, detailed 4 หลัก, prefix 3 หลักของ detailed ต้องมีใน narrow, prefix 2 หลักของ narrow ต้องมีใน broad

### 3. Schema + DB

**`models.py`:**

```python
class SuggestedName(BaseModel):
    name_th: str
    name_en: str


class IscedSuggestion(BaseModel):
    isced_code: str
    field_name_en: str
    field_name_th: str
    rationale_th: str
    suggested_names: list[SuggestedName] = Field(min_length=1, max_length=3)
```

**`ProgramCreateRequest`** เพิ่ม field (ตำแหน่งหลัง `field`):

```python
    isced_code: str | None = None
```

- validator: ถ้าไม่ `None` ต้อง `get_detailed_field(isced_code)` ไม่เป็น `None` — ผิด raise `ValueError` (ข้อความไทย)
- `ProgramMetadata` inherit ตามปกติ — nullable ไม่มีปัญหา legacy row (บทเรียน F1: strictness ที่ input โดนแล้ว — ตัวนี้ optional ทั้งคู่ ไม่ต้อง override)

**ORM + migration:**
- `ProgramTable` เพิ่ม `isced_code: Mapped[str | None] = mapped_column(String(10), nullable=True)`
- Migration ใหม่ (down_revision = head ปัจจุบัน ตรวจตอน implement) — nullable ไม่ต้อง server_default

### 4. Prompt — `prompts/suggest_isced.py`

- `build_suggest_isced_prompt(name_th: str, name_en: str, field: str, retry_invalid_code: str | None = None) -> list[dict]`
- system (ไทย): บทบาทผู้เชี่ยวชาญจำแนกหลักสูตรตาม ISCED-F 2013; แนบ detailed list ทั้งหมด (`code<TAB>name_en` บรรทัดละรายการ ~2k tokens); กติกา:
  - เลือก `isced_code` จากรายการที่ให้เท่านั้น
  - `suggested_names` 2-3 ชื่อ ตามแบบแผนการตั้งชื่อหลักสูตร/ปริญญาไทย (เช่น "หลักสูตรวิทยาศาสตรบัณฑิต สาขาวิชา…") คู่ชื่อ EN ("Bachelor of Science Program in …")
  - `rationale_th` สั้น ≤2 ประโยค
- ถ้า `retry_invalid_code` ไม่ None: เติมบรรทัดเตือน "ครั้งก่อนคุณตอบ {code} ซึ่งไม่อยู่ในรายการ — เลือกใหม่จากรายการเท่านั้น"

### 5. Service helper — `stages/intake.py`

```python
async def suggest_isced(name_th: str, name_en: str, field: str) -> IscedSuggestion:
    """Classify program into ISCED-F 2013 + suggest standard names.

    Code must exist in the embedded taxonomy; one retry with the invalid
    code named, then ValueError for the route to map to 502.
    """
```

- เรียก `complete_light(IscedSuggestion, messages)` → เช็ก `get_detailed_field(result.isced_code)`
- ไม่ผ่าน → retry ด้วย `retry_invalid_code=result.isced_code` → ยังไม่ผ่าน → `raise ValueError`
- ทับ `field_name_en`/`field_name_th` ในผลลัพธ์ด้วยค่าจริงจาก taxonomy เสมอ (กัน LLM สะกดชื่อหมวดเพี้ยน — code คือ source of truth)

### 6. Route — `api/routes/programs.py`

```python
class SuggestIscedRequest(BaseModel):
    name_th: str = Field(min_length=1)
    name_en: str = Field(min_length=1)
    field: str = Field(min_length=1)
```

(วางใน `programs.py` — request model เฉพาะ route นี้)

- `POST /suggest-isced`, `response_model=IscedSuggestion`, `dependencies=[Depends(require_api_key)]`
- body ว่าง/field ขาด → 422 (FastAPI อัตโนมัติ)
- `suggest_isced` โยน exception ใด ๆ → 502 `"จำแนก ISCED ไม่สำเร็จ กรุณาลองใหม่"` (log ตัวจริง)
- payload `POST /programs/` รับ `isced_code` ผ่าน `ProgramCreateRequest` ที่แก้แล้ว — route เดิมไม่ต้องแตะ

### 7. Frontend (`Intake.tsx`)

- ใต้แถวชื่อหลักสูตร (name_th/name_en): ปุ่ม "ตรวจสอบ ISCED / แนะนำชื่อ" — disabled ถ้า `name_th`/`name_en`/`field` ยังว่าง หรือกำลังโหลด
- state: `iscedResult: IscedSuggestion | null`, `iscedLoading`, `iscedError`, `iscedCode: string` (ค่าที่จะ submit)
- การ์ดผลลัพธ์ (เมื่อมี result):
  - หัว: `{isced_code} — {field_name_th} ({field_name_en})` + rationale
  - รายการชื่อแนะนำ: แต่ละชื่อ TH/EN + ปุ่ม "ใช้ชื่อนี้" → `setForm({...name_th, name_en})` (ทับค่าเดิม — ผู้ใช้กดเอง)
  - ปุ่มใช้ = ตั้ง `iscedCode = result.isced_code` ด้วย; แสดง badge "ISCED: {code}" เมื่อ set แล้ว + ปุ่มเล็กล้างค่า
- payload `handleSubmit` เพิ่ม `isced_code: iscedCode || null`
- error จาก endpoint → แสดงในการ์ด (detail จาก response)
- TS interface `IscedSuggestion`/`SuggestedName` mirror backend

### 8. Testing (TDD)

Unit:
- taxonomy: code unique ทุกระดับ, detailed ยาว 4 + prefix-3 อยู่ใน narrow, narrow prefix-2 อยู่ใน broad, `get_detailed_field` hit/miss
- validator: `isced_code=None` ผ่าน, code จริงผ่าน, code มั่ว → `ValidationError`
- prompt: system มี closed list (sample code เช่น "0613" ปรากฏ), กติกา "เท่านั้น" ปรากฏ, retry variant มี code เดิม
- `suggest_isced` (mock `complete_light`): ครั้งแรก valid → คืนผล + ชื่อหมวดถูกทับด้วยค่า taxonomy; ครั้งแรก invalid + retry valid → 2 calls; invalid ทั้งคู่ → `ValueError`
- route (mock `suggest_isced`): 200; body ขาด field → 422; helper โยน → 502; ไม่มี key เมื่อ config → 401

Frontend: `npm run build` + `npm run lint`

## ไฟล์ที่กระทบ

- `src/curriculum_agent/data/isced.py` — ใหม่ (taxonomy + helpers)
- `src/curriculum_agent/models.py` — `SuggestedName`, `IscedSuggestion`, `isced_code` + validator
- `src/curriculum_agent/prompts/suggest_isced.py` — ใหม่
- `src/curriculum_agent/stages/intake.py` — `suggest_isced`
- `src/curriculum_agent/api/routes/programs.py` — `SuggestIscedRequest` + route
- `src/curriculum_agent/data/orm.py` + `migrations/versions/*` — column `isced_code`
- `frontend/src/pages/Intake.tsx` — ปุ่ม + การ์ด + payload
- `tests/unit/test_isced.py` — ใหม่

## Open questions / ความเสี่ยง

- **ความถูกต้องของ taxonomy data** — สร้างจาก ISCED-F 2013 official structure ใน training data; integrity tests จับความสอดคล้องภายใน แต่การสะกด/แปลไทยต้องอาศัย review; ถ้าพบคลาดเคลื่อนแก้ที่ `isced.py` จุดเดียว
- Prompt แบก detailed list ~80 รายการ (~2k tokens) — light model รับได้ แต่ถ้า classify ไม่แม่นค่อยสลับ heavy ผ่านจุดเรียกเดียว
- ชื่อแนะนำอาจไม่ตรงแบบแผนชื่อปริญญาตามเกณฑ์ อว. 100% — เป็น suggestion ให้ผู้ใช้แก้ได้ ไม่ใช่ค่าบังคับ
