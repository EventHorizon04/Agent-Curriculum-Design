# Handoff: run comparison (validator switch + program copy) — frontend

สำหรับ session ที่ดูแล `frontend/` — งาน backend (task 1-4 ของ
`docs/superpowers/specs/2026-10-06-run-comparison-design.md`) commit แล้วที่
`e9a2626`, `10bd1f6`, `3f2acc5`, `38a37ca`. เอกสารนี้สรุปสัญญา API ที่เปลี่ยน/เพิ่ม
และสิ่งที่ UI ต้องทำ 4 จุด อ้างอิง field name จาก source จริง
(`src/curriculum_agent/models.py`, `src/curriculum_agent/api/routes/plos.py`,
`src/curriculum_agent/api/routes/programs.py`) ไม่ใช่สรุปจาก memory — เช็คโค้ดอีกทีถ้าไม่ชัวร์

## 1. `POST /programs/{program_id}/plos/run` — body เพิ่ม `run_validation`

`PLOSynthesisRunRequest` (ขยายจาก `DesignerNoteRequest`, อยู่ใน
`api/routes/plos.py`):

```ts
type PLOSynthesisRunRequest = {
  note_th?: string | null;   // เดิม — max 500 ตัวอักษร, whitespace-only = absent
  run_validation?: boolean;  // ใหม่ — default true
};
```

ส่ง `run_validation: false` = ข้าม SMART validation agent เฉพาะรอบนี้ (pure-code
gate ของ SMART ยังรันเหมือนเดิมเสมอ ไม่เกี่ยวกับ field นี้). Response ไม่เปลี่ยน —
ยังเป็น `PLO[]` เหมือนเดิม

## 2. `GET /programs/{program_id}/plos/validation` — endpoint ใหม่

เรียกตอนหน้า PLO synthesis โหลด เพื่อรู้ว่า validation agent เปิดอยู่ไหมในระบบ
(แยกจาก per-run switch ข้อ 1):

```ts
type ValidationStatusResponse = {
  enabled: boolean;
  model: string;   // "" เมื่อ enabled=false
};
```

- 404 ถ้า `program_id` ไม่มีอยู่จริง (`detail: "Program not found"`)
- `enabled=false` มาจาก `.env` (`VALIDATION_PROVIDER` ว่าง) — เป็นสวิตช์ระดับระบบ
  ที่ request เดี่ยวเปลี่ยนไม่ได้ (เปิดกลับไม่ได้ด้วย `run_validation: true`)

## 3. `POST /programs/{program_id}/copy` — endpoint ใหม่

ต้องส่ง header `X-API-Key` เหมือน create (`POST /programs/`) และ delete
(`DELETE /programs/{program_id}`) — ไม่มี body

Response: `ProgramMetadata` ของโปรแกรมใหม่ (`program_id` รูปแบบ
`{source}-run-{n}`, เลข `n` เริ่ม 1 และเลือกค่าน้อยที่สุดที่ยังว่าง)

Error cases:
- 404 ถ้า `program_id` ต้นทางไม่มีอยู่จริง (`detail: "ไม่พบหลักสูตรนี้"`)
- 409 ถ้าโปรแกรมต้นทางกำลังรัน PLO synthesis อยู่
  (`detail: "หลักสูตรนี้กำลังสังเคราะห์ PLO อยู่ — รอให้เสร็จก่อนจึงคัดลอก"`) —
  แสดง `detail` ตรงๆ ให้ผู้ใช้เห็น ไม่ต้องแปลเพิ่ม
- 409 อื่น (สร้าง id ชนกันซ้ำๆ จนหมดรอบ retry) — มี `detail` เป็นภาษาไทยเช่นกัน

การคัดลอกเอา evidence, skill, Need, PLO, PLO review ทั้งหมดไปด้วย (คนละ id ใหม่
ทุกแถว ยกเว้น `plo_id` ซึ่งคงเดิม) — ไม่เอา session/checkpoint ไปด้วย ดังนั้นสำเนาเริ่ม
checkpoint ใหม่สะอาด

## 4. `ProgramMetadata` / `ProgramSummary` — field ใหม่ `copied_from`

```ts
type ProgramMetadata = {
  program_id: string;
  name_th: string;
  name_en: string;
  field: string;
  isced_code: string | null;
  degree_level: "bachelor" | "master" | "doctoral";
  duration_years: number;
  faculty: string;
  university: string;
  scope_th: string;
  professional_council: string | null;
  accreditation_body: string | null;
  subject_benchmark_ref: string | null;
  program_objectives_th: string[];
  program_goals_th: string[];
  created_at: string;       // ISO datetime
  copied_from: string | null;  // ใหม่ — program_id ต้นทาง, ตั้งโดย POST .../copy เท่านั้น
};

type ProgramSummary = {
  program_id: string;
  name_th: string;
  name_en: string;
  field: string;
  faculty: string;
  degree_level: string;
  created_at: string;
  current_stage: string;
  session_status: string | null;
  copied_from: string | null;  // ใหม่
};
```

`copied_from` เป็น `null` สำหรับโปรแกรมที่ไม่ได้ถูกคัดลอกมา (รวมโปรแกรมเก่าทุกตัว) —
ไม่ใช่ foreign key ที่บังคับ ดังนั้นถ้าต้นทางถูกลบไปแล้ว ค่านี้ยังชี้ไปที่ id ที่ไม่มีอยู่จริงได้
(แสดงผลตรงๆ เป็น string พอ ไม่ต้อง join ไปหาโปรแกรมต้นทาง)

## 5. `PLO` — field ที่มีอยู่แล้วแต่ตอนนี้มีความหมายใหม่

```ts
smart_validated_by: "agent" | "code_only" | "stale" | "legacy";
smart_diagnosis_th: string | null;
```

เมื่อ `run_validation=false` ตอนรัน synthesis, PLO ทุกใบในรอบนั้นจะได้
`smart_validated_by = "code_only"` และ `smart_diagnosis_th` จะอธิบายว่า "ไม่ได้ตรวจ
(ปิดการตรวจในรอบนี้)" — ต่างจากกรณีระบบปิด validation agent เองทั้งระบบ
(`"ไม่ได้ตรวจ (ปิดการใช้ validation agent)"`) หรือกรณี endpoint ล่ม — ดังนั้น UI
ต้องอ่าน `smart_diagnosis_th` ไม่ใช่เดาจาก context เพราะ "ปิดเองรายรอบ" กับ
"ปิดทั้งระบบ" หน้าตา field เดียวกันหมด (`code_only`)

---

## UI ที่ต้องทำ (4 จุด)

1. **หน้า PLO synthesis** — checkbox "ตรวจด้วย validation agent" ข้างปุ่มรัน
   ค่าเริ่มต้นติ๊ก (on) ส่ง `run_validation` ใน body ของ
   `POST /programs/{id}/plos/run` คู่กับ `note_th`. ตอนโหลดหน้า เรียก
   `GET /programs/{id}/plos/validation` → `{enabled, model}`:
   - `enabled=false` → ปิด checkbox (ให้เป็น unchecked ด้วย) พร้อมข้อความ
     "ปิดไว้ในการตั้งค่าระบบ (VALIDATION_PROVIDER)"
   - `enabled=true` → แสดงชื่อ model ให้เห็น (เช่น ข้าง checkbox หรือ tooltip)

2. **การ์ด PLO** — badge "ไม่ได้ตรวจ" เมื่อ `smart_validated_by === "code_only"`
   tooltip ของ badge ใช้ `smart_diagnosis_th` ตรงๆ (ข้อความนี้บอกเองอยู่แล้วว่า
   ปิดเพราะรอบนี้หรือปิดทั้งระบบ)

3. **หน้า list/detail ของโปรแกรม** — ปุ่ม "คัดลอก" เรียก
   `POST /programs/{id}/copy` (ต้องแนบ header `X-API-Key` เหมือนปุ่ม
   สร้าง/ลบโปรแกรม) สำเร็จแล้ว navigate ไปหรือ highlight แถวของ
   `program_id` ใหม่ที่ได้กลับมา ถ้าได้ 409 ให้แสดง `detail` ที่ตอบกลับมาตรงๆ
   (เป็นภาษาไทยอยู่แล้ว)

4. **หน้า list ของโปรแกรม** — ถ้าแถวนั้นมี `copied_from` ไม่เป็น null ให้แสดง
   ข้อความรอง "สำเนาของ {copied_from}" ใต้แถว (`ProgramSummary.copied_from`)

ไม่ได้แตะ `frontend/**` ใดๆ ในงานนี้ — ทั้งหมดอยู่ฝั่ง backend/docs เท่านั้น
