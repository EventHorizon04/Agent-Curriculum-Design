# F1 — Intake Schema + Form Refactor (มคอ.2)

**วันที่:** 2026-07-14
**Stage:** 0 (intake)
**Branch:** `feature/intake-mko2-f1`

## Overview

ปรับ stage 0 (intake) ให้เก็บข้อมูลหลักสูตรตามโครงสร้าง มคอ.2 ครบขึ้น และเลิกให้ผู้ใช้กรอกรหัสหลักสูตรเอง โดยระบบ generate เป็น slug ให้อัตโนมัติ

งานนี้เป็น sub-feature แรก (F1) ของการปรับ intake ทั้งชุด เป็น foundation ให้ F2 (upload เอกสาร → LLM สกัด) และ F3 (ISCED classification) ที่จะทำในรอบถัดไป — ทั้ง F2/F3 อยู่นอก scope ของ spec นี้

## Goals

- เพิ่ม field ตาม มคอ.2 หมวด 1: พันธกิจ, ปรัชญาหลักสูตร, เป้าหมายหลักสูตร, เอกลักษณ์สถาบัน
- `program_id` เปลี่ยนจาก user-input เป็น auto-generated slug — คงบทบาท internal identifier (PK/FK/thread_id/path) ไว้ครบ
- ฟอร์ม intake สะท้อน field ใหม่ และไม่มีช่อง "รหัสหลักสูตร" อีก

## Non-goals (นอก scope)

- Document upload + LLM extraction (→ F2)
- ISCED classification / name suggestion (→ F3)
- SMART R-alignment ที่ใช้ mission/philosophy ใน `plo_synthesis` (downstream — รอบหลัง)
- เปลี่ยนโครงสร้าง PK หรือ FK ของตารางใด ๆ

## Background (สภาพปัจจุบัน)

- `ProgramMetadata` (`models.py:77-92`) มี `program_id` เป็น required str ที่ user กรอก; มี `vision_th` (required), `student_identity_th` (optional), `program_objectives_th` (list, required) — **ไม่มี** mission / philosophy / เป้าหมาย / เอกลักษณ์สถาบัน
- `program_id` เป็น PK ของ table `programs` และ FK ในทุกตารางลูก (evidence, skills, clusters, plos, checkpoints, sessions) + ใช้เป็น LangGraph `thread_id` (`programs.py:19`) + path param ทุก sub-resource (`main.py:68-71`) + payload field บน qdrant point → **ตัดออกจากระบบไม่ได้ แต่ตัดออกจาก input ได้**
- `intake.py` ไม่ generate `program_id` — รับมาจาก metadata ที่ caller (`POST /programs/`) ส่งเข้า
- `Intake.tsx` มีช่อง "รหัสหลักสูตร *" กรอกมือ (required), placeholder `cs-2025`

## Design

### 1. Schema — `ProgramMetadata` (models.py)

เพิ่ม field ใหม่:

| field | type | required | ความหมาย |
|---|---|---|---|
| `mission_th` | `str` | required | พันธกิจ (คู่กับ `vision_th`) |
| `philosophy_th` | `str` | required | ปรัชญาหลักสูตร (มคอ.2 หมวด 1) |
| `program_goals_th` | `list[str]` | required | เป้าหมายหลักสูตร (อิงมาตรฐานสากลเชิงเนื้อหา) — เก็บแบบเดียวกับ `program_objectives_th` |
| `institutional_identity_th` | `str \| None = None` | optional | เอกลักษณ์/อัตลักษณ์สถาบัน (คู่กับ `student_identity_th`) |

`program_id` คงเป็น `str` required ใน model (internal invariant) แต่ **ไม่รับจาก frontend** — service layer เติมให้ก่อน validate (ดูข้อ 2)

Validator:
- `program_goals_th` ต้องไม่ว่าง (list ต้องมีอย่างน้อย 1 รายการ) — สอดคล้องกับ `program_objectives_th` ที่ required
- ไม่ต้องเพิ่ม validator พิเศษให้ `mission_th`/`philosophy_th` — Pydantic บังคับ non-empty str ผ่าน type; เพิ่ม `min_length=1` กันสตริงว่าง

### 2. Slug generation (`program_id`)

- อยู่ที่ **route `POST /programs/`** (service layer) — ทำ *ก่อน* `ProgramMetadata.model_validate`
- อัลกอริทึม: `slug = slugify(name_en)` → lowercase, แทน non-alphanumeric ด้วย `-`, ตัด `-` ซ้ำ/หัวท้าย
- **Collision check** ผ่าน `ProgramRepository`: ถ้ามี `program_id` นี้แล้ว ต่อ `-2`, `-3`, … จนกว่าจะ unique
- ถ้า `name_en` slug แล้วว่าง (เช่นเป็นอักขระที่ normalize ไม่ได้) → fallback เป็น `program` + suffix
- route return `program_id` ที่ generate กลับใน response ให้ frontend ใช้

**เหตุผลของตำแหน่ง:** collision check ต้อง query DB ซึ่งอยู่ที่ repository layer — model ไม่ควรแตะ DB, และ `default_factory` มองไม่เห็น `name_en` ตอน generate จึงไม่เลือก 2 ทางนั้น

### 3. Migration (Alembic)

เพิ่ม columns ใน table `programs`:
- `mission_th` — `TEXT NOT NULL`
- `philosophy_th` — `TEXT NOT NULL`
- `program_goals_th` — เก็บแบบเดียวกับ `program_objectives_th` ปัจจุบัน (ตรวจ ORM ว่าใช้ JSON array column ชนิดใด แล้วทำตาม) `NOT NULL`
- `institutional_identity_th` — `TEXT NULL`

**การจัดการข้อมูลเดิม:** ถ้าตารางมีแถวอยู่แล้ว column NOT NULL ใหม่ต้องมี `server_default` ชั่วคราว (เช่น `''` / `'[]'`) ระหว่าง add column แล้วค่อย drop default หลัง backfill — จัดการใน migration script เดียว ให้ upgrade รันบน DB ที่มีข้อมูลได้

### 4. Frontend (`Intake.tsx`)

- **ลบ** `program_id` ออกจาก `FormState`, `INITIAL`, `required[]`, payload
- **เพิ่ม** ช่องกรอก: พันธกิจ* (textarea), ปรัชญาหลักสูตร* (textarea), เป้าหมายหลักสูตร* (textarea แยกบรรทัด → `program_goals_th[]` เหมือน objectives), เอกลักษณ์สถาบัน (textarea, optional)
- success message + badge เปลี่ยนไปใช้ `name_th` และ `program_id` ที่อ่านจาก response ของ `POST /programs/` (ปัจจุบันไม่ได้อ่าน response id — ต้องแก้ให้อ่าน)

### 5. Testing (TDD — เขียน test ก่อน implementation)

Unit (`tests/unit/`):
- `mission_th` / `philosophy_th` ว่าง → `ValidationError`
- `program_goals_th` เป็น list ว่าง → `ValidationError`
- `institutional_identity_th` ไม่ใส่ → ผ่าน (None)
- slug: `name_en = "Computer Science"` → `computer-science`
- slug collision: มี `computer-science` แล้ว → `computer-science-2`
- slug edge: `name_en` ที่ normalize แล้วว่าง → fallback `program`

Integration (LLM mocked ตาม convention เดิม):
- `POST /programs/` โดยไม่ส่ง `program_id` → 200, response มี `program_id` ที่ generate, DB มีแถวด้วย field ใหม่ครบ

## ไฟล์ที่กระทบ

- `src/curriculum_agent/models.py` — เพิ่ม field + validator
- `src/curriculum_agent/api/routes/programs.py` — slug generation + collision + return id
- `src/curriculum_agent/data/repositories.py` — helper เช็ก `program_id` มีอยู่ไหม (สำหรับ collision)
- `src/curriculum_agent/data/orm.py` — เพิ่ม columns
- `migrations/versions/*` — migration ใหม่
- `frontend/src/pages/Intake.tsx` — form
- `tests/unit/*`, `tests/integration/*` — tests

## Open questions / ความเสี่ยง

- ORM เก็บ `program_objectives_th` ด้วย column type ใด (JSON / ARRAY) — ต้องยืนยันตอน implement เพื่อให้ `program_goals_th` ตรงกัน
- `slugify` — ใช้ helper เขียนเองด้วย regex (ไม่เพิ่ม dependency) หรือมี util อยู่แล้ว — ตรวจตอน implement
- ผลกระทบต่อ integration test เดิมที่อาจส่ง `program_id` เข้า `POST /programs/` — ต้องอัปเดตให้เลิกส่ง
