# Implementation Spec — PLO Scope Guard

สถานะ: พร้อมลงมือ (ยกเว้นหัวข้อ 3.9 ที่รอ [ticket 06](issues/06-checkpoint-two-buckets.md))
ที่มา: [map.md](map.md) — ticket 01-13 ปิดแล้ว 12 ใบ (10 merged เข้า 04, 06 ยัง open)
ฐานโค้ด: `main @ a5823b9`

**เอกสารนี้รวบข้อตัดสินจาก ticket ทั้งหมด ไม่ได้ตัดสินอะไรใหม่** ทุกหัวข้อมีเหตุผลกำกับ
เพราะ guard ตัวนี้เต็มไปด้วยของที่ "ทำให้ง่ายขึ้น" ได้ในสายตาคนที่ไม่ได้อ่านผลการวัด
แล้วพังเงียบ ๆ — ดูหัวข้อ 4 ก่อนแก้อะไรที่ดูเกินจำเป็น

---

## 1. ปัญหาและขอบเขต

### 1.1 อาการ

`plo_synthesis` เรียง Need ด้วย `demand_score` แล้วหยิบ 10 ใบแรกเป็น PLO หลัก
Need ที่ **ไม่ควรเป็น PLO ของหลักสูตรนี้เลย** จึงขึ้นเป็น PLO ได้ ถ้าบังเอิญมีคะแนนสูง
โดยไม่มีอะไรในเส้นทางกันไว้:

- `ExtractedSkill.is_field_relevant` มีอยู่แล้ว (`models.py:244`) แต่ **ตายที่ `need_combination`** —
  clustering ไม่อ่านมันเลย และ `prompts/cluster_skills.py` สั่งชัดว่า off-field skill
  ยังต้องอยู่ในกลุ่มใดกลุ่มหนึ่ง
- `demand_score` = mandate + frequency ล้วน ไม่มีเทอมเรื่องขอบเขต (`stages/demand.py`)
- `Need.classification_coverage` ใช้แทนไม่ได้ เพราะกฎ **requirement wins**
  (`skill_extraction.py:215-225`) ทับ: ทักษะนอกขอบเขตที่สภาวิชาชีพหรือวิสัยทัศน์สถาบันพูดถึง
  ออกมาเป็น `requirement` เสมอ

### 1.2 สองแกน — ไม่ใช่แกนเดียว

แกนที่สองเพิ่มหลัง [ticket 02](issues/02-scope-statement-shape.md) เพราะหลักฐานจากหลักสูตรจริง
บอกว่าแกนแรกจับอาการที่ใหญ่ที่สุดไม่ได้:

| แกน | คำถาม | ตัวอย่างที่ควรถูกกัน |
|---|---|---|
| 1. อยู่ในสาขาไหม | Need ที่ตลาดต้องการจริง แต่นอกขอบเขตหลักสูตรนี้ | ทักษะพัฒนาซอฟต์แวร์ในหลักสูตรการแปล |
| 2. บัณฑิตทำได้ไหม | Need ที่เป็นกิจกรรมของสถาบัน/หลักสูตร/อาจารย์ | "บริหารทรัพยากรอย่างคุ้มค่า", "รับรองอัตราการได้งานทำ" |

**เชิงแนวคิดสองแกนไม่ทับกัน**: "การสร้างเครือข่ายความร่วมมือระดับสากล" อยู่ในสาขาของ
วิทยาลัยนานาชาติเต็ม ๆ แต่ไม่ใช่สิ่งที่บัณฑิตคนหนึ่งทำ

**เชิงข้อมูลบนชุดที่วัดแล้ว ทับกัน 100%** — [ticket 12](issues/12-axis-overlap.md) วัดว่า
ไม่มีทักษะตัวใดติดธงแกนเดียว (NOISE: OFF ทั้งคู่ 5, แกนเดียว 0+0, ไม่ติด 4).
แต่แกนที่สอง**มีมูลค่าแม้ตอบซ้ำ** เพราะการเพิ่มช่อง `is_graduate_capability` ทำให้ธงสาขา
ขยับจาก **3/9 เป็น 5/9 เอง ทั้งที่ไม่มี scope statement** — โมเดลเข้าใจคำถามเดิมคมขึ้น
แล้วตอบสองช่องด้วยคำตัดสินเดียว. **จึงเก็บสองธง ไม่ยุบ** ([ticket 11](issues/11-two-axis-selection.md))

### 1.3 เพดานที่รู้อยู่แล้ว (อย่าคาดหวังเกินนี้)

| สัญญาณ | recall บน NOISE | false positive บน CORE |
|---|---|---|
| control (ไม่มี scope, ไม่มีธงที่สอง) | 3/9 (33%) | 0/29 |
| scope statement แบบ C_narrow อย่างเดียว | 4/8 (50%) | 0/27 |
| ธง `is_graduate_capability` อย่างเดียว | 5/9 (56%) | 1/29 (3%) |

guard นี้จับได้ประมาณครึ่งเดียว — **ออกแบบมาให้เป็นตัวช่วย ไม่ใช่ด่านสมบูรณ์**
ทุกข้อตัดสินข้างล่างเลือกฝั่ง "ปล่อยผ่านแล้วให้คนเห็น" มากกว่า "ตัดแรง" ด้วยเหตุผลเดียวกันนี้

### 1.4 สิ่งที่ไม่ทำ (Out of scope จาก map)

| ไม่ทำ | เพราะ |
|---|---|
| ปุ่ม override ดึง Need นอกสาขากลับมาเป็น PLO | `POST /plos/from-needs` ไม่กรองโดยเจตนา — เป็นทาง override อยู่แล้ว (หัวข้อ 3.8) |
| อาการหลุด scope แบบอื่น (กว้างเกินหลักสูตร / ผิดระดับปริญญา / generic) | map นี้จับเฉพาะ "นอกสาขาเลย" ซึ่งเป็นอาการเดียวที่โค้ดมีสัญญาณค้างอยู่แล้ว |
| แก้ clustering prompt / summarize prompt | scope ไม่เข้า `build_program_context_th` — ทำแล้วล้าง clustering cache ทั้งหมด และส่งสัญญาณขัดกับ `cluster_skills.py` ที่สั่งให้ off-field skill เข้ากลุ่ม |
| เทอม field-relevance ใน `demand_score` | ปนสัญญาณ "ตลาดต้องการแค่ไหน" กับ "อยู่ในสาขาไหม" แล้วอ่านคะแนนไม่ออกทั้งคู่ |
| เกณฑ์ scope ใน SMART gate | ถึงจุดนั้นจ่ายค่า synthesis ไปแล้ว และ escalate PLO นอกสาขาให้คนซ่อม = ให้คนซ่อมของที่ไม่ควรเกิด |
| แก้ rule 6 (6-10 PLO) / กฎห้าม cluster ข้าม KSEC | เฉลยมนุษย์ TCISM มี 4 PLO และ theme ตัดข้าม KSEC — เป็นข้อขัดแย้งที่ **รายงานไว้** ต้องเป็น map ใหม่ ไม่ใช่ ticket ในนี้ |

---

## 2. สรุปการเปลี่ยนแปลง

| ไฟล์ | เปลี่ยนอะไร | หัวข้อ |
|---|---|---|
| `src/curriculum_agent/models.py` | `ProgramCreateRequest.scope_th`; `ExtractedSkill.is_graduate_capability`; `Need.in_field_skill_count` / `graduate_capability_skill_count` + `@property` สองตัว | 3.1, 3.4 |
| `migrations/versions/<new>.py` | `programs.scope_th`, `skills.is_graduate_capability`, `needs.*_count` — **migration เดียว** | 3.4 |
| `src/curriculum_agent/data/orm.py` | คอลัมน์ใหม่สามตารางให้ตรงกับ migration | 3.4 |
| `src/curriculum_agent/prompts/extract_skills.py` | parameter `scope_th`; กติกา `is_graduate_capability` (static); บรรทัด scope ใน **system prompt** แบบมีเงื่อนไข; บรรทัดสคีมาใหม่ | 3.2 |
| `src/curriculum_agent/stages/skill_extraction.py` | `_SkillItem.is_graduate_capability`; อ่าน `scope_th` จาก metadata; ต่อ scope เข้า **cache key** ไม่มีเงื่อนไข; เขียนธงลงแถว | 3.2, 3.3 |
| `src/curriculum_agent/stages/need_combination.py` | นับ counter สองตัวตอนสร้าง `_Group` (~`:202`) และส่งต่อลง `Need` (~`:300`) | 3.5 |
| `src/curriculum_agent/stages/need_grouping.py` | `is_in_scope(need) -> bool` ข้าง `MIN_NEEDS`/`MAX_CORE_PLOS` | 3.6 |
| `src/curriculum_agent/stages/plo_synthesis.py` | กรองด้วย `is_in_scope` **ก่อน** `synthesis_order` และก่อน `MAX_CORE_PLOS`; log สองบรรทัด | 3.7 |
| `src/curriculum_agent/api/routes/plos.py` | merge route: `logger.warning` เมื่อ Need ที่เลือกอยู่นอกขอบเขต — **ไม่กรอง ไม่ 422 ไม่แตะ floor check** | 3.8 |
| `frontend/src/pages/Intake.tsx` | ช่อง `scope_th` (optional) + helper text ที่เพาะรูป C_narrow | 3.1 |
| `scripts/eval_scope_guard.py` (ใหม่) | eval manual สองเคส สอง baseline | 3.10 |
| **checkpoint / `plo_report` / exporter** | **ยังไม่ตัดสิน — รอ ticket 06** | 3.9 |

---

## 3. รายละเอียดรายส่วน (เรียงตามลำดับที่ควรลงมือ)

### 3.1 scope statement — เก็บที่ไหน และฟอร์มที่ intake

อ้างอิง: [ticket 02](issues/02-scope-statement-shape.md), [ticket 01](issues/01-scope-boundary-standards.md),
[ticket 08](issues/08-fetch-post-2565-standards.md)

#### รูปที่เก็บ

field ใหม่บน `ProgramCreateRequest` (สืบทอดไปถึง `ProgramMetadata`):

```python
# models.py — ProgramCreateRequest
# ขอบเขตของหลักสูตรตามที่ผู้ออกแบบเขียนเอง ฝั่งบวกล้วน แจกแจงเป็นรายการ
# ("หลักสูตรนี้ครอบคลุม A, B, C และ D"). ไปถึง extraction model ที่ system prompt
# เป็นเกณฑ์ตัดสิน is_field_relevant เท่านั้น — ดู prompts/extract_skills.py
# ว่างได้: โปรแกรมที่ไม่เขียนจะได้ prompt เดิมทุกไบต์ และ guard กลายเป็น no-op เอง
scope_th: str = ""
```

**free text ช่องเดียว ฝั่งบวกล้วน** — ยืนตามมติเดิมของ map และ **กลับข้อเสนอของ ticket 01**
ที่ว่าควรมีช่อง "ไม่รวมถึง" แยก เพราะหลักฐานบอกตรงข้าม:

| variant | true positive (NOISE) | false positive (CORE) |
|---|---|---|
| A_none (control) | 3/9 (33%) | 0/29 |
| B_broad | 2/8 (25%) | 0/29 |
| **C_narrow** | **4/8 (50%)** | 0/27 |
| D_with_exclusions | **0/8 (0%)** | **1**/27 |
| E_vague | 2/8 (25%) | 0/27 |

- รายการ "ไม่รวมถึง" (D) ได้ **ศูนย์** แย่กว่าไม่ใส่อะไรเลย และเป็น variant เดียวที่ทำ
  false positive — มันจับเฉพาะของที่อยู่ในรายการเป๊ะ ๆ แล้วปิดวิจารณญาณกับอย่างอื่น
- เขียนกว้าง (B) หรือลอย ๆ (E) ได้ 25% **แย่กว่า control** — scope ที่ไม่คมไม่ใช่แค่ไม่ช่วย
  แต่ทำให้โมเดลมั่นใจผิด
- ฝั่งลบไม่มีมาตรฐานไทยฉบับไหนเพาะให้ได้เลย (มคอ.1 grep `ไม่รวมถึง`/`มิได้ครอบคลุม`/`ไม่ครอบคลุม`
  ทั้ง 9 ฉบับ = 0 ครั้ง; ประกาศ กมอ. หลัง 2565 สองฉบับ = 0; AUN-QA ไม่มีข้อความเรื่องขอบเขตเลย)
  → **การที่ฝั่งลบหาไม่ได้กลายเป็นเรื่องดี ไม่ใช่ช่องว่าง**

#### ฟอร์มที่ intake

`frontend/src/pages/Intake.tsx` — เพิ่ม `<textarea>` ต่อจากช่อง "สาขาวิชา / ภาควิชา"
ก่อนระดับปริญญา, **ไม่บังคับกรอก** (ไม่เข้า `required` array ที่ `:45`)

copy ที่ต้องเพาะรูปของ C_narrow:

- label: `ขอบเขตของหลักสูตร (ไม่บังคับ)`
- placeholder: `หลักสูตรนี้ครอบคลุม… (แจกแจง 3-4 รายการ)`
- helper text ต้องมีสามข้อความนี้ เพราะแต่ละข้อมาจากตัวเลขในตารางข้างบน:
  1. `เขียนเฉพาะสิ่งที่หลักสูตรครอบคลุม แจกแจงเป็นรายการ 3-4 อย่าง`
  2. `อย่าเขียนรายการ "ไม่รวมถึง" — จากการทดสอบ รายการกันออกทำให้ระบบตัดสินแย่ลงกว่าไม่เขียนอะไรเลย`
  3. `เขียนกว้าง ๆ หรือลอย ๆ แย่กว่าไม่เขียน — ถ้ายังแจกแจงไม่ได้ ให้เว้นว่างไว้ก่อน`

ตัวอย่างที่ผ่านการวัดแล้ว (C_narrow, ~150 ตัวอักษร) ใช้เป็นตัวอย่างในฟอร์มได้:

```
หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจและกฎหมายจีน-ไทย การล่ามการเจรจาธุรกิจ
การตรวจแก้งานแปลที่ได้จากเครื่อง (post-editing) และความรู้ด้านวัฒนธรรมและมารยาท
ทางธุรกิจจีนที่จำเป็นต่องานแปลและล่าม
```

**floor คือ "แจกแจงได้อย่างน้อย 3-4 รายการ" ไม่ใช่จำนวนตัวอักษร** — B_broad ยาว ~90 ตัวอักษร
แบบบรรยายรวม ๆ ไม่พอ ส่วน C_narrow ~150 ตัวอักษรแจกแจง 4 รายการพอ. ความยาวเป็นผลพลอยได้
ของการแจกแจง ไม่ใช่ตัวชี้วัด

> **ยังไม่ตัดสิน (1) — ของตั้งต้นในฟอร์มเป็นแบบไหน**
> [ticket 02](issues/02-scope-statement-shape.md) ตอบว่า "มีของตั้งต้น และรูปที่ต้องเพาะคือรูปของ C_narrow"
> แต่ไม่ได้ตัดสินว่าเป็น **static placeholder/ตัวอย่างในฟอร์ม** (ราคา = 0) หรือ
> **auto-seed จาก ISCED-F / ประกาศ กมอ.** ซึ่ง ticket 01 ตีราคาไว้สามชั้น
> (intake ต้องถาม `isced_code` 4 หลัก + `data/isced.py` ต้อง import description + ต้องแปลไทย)
> และ ticket 08 บอกว่าประกาศ กมอ. ครอบเฉพาะสาขาที่มีสภาวิชาชีพ = ว่างสำหรับหลักสูตรส่วนใหญ่.
> **spec นี้สั่งเฉพาะ static placeholder + helper text** ซึ่งเป็นส่วนที่ทั้งสองทางต้องมีเหมือนกัน
> auto-seed เป็นงานแยกที่ ticket 02 (หรือใบใหม่) ต้องปิดก่อนลงมือ

> **ยังไม่ตัดสิน (2) — เพดานความยาวของ `scope_th`**
> [ticket 13](issues/13-scope-position.md) ระบุข้อจำกัดไว้ว่าทดสอบเฉพาะ ~150 ตัวอักษร
> ยังไม่รู้ว่า scope ที่ยาวกว่านี้มากใน system prompt จะเริ่มปนเป็นหลักฐานไหม
> **spec นี้ไม่ใส่ validator ความยาว** (ไม่มี ticket ไหนสั่ง และการเดาเลขมั่ว ๆ
> จะกลายเป็นกฎที่ไม่มีใครอธิบายได้) — แต่ metric `contamination` ในหัวข้อ 3.10
> เป็นตัวถาวรที่จะจับอาการนี้ถ้ามันเกิด ใบที่ควรตอบคือ ticket 07 รอบแรกที่รันจริง

---

### 3.2 prompt — ถ้อยคำที่ทดสอบแล้ว และธง `is_graduate_capability`

อ้างอิง: [ticket 09](issues/09-graduate-capability-prompt.md), [ticket 13](issues/13-scope-position.md),
[ticket 03](issues/03-extraction-prompt-and-cache.md)

#### 3.2.1 ธงใหม่ในสคีมา ไม่ใช่กติกาที่ตัดทิ้ง

[ticket 09](issues/09-graduate-capability-prompt.md) ทดสอบสามทางบนชุดเดียวกัน 56/56 call:

| treatment | CORE_n | FP | NOISE_n | **TP** | INST_n | rewrites |
|---|---|---|---|---|---|---|
| A_none (control) | 29 | 0 | 9 | 0 | 20 | 0 |
| T1_rule (กติกาตัดทิ้ง) | **26** | 0 | **5** | ไม่มีธง | **14** | 0 |
| **T2_field (ธงในสคีมา)** | 29 | 1 (3%) | 9 | **5/9 (56%)** | 20 | 0 |
| T3_rewrite (เขียนใหม่) | 26 | 0 | 9 | 4/9 (44%) | 21 | **45** |
| T4_combo | 25 | 1 (4%) | 12 | 5/12 (42%) | 24 | 0 |

- **T1 ตก** — ลด NOISE 9→5 จริง แต่ลด CORE 29→26 และ institutional 20→14 ด้วย
  **โดยไม่มีร่องรอย** ปัญหาไม่ใช่ตัวเลขแต่คือตรวจสอบไม่ได้
- **T3 ตก** — เขียนใหม่ 45 ครั้ง และแต่งเติมความเฉพาะที่หลักฐานไม่ได้พูด
  ("การนำ AI มาปฏิรูปการศึกษา" → "การใช้ปัญญาประดิษฐ์ในงานแปลและล่าม") ชื่อทักษะไม่ตรงกับ
  `evidence_span_th` ที่ต้องคัดลอกตรงตัว = **ชน immutable rule 2**
- **T2 ผ่าน** — recall สูงสุด FP เดียว ของทุกอย่างยังมองเห็นได้ ตรงกับนโยบายที่ prompt เดิม
  เขียนไว้แล้วสำหรับ `is_field_relevant` ("ห้ามตัดทิ้งเอง ผู้ออกแบบหลักสูตรจะเป็นผู้ตัดสิน")

#### 3.2.2 signature ใหม่

```python
def build_extract_skills_prompt(
    evidence_text: str,
    classification: str,
    field_th: str = "",
    program_name_th: str = "",
    scope_th: str = "",          # ใหม่ — default "" ทำให้ fingerprint ไม่ขยับตาม scope
) -> list[dict[str, str]]:
```

#### 3.2.3 ถ้อยคำ — คัดลอกตามนี้ ไม่ต้องขัดเกลา

ทั้งสามบล็อกคือถ้อยคำที่ prototype 09/13 รันแล้วได้ตัวเลขในตารางข้างบน
**การเรียบเรียงใหม่ทำให้ตัวเลขทั้งหมดใน spec นี้ใช้อ้างไม่ได้**

**(ก) กติกาแกนบัณฑิต — static ต่อท้ายบล็อกกติกาเดิม (`extract_skills.py:29` หลังบรรทัด `is_field_relevant`)**

```
- is_graduate_capability = true เมื่อทักษะนั้นเป็นสิ่งที่บัณฑิตคนหนึ่งทำได้เมื่อสำเร็จการศึกษา;
  false เมื่อเป็นกิจกรรมหรือภารกิจของสถาบัน/หลักสูตร (เช่น การบริหารหลักสูตร การจัดหางบประมาณ
  การสร้างความร่วมมือระดับองค์กร) ให้คงไว้แต่ตั้งเป็น false ห้ามตัดทิ้งเอง
```

**(ข) บรรทัด scope — มีเงื่อนไข (`if scope_th:`) ต่อจาก (ก) ก่อนบรรทัด `"ตอบเป็น JSON object:"`**

```
- ขอบเขตของหลักสูตรนี้: {scope_th}
  ใช้บรรทัดนี้เป็นเกณฑ์ตัดสิน is_field_relevant เท่านั้น ห้ามสกัดทักษะจากบรรทัดนี้
  ทักษะทุกรายการต้องมาจากข้อความ evidence เท่านั้น
```

**ต้องมีทั้งสองประโยค บรรทัดที่สองไม่ใช่ส่วนเกิน** — มันคือสิ่งที่กันไม่ให้โมเดลอ่าน scope
เป็นหลักฐาน

**(ค) บรรทัดสคีมา — static แทรกก่อน `confidence: 0.0-1.0`**

```
  is_graduate_capability: true|false — เป็นสมรรถนะของบัณฑิตหรือไม่,
```

#### 3.2.4 scope อยู่ใน **system prompt** ไม่ใช่ user header

[ticket 13](issues/13-scope-position.md) วัดตำแหน่งล้วน ๆ 28/28 call:

| | `U_user` (user header) | `S_system` (system prompt) |
|---|---|---|
| **ชื่อทักษะลอกวลีจาก scope** | **8** | **0** |
| `evidence_span_th` หาไม่พบในหลักฐาน | **9** | **3** |
| NOISE ติดธง (recall) | 4/8 | 4/8 |
| CORE ติดธง (FP) | 1/27 | 1/26 |

**ย้ายแล้วหายสนิท ไม่แลกอะไร** — recall และ FP เท่ากันทั้งสองตำแหน่ง

รูปของบั๊กอันตรายกว่าที่เห็นในตัวเลข: บน `ev04`/`ev05` (สอง evidence ที่สั้นที่สุด, 148 และ
348 ตัวอักษร) `U_user` ผลิตทักษะที่ **span คัดลอกตรงตัวจริง แต่คัดจาก scope ไม่ใช่จากหลักฐาน**
— วันที่ scope บังเอิญมีวลีตรงกับหลักฐาน `is_grounded()` จะปล่อยผ่าน โดยที่ `evidence_span_th`
ไม่ได้ชี้ไปที่หลักฐานจริง = ชน immutable rule 2 แบบที่ตรวจไม่เจอ

span ที่หาไม่พบ 3 รายการที่เหลือของ `S_system` ไม่มีตัวไหนมาจาก scope — เป็น span ที่โมเดล
ตัดกลางประโยคหรือเรียบเรียงใหม่ ซึ่งเกิดในทุก variant มาตั้งแต่ต้นและ `is_grounded()` จับได้อยู่แล้ว

#### 3.2.5 ฝั่ง `skill_extraction.py`

- `_SkillItem` (`:140-147`) เพิ่ม `is_graduate_capability: bool = True`
- `run()` (`~:500`) อ่าน `scope_th = str(metadata.get("scope_th", ""))` ข้าง `field_th`/`program_name_th`
- `_extract_chunk` ส่ง `scope_th=scope_th` เข้า `build_extract_skills_prompt`
- ตอนสร้าง `ExtractedSkill` (`~:541`) เพิ่ม
  `is_graduate_capability=bool(s.get("is_graduate_capability", True))`
  **เขียนธงดิบรายแถวเหมือน `is_field_relevant`** ไม่ผ่าน `class_by_norm` — ดูเหตุผลที่ 3.5
- `classify_skills` **ไม่แตะ** — ดูข้อห้าม 4.4

---

### 3.3 cache & contract

อ้างอิง: [ticket 03](issues/03-extraction-prompt-and-cache.md)

#### 3.3.1 cache key — ต่อ scope แบบ**ไม่มีเงื่อนไข**

```python
cache_key = hashlib.sha256(
    f"{chunk}\x00{evidence.classification}\x00{settings.extraction_model}"
    f"\x00{_EXTRACTION_CONTRACT}\x00{field_th}\x00{program_name_th}"
    f"\x00{scope_th}".encode()          # ใหม่ — ต่อเสมอ แม้ scope ว่าง
).hexdigest()
```

**กลับด้านจากที่ ticket 03 ตั้งไว้ตอนแรก** — เหตุผลที่เคยทำให้ conditional จำเป็นคือ
"รักษาแถวเก่าให้ยังหยิบได้" ซึ่งหายไปแล้ว: ธงใหม่ในสคีมาทำให้ `_EXTRACTION_CONTRACT` ขยับ
ทุกแถวกลายเป็น miss อยู่ดี **ไม่มี key เดิมให้รักษา**. conditional จึงเหลือแต่ต้นทุน —
branch ที่ต้องมี test คุ้มตลอดไป แลกกับประโยชน์ครั้งเดียวที่ไม่ได้เกิด

เหตุผลที่ scope ต้องอยู่ใน key เลย: เหมือน `field_th`/`program_name_th` — สองโปรแกรมที่กิน
source text เดียวกัน (มาตรฐานสภาวิชาชีพฉบับเดียวกัน, job posting ที่ scrape มาชุดเดียวกัน)
ต้องไม่ใช้ entry ร่วมกัน เพราะ `is_field_relevant` ของอีกโปรแกรมตัดสินจาก scope คนละอัน

ผลพลอยได้ที่ต้องการ: **หลังรอบ re-extract ใหญ่แล้ว โปรแกรมที่แก้ scope ทีหลัง re-extract
เฉพาะตัวเอง** โปรแกรมอื่นไม่กระทบ

#### 3.3.2 `scope_th` ต้อง **ไม่** เข้า `_extraction_contract_fingerprint()`

`_extraction_contract_fingerprint()` (`skill_extraction.py:174-192`) เรียก
`build_extract_skills_prompt("", "")` ด้วย argument ว่าง — `scope_th: str = ""` แบบมีเงื่อนไข
ทำให้ **ไม่มีบรรทัด scope ใน system prompt ที่ถูก hash** ผลคือ fingerprint ขยับ**ครั้งเดียว**
จากสคีมาใหม่ + กติกาใหม่ แล้วนิ่ง ไม่แปรตามโปรแกรม

**นี่คือสิ่งที่ถูกต้อง ไม่ใช่ผลข้างเคียงที่ต้องแก้** — ต้องมีคอมเมนต์กำกับไว้ในโค้ด:

> fingerprint คือสัญญาเรื่อง**รูปร่าง**ของ payload ซึ่งไม่แปรตามโปรแกรม
> scope statement เป็น per-program **input** เหมือน `field_th`/`program_name_th` ที่อยู่ใน
> cache key แยก. ถ้าใครทำให้ scope เข้า fingerprint ทุกโปรแกรมจะมี contract คนละค่า แล้ว
> `prune_cache` จะรายงาน `stale-contract` **มั่วทั้งตาราง** — สัญญาณที่ทั้งเครื่องมือนั้น
> มีอยู่เพื่อบอกจะตายทันที

#### 3.3.3 re-extract ครั้งเดียวจบ

- **ธงใหม่ + scope + กติกาใหม่ ไป migration เดียวกัน** ไม่ทยอยแก้แล้วจ่ายสองรอบ
  (นี่คือเหตุผลที่หัวข้อ 3.4 บังคับให้ทุกคอลัมน์อยู่ใน revision เดียว)
- **ไม่สั่ง `prune_cache --delete` ก่อน deploy** — นั่นคือเอา irreversible action มาไว้ก่อนจุด
  ที่ยังถอยได้ ถ้าต้อง rollback แถวเก่ายังใช้ได้ถ้ายังไม่ลบ.
  `uv run python -m curriculum_agent.data.prune_cache` รายงาน `stale-contract` ได้เองอยู่แล้ว
  กวาดหลังจากมั่นใจแล้วถูกลำดับกว่า
- **ไม่เตือนใน UI** — ผู้ใช้จริงคนเดียวคือ designer ที่กดรันใหม่ในโปรแกรมตัวเอง เห็นเวลารอ
  เพิ่มครั้งเดียวแล้วจบ. คำเตือนใน UI ต้องรู้ว่า cache ของโปรแกรมนี้ stale = query `llm_cache`
  เทียบ contract ก่อนเรนเดอร์หน้า — โครงสร้างใหม่ทั้งชุดเพื่อข้อความที่แสดงครั้งเดียวใน
  ชีวิตของ deployment

---

### 3.4 models + migration

อ้างอิง: [ticket 04](issues/04-two-axis-flags-on-need.md) (รวม ticket 10)

#### 3.4.1 รูปที่ตกลง

| ชั้น | field | ชนิด |
|---|---|---|
| `ExtractedSkill` | `is_field_relevant` (มีอยู่แล้ว) | `bool = True` |
| `ExtractedSkill` | `is_graduate_capability` (**ใหม่**) | `bool = True` |
| `Need` | `in_field_skill_count` (**ใหม่**) | `int = 0`, store |
| `Need` | `graduate_capability_skill_count` (**ใหม่**) | `int = 0`, store |
| `Need` | `is_field_relevant` / `is_graduate_capability` | `@property` = `count > 0` |
| `ProgramCreateRequest` | `scope_th` (**ใหม่**) | `str = ""` |

```python
# models.py — ExtractedSkill
# ตั้งโดย extraction model: ทักษะนี้เป็นสิ่งที่บัณฑิตคนหนึ่งทำได้เมื่อสำเร็จการศึกษา
# หรือเป็นกิจกรรมของสถาบัน/หลักสูตร. แยก field กับ is_field_relevant โดยเจตนา —
# สองแกนไม่ทับกันเชิงแนวคิด และรูป bool แยกคือรูปเดียวที่ ticket 09 วัดได้ 56%
# ยุบทีหลังได้ แยกทีหลังไม่ได้
is_graduate_capability: bool = True
```

```python
# models.py — Need
# จำนวน "แถว" สมาชิกที่ธงเป็น true ไม่ใช่จำนวนชื่อทักษะที่ต่างกัน (ดู 3.5)
# ตัวหารคือ len(member_skill_ids) ซึ่งอยู่บน Need แล้ว จึงเก็บเป็น int ไม่ใช่ dict
in_field_skill_count: int = 0
graduate_capability_skill_count: int = 0

# แก้ระหว่าง implement — spec ฉบับแรกไม่ครอบข้อนี้:
# "ไม่มี key เลย" ต้องต่างจาก "ระบุ 0". อย่างหลังแปลว่า extractor ตัดสินว่าสมาชิก
# ทุกคนนอกขอบเขต และต้องถูกกรอง; อย่างแรกแปลว่าไม่มีใครเคยประเมิน และต้องรักษา
# พฤติกรรมเดิม = เท่ากับ len(member_skill_ids) เหมือนที่ migration backfill ทำ
# กับแถวเก่า. Need ไม่ได้มาจาก DB อย่างเดียว — มันมาเป็น dict ดิบจาก LangGraph
# checkpoint ที่ suspend ค้างข้าม deploy ด้วย ซึ่ง migration ไม่มีทางแตะ
# ถ้าไม่มี validator นี้ ทุก Need ในเธรดที่ค้างอยู่จะถูกกรองทิ้งทั้งหมดเงียบ ๆ
@model_validator(mode="before")
@classmethod
def _default_counts_to_all_members(cls, data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    members = data.get("member_skill_ids") or []
    for key in ("in_field_skill_count", "graduate_capability_skill_count"):
        if data.get(key) is None:
            data[key] = len(members)
    return data

@property
def is_field_relevant(self) -> bool:
    """กฎ any: สมาชิกในสาขาอย่างน้อยหนึ่งคนก็พอ"""
    return self.in_field_skill_count > 0

@property
def is_graduate_capability(self) -> bool:
    """กฎ any เหมือนกัน — ดู is_in_scope() ใน need_grouping.py"""
    return self.graduate_capability_skill_count > 0
```

#### 3.4.2 เหตุผลของแต่ละข้อ (อย่าลบ อ่านก่อนแก้)

1. **สองแกนแยกกันบน `ExtractedSkill` ไม่ยุบเป็น enum เดียว** — enum เดียวต้องมีค่า
   `both_off` และบังคับให้โมเดลเลือกค่าเดียวจากสี่ ซึ่ง**ไม่ใช่รูปที่ ticket 09 วัดได้ 56%**
   ที่วัดคือ bool แยกสองช่อง. **ยุบทีหลังได้ แยกทีหลังไม่ได้**
2. **บน `Need` เป็น counter ไม่ใช่ bool** — bool derive จาก counter ได้ ย้อนกลับไม่ได้ และ
   ticket 06 ต้องบอก designer ว่า "3 ใน 8" ไม่ใช่แค่ "อยู่". เลือก `int` ไม่ใช่ `dict`
   แบบ `classification_coverage` เพราะแกนมีสองค่าและตัวหารอยู่บน Need แล้ว —
   dict จะเก็บข้อมูลซ้ำ
3. **store ไม่ derive** — precedent ที่ใกล้ที่สุดคือ `classification_coverage` /
   `stakeholder_coverage` ซึ่ง store ทั้งคู่และคำนวณจาก members ชุดเดียวกันที่
   `need_combination.py:202`. `cited_need_ids` derive เพราะเป็นความสัมพันธ์ PLO→Need ที่
   เปลี่ยนทุกครั้งที่ลบ PLO — ธงสองแกนไม่เปลี่ยนหลัง group ถูกสร้าง (re-extract สร้าง Need
   ใหม่อยู่ดี). derive ยังบังคับให้ทุกหน้าจอที่โชว์ Need ต้อง join `skills` กลับ
4. **กฎ any อยู่บน model ที่เดียว** — `@property` = `count > 0` ไม่ใช่ปล่อยให้ selection กับ
   checkpoint เขียน `count > 0` คนละที่แล้ว drift
5. **ชื่อเดียวกับ `ExtractedSkill`** — precedent อยู่ในโมเดลเดียวกัน: `ksec_category` และ
   `bloom_level` อยู่ทั้งสองชั้น ชื่อเดียวกัน โดย Need เป็นค่าที่รวมขึ้นมา
   (`resolve_need_ksec`, `merge_bloom`). ชื่อแบบ `has_in_field_skill` ตั้งตาม*วิธีคำนวณ*
   ไม่ใช่ตาม*ความหมาย* — วันที่ ticket 07 สั่งเปลี่ยน threshold ชื่อจะโกหกทันที

#### 3.4.3 migration — หนึ่ง revision สามตาราง

`down_revision = 'f3a91c02b7de'` (head ปัจจุบัน: `f3a91c02b7de_llm_cache_kind_and_contract`)

```python
def upgrade() -> None:
    # programs — ว่างได้ตามธรรมชาติ ตาม precedent ของ isced_code (5ccd16b72130)
    op.add_column("programs", sa.Column("scope_th", sa.Text(), nullable=True))

    # skills — server_default true เหมือน is_field_relevant:
    # แถวเก่าต้องอ่านได้ว่า "เป็นสมรรถนะบัณฑิต" เพื่อรักษาพฤติกรรมเดิมเป๊ะ
    op.add_column(
        "skills",
        sa.Column("is_graduate_capability", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
    )

    # needs — เพิ่มแบบ nullable ก่อน แล้ว BACKFILL แล้วค่อยบังคับ non-null
    for col in ("in_field_skill_count", "graduate_capability_skill_count"):
        op.add_column("needs", sa.Column(col, sa.Integer(), nullable=True))
    op.execute(BACKFILL_NEED_COUNTS)
    for col in ("in_field_skill_count", "graduate_capability_skill_count"):
        op.alter_column("needs", col, nullable=False, server_default="0")
```

```python
# แยกเป็นค่าคงที่ระดับโมดูลเพื่อให้ test อ่านได้ — precedent: STAKEHOLDER_TYPE_BACKFILL
# ใน b7c4e1a9f052 ที่ tests/unit/test_migration_backfill.py import ผ่าน importlib
BACKFILL_NEED_COUNTS = """
UPDATE needs
   SET in_field_skill_count = jsonb_array_length(member_skill_ids),
       graduate_capability_skill_count = jsonb_array_length(member_skill_ids)
"""
```

**ทำไมต้อง backfill ไม่ใช่ `server_default 0`:**
`server_default 0` แปลว่า Need เก่าทุกแถวอ่านได้ว่า "ไม่มีสมาชิกไหนอยู่ในสาขา" = **ทุกโปรแกรม
ที่มีอยู่ถูกกรองหมดทันทีที่ deploy โดยไม่มีใครสั่ง**. `member_skill_ids` เป็น JSONB ตั้งแต่
`aa1e44fd1a46` จึงทำได้ใน `UPDATE` เดียว

**ทำไมไม่ `nullable` ถาวร ("ไม่เคยประเมิน"):** ซื่อสัตย์กว่าจริง แต่บังคับ tri-state ให้ทุก
ผู้บริโภคของ `Need` ตลอดไป และ `skills.is_field_relevant` ก็ default `True` ด้วยเหตุผลเดียวกัน
มาแล้ว

`orm.py` ต้องเพิ่มคอลัมน์ให้ตรงกันทั้งสามตาราง (`ProgramTable`, `SkillTable`, `NeedTable`)

> **หมายเหตุการ plumbing (ไม่ใช่ข้อตัดสินจาก ticket):** `programs.scope_th` เป็น
> `nullable=True` ตาม precedent `isced_code` ส่วนฝั่ง Pydantic เป็น `str = ""` ตาม precedent
> `name_th`/`name_en` — repository ต้องแปลง `None → ""` ตอนอ่าน ไม่ให้ `None` หลุดเข้า
> cache key (จะได้สตริง `"None"`)

---

### 3.5 `need_combination` — คำนวณ counter ตอนสร้าง group

อ้างอิง: [ticket 04](issues/04-two-axis-flags-on-need.md) ข้อ 3 และ 9

ที่ `need_combination.py:~202` ตรงที่ `_Group` ถูกสร้าง มี `members` อยู่ในมือแล้ว
(บรรทัดเดียวกับที่คำนวณ `cls_coverage` / `stk_coverage`):

```python
in_field = sum(1 for m in members if m.is_field_relevant)
grad_capable = sum(1 for m in members if m.is_graduate_capability)
```

เพิ่มสอง field ลง `_Group` แล้วส่งต่อลง `Need(...)` ที่ `~:300` ข้าง `classification_coverage`

#### counter นับ **ธงดิบรายแถว** ไม่ผ่าน or-by-name

โค้ดมีความไม่สม่ำเสมออยู่แล้ว: `classification` ผ่าน `class_by_norm` (or-by-name,
`skill_extraction.py:238`) แต่ `is_field_relevant` เขียนลงแถวแบบดิบ (`:541`) —
**ชื่อทักษะเดียวกันสองแถวมีธงต่างกันได้**

**ไม่แก้ความไม่สม่ำเสมอนี้** ด้วยเหตุผลสองข้อ:

1. property `count > 0` ให้ผลเท่ากันทั้งสองทาง — or-by-name คือ any ในกลุ่มย่อยอยู่แล้ว
2. or-by-name จะดัน counter เข้าใกล้ total เสมอเมื่อชื่อซ้ำเยอะ = **เศษส่วนที่ designer อ่าน
   จะจืดจนไร้ประโยชน์กับ ticket 06**

→ ต้องเขียนคอมเมนต์กำกับให้ชัดว่าตัวเลขนี้คือ **จำนวนแถว** ไม่ใช่จำนวนทักษะที่ต่างกัน
ไม่งั้นคนถัดไปจะ "แก้บั๊ก" ให้มันไปผ่าน `class_by_norm`

---

### 3.6 `is_in_scope()` — predicate เดียว เรียกที่เดียว

อ้างอิง: [ticket 05](issues/05-synthesis-selection-filter.md) ข้อ 2-3, [ticket 11](issues/11-two-axis-selection.md) ข้อ 1

วางที่ `need_grouping.py` **ข้าง `MIN_NEEDS` / `MAX_CORE_PLOS`**

```python
def is_in_scope(need: Need) -> bool:
    """Need ใบนี้มีสิทธิ์เป็น PLO ของหลักสูตรนี้ไหม — ผ่านต้องผ่านทั้งสองแกน

    สองแกนถูกตัดสินรายทักษะโดย extraction model แล้วรวมขึ้นเป็น counter บน Need
    ที่ need_combination (กฎ any: สมาชิกหนึ่งคนผ่านก็พอ ต่อแกน)

    คืน bool เท่านั้น — "ตกเพราะแกนไหน" อ่านได้จาก counter บน Need เองอยู่แล้ว
    ("0 ใน 8") ซึ่งละเอียดกว่า enum และไม่มีวันไม่ตรงกับ counter
    """
    return need.is_field_relevant and need.is_graduate_capability
```

**ทำไมอยู่ที่นี่**: โมดูลนี้มีเหตุผลกำกับอยู่แล้วว่าทำไม policy ถึงอยู่ตรงนี้ และ predicate นี้
คือ policy **ตัวที่สามที่ตัดสินว่า Need ไหนได้เป็น PLO** เหมือนกันเป๊ะกับสองค่าเดิม.
วางที่ `plo_synthesis` จะทำให้ policy กระจายสองที่โดยไม่มีเส้นแบ่งที่อธิบายได้;
โมดูล `scope_guard.py` แยกยังไม่คุ้มจนกว่า ticket 07 จะพาให้เกิด threshold หลายตัว

**ทำไม `and` ทั้งที่ ticket 12 บอกว่าแยกไม่ออกจากข้อมูล**: `and`/`or` ให้ตัวเลขเท่ากันเป๊ะ
บนชุดที่วัด (NOISE 5/9, CORE 1/29 ทั้งสี่กฎ) จึงเลือกจากข้อมูลไม่ได้ ต้องเลือกจากนโยบาย —
และนโยบายคือ "ตกแกนใดแกนหนึ่งก็ถูกกัน" เพราะ Need ที่ไม่ใช่สมรรถนะบัณฑิตเขียนเป็น PLO
ไม่ได้เลย ไม่ใช่แค่ผิดสาขา. ที่ระดับ skill กฎ any เป็นฝั่งปล่อยผ่านอยู่แล้ว การซ้อน `and`
ที่ระดับ Need จึงไม่ได้แปลว่ากรองแรง

**`is_in_scope` เป็นสวิตช์เดียวของ fallback ทั้งหมด** — ถ้า eval ไม่ผ่าน การถอยคือหยุดเรียก
predicate นี้ที่จุดเดียว แล้วเหลือธงไว้ให้ designer ดูที่ checkpoint (หัวข้อ 3.10)
นี่คือเหตุผลเพิ่มที่มันต้องเป็น predicate เดียว เรียกที่เดียว

---

### 3.7 `plo_synthesis` — ตำแหน่งกรอง และ warning

อ้างอิง: [ticket 05](issues/05-synthesis-selection-filter.md), [ticket 11](issues/11-two-axis-selection.md) ข้อ 4-5

#### ลำดับใหม่ใน `run()`

```
needs → [filter: is_in_scope] → แยก optional → synthesis_order → ceiling → loop
```

กรองที่ `plo_synthesis.py:~350` **ก่อน** `for is_optional in (False, True):` (`:356`)
เพื่อครอบทั้งสองซีรีส์ในที่เดียว

#### กรองก่อน `synthesis_order` และสำคัญกว่านั้นคือ **ก่อน `MAX_CORE_PLOS`**

กรองหลังเพดาน (`:358-368`) จะทำให้เพดานหยิบ 10 ใบแรกที่มีนอกขอบเขตปนอยู่ แล้วกรองทิ้ง
เหลือ 7 PLO **ทั้งที่ยังมี Need ในขอบเขตอีกหลายใบรออยู่ท้ายแถว** — เพดานต้องนับเฉพาะใบที่มีสิทธิ์

#### ครอบ optional ด้วย

**นอกสาขาก็คือนอกสาขา ไม่ว่าหลักหรือเสริม** — วาง predicate ก่อนลูปสองซีรีส์ครอบทั้งคู่
ยืนยันจากโค้ดแล้วว่า `synthesize_from_needs` มี caller สองที่เท่านั้น: `plo_synthesis.run()`
และ `api/routes/plos.py:291` (merge route — หัวข้อ 3.8) → **ไม่มีเส้นทางอื่นที่ Need
นอกขอบเขตเข้าเป็น PLO ได้**

#### ไม่เว้นเลข PLO

ช่องว่างของเลข PLO มีความหมายอยู่แล้วว่า "Need ใบนี้ร่างไม่สำเร็จ" (`plo_synthesis.py:380`)
ใส่ความหมายที่สองเข้าไปทำให้อ่านไม่ออกทั้งคู่. Need ที่ถูกกรองอยู่สถานะเดียวกับ Need ที่แพ้เพดาน
— **ไม่ถูกเลือก ไม่ใช่พัง** — และเพดานก็ไม่กินเลข

#### log สองบรรทัด

**(ก) บรรทัดตอนกรอง** — กี่ใบ ชื่ออะไร แยกตัวเลขสองแกน:

```python
if filtered:
    off_field = sum(1 for n in filtered if not n.is_field_relevant)
    off_grad = sum(1 for n in filtered if not n.is_graduate_capability)
    logger.warning(
        f"Stage 4: กรอง Need นอกขอบเขตออก {len(filtered)} ใบ "
        f"(นอกสาขา {off_field}, ไม่ใช่สมรรถนะบัณฑิต {off_grad}): "
        f"{', '.join(n.need_id for n in filtered)}"
    )
```

**แยกตัวเลขสองแกนในบรรทัดเดียว ไม่รวมเป็นตัวเดียว** — ticket 12 บอกว่าสองตัวจะเท่ากันเกือบเสมอ
ซึ่งฟังดูเหมือนเหตุผลให้ยุบ แต่กลับกัน: **ความเท่ากันนั้นคือข้อมูล** — วันที่สองตัวไม่เท่ากัน
คือวันที่สองแกนเริ่มแยกกันจริง และเห็นได้จากล็อกทันทีโดยไม่ต้องรัน eval.
ตัวเลขรวมตัวเดียวทำให้สัญญาณนั้นหายไปตลอดกาล

**(ข) เติมสาเหตุเข้าไปใน warning `MIN_NEEDS` เดิม** (`plo_synthesis.py:383-386`)
เมื่อการกรองเป็นเหตุ:

```
Stage 4 produced {core} core PLOs, below the {MIN_NEEDS} minimum policy —
กรอง Need นอกขอบเขตออก {len(filtered)} ใบก่อนร่าง (หลักฐานในขอบเขตไม่พอ); review at the checkpoint
```

designer ต้องแยก **"evidence ในสาขาไม่พอ"** ออกจาก **"Need น้อยแต่เดิม"**
(`need_combination.py:321-325`) ให้ได้ — สองอย่างนี้อ่านต่างกันได้ก็ต่อเมื่อบรรทัดที่บอกว่า
ต่ำกว่า 6 บอกสาเหตุมาในบรรทัดเดียวกัน ไม่ใช่ให้คนอ่านต่อเอาเองจากสองบรรทัดคนละที่ในล็อก

#### ยังกรองต่อแม้เหลือต่ำกว่า `MIN_NEEDS`

**ไม่เติม Need นอกขอบเขตให้ครบโควตา** — นั่นคือการผลิต PLO ที่รู้อยู่แล้วว่าผิดเพื่อให้ตัวเลขสวย
(เฉลยมนุษย์ของ TCISM มี 4 PLO ซึ่งต่ำกว่าพื้นอยู่แล้ว — เป็นข้อขัดแย้งกับ rule 6 ที่ map นี้
ไม่แตะ ไม่ใช่เหตุผลให้ผ่อนการกรอง)

> **หมายเหตุการ plumbing (ไม่ใช่ข้อตัดสินจาก ticket):** `known_need_ids` (`:352`)
> ยังเป็นเซตของ Need **ทั้งหมด** ไม่ใช่เฉพาะที่ผ่านการกรอง — มันเป็นด่านตรวจว่า id ที่ PLO
> อ้างมีอยู่จริง ไม่ใช่ด่านคัดเลือก และ merge route ก็ส่งชุดเต็มเข้าไปเหมือนกัน

---

### 3.8 merge route — ไม่กรอง log อย่างเดียว

อ้างอิง: [ticket 05](issues/05-synthesis-selection-filter.md) ข้อ 5, [ticket 11](issues/11-two-axis-selection.md) ข้อ 2

`POST /programs/{program_id}/plos/from-needs` (`api/routes/plos.py:205`)

#### ไม่กรอง — โดยเจตนา ไม่ใช่ช่องที่ลืมปิด

designer เลือก Need เองคือการตัดสินใจของคน ไม่ใช่ของ pipeline และนี่คือ **ทาง override
เพียงทางเดียว** จึงไม่ต้องมีปุ่ม override แยก (ตรงกับที่ map ระบุไว้ใน Out of scope)

#### ไม่กันแกน "ไม่ใช่สมรรถนะบัณฑิต" ด้วย — แม้ตกแกนนี้จะหนักกว่า

เรียงตามน้ำหนักของเหตุผล:

1. ticket 12 วัดว่าธง grad-OFF **ไม่เคยมาเดี่ยว (0 ตัวจาก 38)** ทุกตัวติดคู่กับธงสาขา →
   การกันแกนบัณฑิตคือการกันของชิ้นเดียวกับที่แกนสาขาปล่อยผ่านอยู่ = **นโยบายขัดกันเองบน
   request เดียว**
2. PLO ที่ผิดรูปมีด่านของมันอยู่แล้ว — SMART hard check กับ soft judge จับ "บริหารทรัพยากร"
   ที่เขียนเป็น PLO ได้ตรงกว่าธงที่ตัดสินตั้งแต่ชั้นสกัด
3. recall 56% แปลว่าอีก 44% ธงไม่ติดทั้งที่ควรติด — 422 บนสัญญาณครึ่งใบจะบล็อกงานที่ถูกต้อง
   ของ designer โดยไม่มีทางออก

#### สิ่งที่เพิ่ม: `logger.warning` อย่างเดียว

หลัง `selected = [by_id[nid] for nid in body.need_ids]` (`:233`) เพิ่มบล็อกทรงเดียวกับ
`released` (`:284-289`):

```python
out_of_scope = [n.need_id for n in selected if not is_in_scope(n)]
if out_of_scope:
    logger.warning(
        f"Merge ใช้ Need นอกขอบเขต {out_of_scope} — designer เลือกเอง "
        "(endpoint นี้ไม่กรองโดยเจตนา: เป็นทาง override ทางเดียว)"
    )
```

**ไม่ warn ใน response** — response ที่เตือนคือการทวงถามการตัดสินใจที่คนเพิ่งตัดไปแล้ว
แต่ต้องตามรอยได้ว่า PLO นอกขอบเขตข้อนี้มาจากไหน

#### floor check ไม่ต้องแก้

`projected_core < MIN_NEEDS and projected_core < current_core` (`:270`) กันเคสนี้ไว้แล้ว —
โปรแกรมที่การกรองทำให้เหลือ 4 PLO จะไม่ถูกปฏิเสธทุก merge ต่อจากนั้น เพราะเงื่อนไขที่สอง
บังคับว่า merge นี้ต้องเป็นตัวที่ทำให้ลดลง **เจตนาเดิมตรงกับที่ต้องการพอดี — อย่าไป "ปรับ"**

---

### 3.9 checkpoint / report — **placeholder รอ ticket 06**

**[ticket 06](issues/06-checkpoint-two-buckets.md) ยัง `Status: open`** — ห้ามเดาแทน

#### สิ่งที่ตกลงแล้วและใช้เป็นข้อจำกัดของงานนี้ได้

- ต้องแยกเป็น **สามก้อน** ไม่ใช่สอง: "แพ้ demand" / "นอกขอบเขต" / "ไม่ใช่สมรรถนะบัณฑิต"
  เพราะ designer ทำคนละอย่าง — แพ้ demand คือยอมรับได้; นอกขอบเขตคือต้องอ่านว่าโมเดล
  ตัดสินสาขาถูกไหม (ถ้าผิด = scope statement เขียนไม่ดี); ไม่ใช่สมรรถนะบัณฑิตคือตัดสินว่า
  ประโยคนั้นเขียนเป็น PLO ได้ไหมเลย
- ticket 11 ยืนยันแล้วว่า **สามก้อนอ่านไหว** และ **ไม่ต้องขอ field เพิ่ม** — ทั้ง bool
  (`@property`) และ counter สองตัวมีให้ใช้แล้วจากหัวข้อ 3.4
- ระบบ **เตือนอย่างเดียว ไม่ re-run ให้เอง** (จะชน immutable rule 7)
- `plo_report` วันนี้มี `needs_not_synthesized` (`plo_report.py:56`, `:73`) เป็นรายการเดียว
  รวมทุกสาเหตุอยู่แล้ว — จะต่อยอดหรือทำใหม่คือคำถามของ ticket 06

> **ยังไม่ตัดสิน (3) — แต่ละรายการในก้อน "นอกขอบเขต" แสดงอะไร**
> statement ของ Need, ชื่อ skill สมาชิก, สัดส่วน in-field, evidence span, demand_score
> ที่จะได้ถ้าไม่ถูกกัน — ticket 06 ต้อง prototype หน้าจอจริงก่อน

> **ยังไม่ตัดสิน (4) — ข้อความ "แก้ scope statement แล้วต้องรันอะไรใหม่บ้าง"**
> ต้องไม่กำกวมว่ารันแค่ skill extraction หรือรวม need combination ด้วย
> (ในเชิงกลไก: scope อยู่ใน extraction cache key → แก้ scope = re-extract ทั้งโปรแกรม
> → need_combination รันตามอยู่แล้วเพราะแชร์ checkpoint เดียวกัน — แต่ **ถ้อยคำ**
> ที่ designer อ่านยังไม่มีใครเขียน) ใบที่ควรตอบ: ticket 06

> **ยังไม่ตัดสิน (5) — อยู่ที่ checkpoint ของ plo_synthesis, `plo_report`, หรือทั้งสอง**
> ใบที่ควรตอบ: ticket 06

> **ยังไม่ตัดสิน (6) — `plo_report` / มคอ.2 exporter ต้องรายงาน Need ที่ถูกกันไหม และรายงานให้ใคร**
> (designer อ่านเอง vs อยู่ในเอกสารที่ส่ง MHESI) — map ระบุไว้ใน "Not yet specified"
> ว่าขึ้นกับรูปที่ ticket 06 ออกมา **ห้ามแตะ `exporters/` ในงานรอบนี้**

**งานรอบนี้ทำได้ถึงแค่นี้**: กรองจริง + log ครบ + counter อยู่บน `Need` พร้อมให้หน้าจอหยิบ
UI เป็นงานรอบถัดไปหลัง ticket 06 ปิด

---

### 3.10 eval protocol

อ้างอิง: [ticket 07](issues/07-eval-protocol.md)

#### ชุดข้อมูล — สองเคส

1. **TCISM ล้วน** — evidence 14 รายการจาก `Data/ความต้องการของผู้มีส่วนได้ส่วนเสีย การแป.docx`
   เฉลยจาก `Data/Needs_to_PLO_TCISM.xlsx` (13 Need → 4 theme → 4 PLO)
   วัดแกน **"ไม่ใช่สมรรถนะบัณฑิต"** เป็นหลัก
   - CORE (ติดธง = false positive): ev06-09, ev14
   - NOISE (ติดธง = true positive): ev10, ev11
2. **TCISM + evidence ยัด** — job posting สาขาอื่นไปเลย (วิศวะ/พยาบาล จาก
   `Data/linkedin_offers2026-04-30.csv`) วัดแกน **"นอกสาขา"** ซึ่ง TCISM ล้วนไม่มีเคส
   (evidence ของ TCISM ทุกชิ้นอยู่ในสาขา — มนุษย์เก็บ theme D ผู้ประกอบการไว้เป็น PLO4 ด้วยซ้ำ)

**เฉลยของเคสสังเคราะห์รู้แน่นอนโดยการก่อสร้าง** — ไม่ต้องมี rubric ให้คนละคนอ่านแล้วเถียงกัน
และไม่ต้องมี LLM judge ที่ถามคำถามเดียวกับที่ระบบเพิ่งตอบ (สองทางตันที่ ticket 07 ตั้งไว้แต่แรก)

**evidence ที่ยัดต้องยัดทั้ง `employer` และ `professional_council` รายงานแยกสองก้อน**

> **แก้หลังรัน eval จริง — spec ฉบับแรกเขียนข้อนี้ผิด**
>
> เดิมเขียนว่า *"requirement wins เป็นกฎที่ตั้งใจให้ guard กรองไม่ได้"* และให้รายงาน
> ว่า *"กรองไม่ได้ N ใบ เพราะเป็น requirement — ถูกต้องตามนโยบาย"* **ไม่จริงทั้งคู่**
>
> `requirement wins` ตัดสิน **`classification` เท่านั้น** (`classify_skills` กฎข้อ 1-2
> ทับกฎข้อ 3 ที่ว่า off-field → `unclassified`) ส่วน `is_in_scope()` อ่าน
> `Need.in_field_skill_count` / `graduate_capability_skill_count` ซึ่งนับจาก**ธงดิบ
> รายแถว** — `classification` ไม่เคยไปถึงมันเลย. ทักษะที่สภาวิชาชีพสั่งแล้วโมเดลตีว่า
> นอกสาขา **ถูกกรองเหมือนของอื่นทุกประการ**
>
> การรันจริงยืนยัน: 1-2 Need ต่อรอบถูกกรองทั้งที่มีสมาชิก `classification=requirement`

สิ่งที่ต้องรายงานจริงจึงกลับด้าน — ไม่ใช่ *"กรองไม่ได้เพราะเป็น requirement"* แต่เป็น
*"**กรองไป** N ใบ ทั้งที่มีสมาชิกเป็น requirement"* ซึ่งเป็น**สัญญาณเตือน ไม่ใช่การยืนยัน
ว่ากฎทำงานถูก**: มันคือสมรรถนะที่มีอำนาจตามกฎหมายสั่งไว้ แล้ว pipeline ตัดทิ้งตามคำ
ของโมเดลที่ recall แค่ครึ่งเดียว. เหตุผลที่ยังต้องยัด `professional_council` เข้าไป
จึงคือการ**วัดขนาดของช่องนี้** ไม่ใช่การทดสอบว่ากฎปกป้องมันจริง

> **ตัดสินแล้ว — `requirement` ไม่ได้รับการยกเว้น กรองตามปกติ**
>
> "requirement wins" ตัดสินว่าทักษะเป็น**ข้อกำหนด**หรือไม่ ซึ่งเป็นคนละคำถามกับว่า
> **สมรรถนะนั้นเป็นของหลักสูตรนี้หรือเปล่า** — สภาวิชาชีพสั่งสิ่งที่หลักสูตรนี้ไม่ใช่
> ที่ทางที่ถูกต้องจะสอนได้. การให้ `classification` ข้าม guard จะทำให้ธงนอกสาขา
> ไร้ผลกับทุกทักษะที่สภาวิชาชีพหรือวิสัยทัศน์สถาบันพูดถึง ซึ่งเป็นกลุ่มใหญ่ของคลัง
>
> สิ่งที่ทำแทน — สองอย่างนี้ทำให้ไม่ต้องยกเว้นในโค้ด: Need ที่ถูกกรองทั้งที่มีข้อกำหนด
> จากสภาวิชาชีพ **ติดป้ายที่หน้า report** ให้ designer เห็นก่อนอนุมัติ และ **merge route
> ไม่กัน** จึงหยิบกลับมาได้ถ้าตัดสินว่าโมเดลอ่านผิด
>
> **โค้ดไม่เปลี่ยน** — `is_in_scope()` ไม่เคยอ่าน `classification` อยู่แล้ว
> สิ่งที่เพิ่มคือคอมเมนต์ที่บอกว่าเป็นเจตนา ไม่ใช่ของที่ลืม

**ยังไม่ต้องมีหลักสูตรที่สาม** — สิ่งที่ทำให้เคสใช้ได้คือเฉลยของมนุษย์ ซึ่งขอจากมหาวิทยาลัย
ไม่ได้ตามใจ ผูก map ไว้กับงานที่เราสั่งไม่ได้คือการบล็อกตัวเอง

#### ระดับที่วัด

**ระดับ Need เป็นตัวตั้งเกณฑ์ ระดับ skill เป็น diagnostic**

กฎ any ทำให้ตัวเลข skill **หลอก**: Need ที่มีสมาชิก 8 ตัวถูกกรองก็ต่อเมื่อ **ทั้ง 8 ตัว**
ติดธง — recall 56% ที่ระดับ skill จึงกลายเป็นตัวเลขที่ต่ำกว่านั้นมากที่ระดับ Need
และนั่นคือตัวที่ตัดสินว่า PLO หลุดหรือไม่

**ไม่วัดที่ระดับ PLO** — ต้องจ่ายค่า synthesis ทุกรอบเพื่อวัดสิ่งที่ระดับ Need ตัดสินไปแล้ว
PLO ที่หลุดคือ PLO ที่ Need หลุดผ่านมา ไม่มีทางหลุดเพิ่มที่ชั้นนั้น

#### เกณฑ์ผ่าน — asymmetric

| | เกณฑ์ |
|---|---|
| **false positive ที่ระดับ Need** | **= 0 — hard gate** (Need ในสาขาต้องไม่ถูกกรองแม้ใบเดียว) |
| **recall ที่ระดับ Need** | **รายงานเทียบ baseline ไม่ใช่ gate** |

สองฝั่งไม่เท่ากันในผลที่ตามมา: Need ในสาขาที่ถูกกรองผิดคือ **PLO ที่หายไปจากหลักสูตร
โดยไม่มีใครรู้** ส่วน Need นอกสาขาที่หลุดเข้ามาคือของที่ designer เห็นที่ checkpoint แล้วลบได้
ในสามวินาที. เกณฑ์เดียวที่บีบทั้งสองฝั่งเข้าเลขเดียวคือการแลกของที่กู้คืนไม่ได้กับของที่กู้คืนได้

**ตัวเลข recall ตายตัวตั้งไม่ได้ตอนนี้** — ไม่มีใครวัด recall ที่ระดับ Need มาก่อน

#### baseline — สองตัว

| | คือ | ตอบคำถาม |
|---|---|---|
| `B0` | branch เดิม ก่อนธงใหม่ | — |
| `B1` | branch ใหม่ scope ว่าง | `B1 − B0` = **ช่องธงที่สองให้อะไร** |
| ผลจริง | branch ใหม่ + scope | `ผล − B1` = **scope statement ให้อะไร** |

**"ไม่มี scope = พฤติกรรมเดิมเป๊ะ" จริงเฉพาะที่ระดับ prompt bytes ไม่จริงที่ระดับผลลัพธ์** —
ticket 12 วัดว่าการเพิ่มช่อง `is_graduate_capability` ดันธงสาขาจาก 3/9 เป็น 5/9 ทั้งที่ไม่มี
scope เลย. `B1 − B0` คือตัวเลขที่ต้องดูวันที่ตัดสินใจว่าจะยุบเป็นแกนเดียวไหม

#### metric ที่รายงานทุกรอบ

1. recall / FP ที่ระดับ **Need** แยกสองแกน และรวม
2. recall / FP ที่ระดับ **skill** (diagnostic — อธิบายว่าทำไมตัวเลข Need ออกมาแบบนั้น)
3. **overlap ของสองแกน** (ตาราง 2×2 แบบ ticket 12) — ตัวที่ตัดสินว่าเก็บสองคอลัมน์ไว้ถาวรคุ้มไหม
4. **contamination** — ทักษะที่ชื่อหรือ span ลอกวลีจาก scope statement
   เป็น metric **ถาวร ไม่ใช่วัดครั้งเดียวแล้วเลิก** เพราะยังไม่รู้ว่า scope ที่ยาวกว่า
   ~150 ตัวอักษรจะเริ่มปนไหม (ดู "ยังไม่ตัดสิน (2)")
5. จำนวน Need ที่ **ถูกกรองทั้งที่มีสมาชิกเป็น `requirement`** — สัญญาณเตือนว่า
   สมรรถนะที่สภาวิชาชีพสั่งถูกตัดทิ้งตามคำโมเดล ไม่ใช่การยืนยันว่ากฎทำงานถูก
   (ดูกล่องแก้ไขในหัวข้อชุดข้อมูล และ "ยังไม่ตัดสิน (8)")

#### ผลกระทบของการยัด evidence ต่อ `demand_score`

`demand_score` = `0.30 × mandate + 0.70 × share of corpus` — ยัด evidence เข้าคลังแล้ว
ทุก Need เดิมได้คะแนนใหม่ **แต่ไม่กระทบ metric ของ guard เลย** เพราะการกรองอยู่**ก่อน**
`synthesis_order` (หัวข้อ 3.7) จึงอยู่ก่อนจุดที่ `demand_score` เข้ามาเกี่ยว

- เทียบข้ามเคสได้: recall / FP ที่ระดับ Need
- เทียบไม่ได้ และไม่ต้องเทียบ: "Need ไหนได้เป็น PLO"

**ไม่ตรึง corpus size ด้วยการเอา evidence ของ TCISM ออก** — นั่นคือเปลี่ยนโจทย์เพื่อให้เลขสวย

#### ถ้าไม่ผ่าน — fallback ที่ประกาศไว้ล่วงหน้า

**ปิดสวิตช์กรอง เหลือแต่ติดธงให้ designer ดูที่ checkpoint** — ticket 06 สร้างหน้าที่แสดง
Need ที่ถูกกันอยู่แล้ว การถอยจึงเป็นการปิดการกรองอัตโนมัติ ไม่ใช่เขียนอะไรใหม่
เป็น degradation ที่ถูกที่สุดที่ map นี้จะมีได้

(การปรับถ้อยคำ prompt แล้ววัดใหม่ทำได้ระหว่างทางอยู่แล้ว ไม่ต้องประกาศเป็น fallback;
ส่วน "หาสัญญาณอื่นแทนธงจากโมเดล" เป็นงานวิจัยเปิดที่ไม่ควรผูกกับเงื่อนไข "ถ้า eval ไม่ผ่าน")

#### รันเมื่อไหร่

**manual — สคริปต์ใน `scripts/` รันเมื่อแตะ prompt, เปลี่ยน model, หรือย้าย slot**

**ไม่ใช่ CI**: เรียก LLM จริง 28-70 call ต่อรอบ จะจ่ายทุกครั้งที่มีคนแก้ typo และผลไม่
deterministic พอจะเป็น gate สีแดง/เขียว. **eval เป็นเครื่องมือตัดสินใจของคน ไม่ใช่ด่านอัตโนมัติ**
ผลเก็บเป็นไฟล์ที่ commit ไว้ เทียบข้ามรอบได้

สิ่งที่อยู่ใน CI คือ unit test ของ `is_in_scope()` และ cache key ซึ่ง deterministic ล้วน (หัวข้อ 5)

**หมายเหตุสภาพแวดล้อมจาก prototype**: ทุกตัวเลขใน spec นี้มาจาก `gemma4:31b-cloud`
ผ่าน ollama cloud. OpenRouter หมดเครดิตตอนทำ prototype (402 `in_flight_budget_exhausted`)
และ llama-3.3-70b เขียนไทยเพี้ยน (อักษรซีริลลิกปนในชื่อทักษะ) — **การเทียบข้ามโมเดล
ไม่มีความหมาย** ถ้ารัน eval บนโมเดลอื่น ต้องรัน baseline ใหม่ทั้งชุด

---

## 4. สิ่งที่ต้องไม่ทำ

ทุกข้อในนี้ "ดูสมเหตุสมผล" สำหรับคนที่ไม่ได้อ่านผลการวัด — นั่นคือเหตุผลที่มันอยู่ในรายการนี้

### 4.1 ห้ามเพิ่ม branch "โปรแกรมนี้มี scope statement ไหม"

โปรแกรมที่ไม่มี scope statement มีธงเป็น `True` ทุกแถวจาก default (หัวข้อ 3.4)
→ counter = total → predicate ผ่านหมด → **`is_in_scope` กลายเป็น no-op เอง**
branch นั้นเป็นโค้ดที่ไม่มีวันเปลี่ยนพฤติกรรมอะไร แต่ต้องมี test คุ้มตลอดไป
([ticket 05](issues/05-synthesis-selection-filter.md))

### 4.2 ห้ามให้ `scope_th` เข้า `_extraction_contract_fingerprint()`

ถ้าเข้า ทุกโปรแกรมจะมี contract คนละค่า แล้ว `prune_cache` จะรายงาน `stale-contract`
**มั่วทั้งตาราง** — เครื่องมือที่มีอยู่เพื่อบอกว่าแถวไหนตายจะเลิกบอกอะไรได้เลย
fingerprint = สัญญาเรื่อง**รูปร่าง**; scope = per-program **input** (หัวข้อ 3.3.2,
[ticket 03](issues/03-extraction-prompt-and-cache.md))

### 4.3 ห้ามยุบสองแกนเป็นธงเดียว / enum เดียว

- enum เดียวไม่ใช่รูปที่วัดได้ 56% — ที่วัดคือ bool แยกสองช่อง
- ช่องที่สอง**มีมูลค่าแม้ตอบซ้ำ**: มันดันธงสาขาจาก 3/9 เป็น 5/9 โดยไม่มี scope เลย
  ลบออกอาจเสีย recall กลับไปที่ control
- "ธงเดียวที่มีนิยามครอบทั้งสองเกณฑ์" อาจให้ 5/9 เท่าเดิมหรืออาจกลับไป 3/9 —
  **ไม่มีใครวัด ยุบตอนนี้คือเดา**
- ยุบทีหลังได้ แยกทีหลังไม่ได้

([ticket 04](issues/04-two-axis-flags-on-need.md) ข้อ 1, [ticket 11](issues/11-two-axis-selection.md) ข้อ 1)

**เงื่อนไขที่จะทำให้กลับมาพิจารณายุบได้**: ถ้า ticket 07 วัดบนชุดใหญ่แล้วยังทับกัน 100%
**และ**วัด "ธงเดียวนิยามรวม" เทียบด้วยแล้ว — ไม่ใช่ก่อนนั้น

### 4.4 ห้ามให้สองแกนไหลผ่าน `classification`

กฎแบบ `is_graduate_capability=False → unclassified` เป็น **dead rule บนตัวอย่างที่มันควรจับพอดี**:
"การบริหารจัดการและพัฒนาแหล่งรายได้" มาจากวิสัยทัศน์สถาบัน → evidence เป็น `requirement`
→ `classification` เป็น `requirement` เสมอ ต่อให้ธงบอกว่าไม่ใช่สมรรถนะบัณฑิต
(**requirement wins** ทับ ตรงจุดที่ต้องการกฎใหม่ที่สุด — เหมือนที่แกนสาขาเจอมาแล้ว)

→ selection ต้องอ่านธงตรง ๆ **precedence 5 ข้อใน `classify_skills` ไม่ขยับแม้แต่ข้อเดียว**
([ticket 04](issues/04-two-axis-flags-on-need.md) ข้อ 5)

### 4.5 ห้ามกรองที่ระดับ stakeholder

กฎแบบ "`administrator` กับ `program_committee` เป็น evidence ที่ไม่เข้าสู่ PLO" **เขียนง่ายกว่า
และผิดชัดเจน** — เฉลยมนุษย์เก็บ Need ของผู้บริหาร (9 → theme B+D), อ.ผู้รับผิดชอบ (10 → D),
อ.ผู้สอน (11 → A) ไว้ครบ **ตัดเฉพาะเนื้อหาบางส่วนในสิ่งที่เขาพูด ไม่ใช่ตัวเขา**
([ticket 04](issues/04-two-axis-flags-on-need.md) ข้อ 7)

### 4.6 ห้ามใช้ majority แทน any

prototype 09 วัด false positive 1/29 แต่ recall 56% → **ธงที่ติดมาเชื่อได้ แต่ที่ไม่ติดพลาด
ครึ่งหนึ่ง**. any คือฝั่งปล่อยผ่าน ตรงกับนโยบาย "ห้ามตัดทิ้งเอง";
majority บนสัญญาณที่ recall แค่ครึ่งคือ**การตัดของถูกทิ้ง**
([ticket 04](issues/04-two-axis-flags-on-need.md) ข้อ 4)

### 4.7 ห้ามให้ prompt ตัดทิ้งเงียบ (T1)

กติกาที่สั่งให้โมเดลไม่เสนอทักษะฝั่งสถาบันลด NOISE 9→5 ก็จริง แต่ลด CORE 29→26 และ
institutional 20→14 ด้วย **โดยไม่มีร่องรอย** — ปัญหาไม่ใช่ตัวเลขแต่คือตรวจสอบไม่ได้
([ticket 09](issues/09-graduate-capability-prompt.md))

### 4.8 ห้ามให้ extraction เขียนชื่อทักษะใหม่ (T3)

เขียนใหม่ 45 ครั้งและแต่งเติมความเฉพาะที่หลักฐานไม่ได้พูด → ชื่อทักษะไม่ตรงกับ
`evidence_span_th` ที่ต้องคัดลอกตรงตัว = **ชน immutable rule 2**

**มนุษย์เขียนใหม่จริง แต่ทำที่ระดับ Need** ตอนที่หลักฐานถูกเก็บครบแล้วและ span ยังชี้กลับได้
→ ที่ทางของการเขียนใหม่คือ `summarize_need` ไม่ใช่ `extract_skills`
([ticket 09](issues/09-graduate-capability-prompt.md))

> **ยังไม่ตัดสิน (7) — `summarize_need` ควรเห็นธงรายสมาชิกไหม**
> map ระบุไว้ใน "Not yet specified": `summarize_need` ทำงาน**ก่อน**ที่ธงจะรวมเป็น counter
> บน `Need` (เขียนประโยคจากชื่อทักษะตอนที่ยังเห็นสมาชิกรายตัว) — ยังไม่รู้ว่าควรเห็นธงไหม
> และถ้าเห็น ควรข้ามทักษะที่ติดธงหรือเขียนประโยคที่กันมันออกเอง
> **spec นี้ไม่แตะ `summarize_need`** ต้องเป็น ticket ใหม่

### 4.9 ห้ามวาง scope statement ใน user header

วางติดข้อความหลักฐาน = เชิญให้โมเดลอ่านมันเป็นหลักฐาน: 8 ทักษะชื่อลอกวลีจาก scope,
9 span หาไม่พบในหลักฐาน และรูปที่อันตรายที่สุดคือ **span คัดลอกตรงตัวจริงแต่คัดจาก scope**
— วันที่ scope บังเอิญมีวลีตรงกับหลักฐาน `is_grounded()` จะปล่อยผ่าน
([ticket 13](issues/13-scope-position.md))

### 4.10 ห้ามเพิ่มรายการ "ไม่รวมถึง" เข้า scope statement

0/8 แย่กว่าไม่ใส่อะไรเลย (control 3/9) และเป็น variant เดียวที่ทำ false positive —
รายการ exclusion ดึงความสนใจโมเดลไปอยู่กับรายการแล้วปิดวิจารณญาณกับอย่างอื่น
([ticket 02](issues/02-scope-statement-shape.md))

### 4.11 ห้ามอ้าง AUN-QA ในเอกสารหรือคอมเมนต์

keyword sweep v4.0 + v3.0: `distinctive` 0, `unique` 0, `boundary` 0, `identity` 0;
`scope` เจอแต่ในความหมาย "ขอบเขตการประเมิน" → **ไม่มีข้อความรองรับว่า scope statement
รองรับ AUN-QA Criterion 1**. ถ้าจะอ้างมาตรฐาน อ้าง traceability (immutable rule 2)
กับ ISCED-F ได้ AUN-QA ไม่ได้ ([ticket 01](issues/01-scope-boundary-standards.md))

**อ้างได้**: 4 ด้านของประกาศ กมอ. หลัง 2565 (ความรู้=K, ทักษะ=S, จริยธรรม=E, ลักษณะบุคคล=C)
ตรงกับ `SKILL_KSEC` หนึ่งต่อหนึ่ง — เป็นหลักฐานว่า KSEC ในโค้ดสอดคล้องกฎหมายปัจจุบัน
([ticket 08](issues/08-fetch-post-2565-standards.md))

### 4.12 ห้ามเว้นเลข PLO ให้ Need ที่ถูกกรอง

ช่องว่างแปลว่า "ร่างไม่สำเร็จ" อยู่แล้ว ใส่ความหมายที่สองทำให้อ่านไม่ออกทั้งคู่
([ticket 05](issues/05-synthesis-selection-filter.md))

### 4.13 ห้ามเติม Need นอกขอบเขตให้ครบ `MIN_NEEDS`

คือการผลิต PLO ที่รู้อยู่แล้วว่าผิดเพื่อให้ตัวเลขสวย
([ticket 05](issues/05-synthesis-selection-filter.md) ข้อ 3, [ticket 11](issues/11-two-axis-selection.md) ข้อ 5)

### 4.14 ห้าม 422 ที่ merge route และห้ามแตะ floor check ที่นั่น

ดูเหตุผลสามข้อที่หัวข้อ 3.8

### 4.15 ห้ามรวมตัวเลขสองแกนใน warning เป็นตัวเดียว

ความเท่ากันของสองตัวเลขคือข้อมูล — วันที่มันไม่เท่ากันคือวันที่สองแกนแยกกันจริง
ตัวเลขรวมทำให้สัญญาณนั้นหายไปตลอดกาล ([ticket 11](issues/11-two-axis-selection.md) ข้อ 4)

### 4.16 ห้าม prune cache ก่อน deploy

irreversible action ก่อนจุดที่ยังถอยได้ ([ticket 03](issues/03-extraction-prompt-and-cache.md) ข้อ 4)

---

## 5. test ที่ต้องมี

ทั้งหมด deterministic ล้วน อยู่ใน CI ได้ (eval ไม่อยู่ — หัวข้อ 3.10)

### 5.1 prompt — `tests/unit/test_extract_skills_prompt.py`

| test | ยืนยันอะไร |
|---|---|
| ไม่มี `scope_th` → system prompt ไม่มีบรรทัด "ขอบเขตของหลักสูตรนี้" | โปรแกรมที่ไม่เขียน scope ได้ prompt เดิม |
| มี `scope_th` → บรรทัดอยู่ใน **system** message ไม่ใช่ user message | ข้อห้าม 4.9 |
| มี `scope_th` → มี**ทั้งสอง**ประโยค (ทั้งบรรทัดขอบเขต และ "ห้ามสกัดทักษะจากบรรทัดนี้") | บรรทัดที่สองไม่ใช่ส่วนเกิน |
| กติกา `is_graduate_capability` + บรรทัดสคีมา อยู่เสมอ ไม่ว่าจะมี scope หรือไม่ | มันเป็น static |

### 5.2 contract — `tests/unit/test_extraction_cache_contract.py`

| test | ยืนยันอะไร |
|---|---|
| `_extraction_contract_fingerprint()` เท่ากันเมื่อ `scope_th` ต่างกัน | ข้อห้าม 4.2 — scope ไม่เข้า fingerprint |
| fingerprint ขยับเมื่อสคีมาเปลี่ยน (ธงใหม่อยู่ใน `model_json_schema()`) | re-extract รอบเดียวเกิดขึ้นจริงตามที่ตั้งใจ |

### 5.3 cache key — `tests/unit/test_skill_extraction_cache.py`

**เขียนแบบ replay entry ไม่ใช่ assert ราย call site** — บทเรียนจากบั๊กที่ key เขียนด้วย
`light_model` แต่ store ด้วย `heavy_model` ซึ่งรอดมาได้เพราะแต่ละ call site ถูก assert แยกกัน

| test | ยืนยันอะไร |
|---|---|
| วาง entry ที่ key มี `\x00{scope}` ต่อท้าย → `complete_extraction` ไม่ถูกเรียก | key ต่อ scope ถูกที่ ถูกลำดับ |
| โปรแกรมไม่มี scope → key ลงท้ายด้วย `\x00` (unconditional) → hit ได้ | ข้อ 3.3.1 ต่อแบบไม่มีเงื่อนไข |
| สอง scope ต่างกันบน chunk เดียวกัน → คนละ key | โปรแกรมที่แก้ scope re-extract เฉพาะตัวเอง |

### 5.4 predicate — `tests/unit/test_need_grouping.py` (หรือไฟล์ใหม่ `test_scope_guard.py`)

| test | ยืนยันอะไร |
|---|---|
| ตารางความจริงครบ 4 ช่อง: (in>0, grad>0)=True; อีกสามช่อง=False | `and` ตามข้อ 3.6 |
| Need ที่ default ทุกอย่าง (counter = จำนวนสมาชิก) → `is_in_scope` = True | **predicate เป็น no-op เมื่อไม่มี scope** — ข้อห้าม 4.1 |
| `Need.is_field_relevant` / `is_graduate_capability` = `count > 0` | กฎ any อยู่ที่เดียว |

### 5.5 counter — `tests/unit/test_need_combination.py`

| test | ยืนยันอะไร |
|---|---|
| สองแถวชื่อทักษะเดียวกัน ธงต่างกัน → counter นับ**สองแถวแยกกัน** | นับแถวดิบ ไม่ผ่าน or-by-name (ข้อ 3.5) |
| counter ≤ `len(member_skill_ids)` เสมอ | ตัวหารตรงกับตัวตั้ง |
| สมาชิกที่ `classification == "requirement"` แต่ `is_field_relevant=False` → ไม่นับเข้า counter | ข้อห้าม 4.4 — สองแกนไม่ไหลผ่าน classification |

### 5.6 migration — `tests/unit/test_migration_backfill.py` (เพิ่ม case)

| test | ยืนยันอะไร |
|---|---|
| `BACKFILL_NEED_COUNTS` อ้าง `jsonb_array_length(member_skill_ids)` ไม่ใช่ค่าคงที่ 0 | ข้อ 3.4.3 — แถวเก่าต้องรักษาพฤติกรรมเดิม |
| migration ตั้ง `server_default` ของ `skills.is_graduate_capability` เป็น true | เหมือน `is_field_relevant` |
| `down_revision` ชี้ที่ head ปัจจุบัน และคอลัมน์ทั้งสามตารางอยู่ใน revision เดียว | re-extract รอบเดียว (ข้อ 3.3.3) |

(import migration ผ่าน `importlib` ตาม precedent ของไฟล์นี้ — Alembic revision import
เป็น package ไม่ได้)

### 5.7 selection — `tests/unit/test_plo_synthesis_guard.py` / `test_plo_count_policy.py`

| test | ยืนยันอะไร |
|---|---|
| 12 Need ในสาขา + 2 Need นอกขอบเขตที่ `demand_score` สูงสุด → ได้ **10** PLO หลัก ไม่ใช่ 8 | **กรองก่อน `MAX_CORE_PLOS`** (ข้อ 3.7) |
| เลข PLO เรียง 1..n ต่อเนื่อง ไม่เว้นช่องให้ใบที่ถูกกรอง | ข้อห้าม 4.12 |
| Need นอกขอบเขตที่ `is_optional=True` ก็ถูกกรอง | ครอบทั้งสองซีรีส์ |
| กรองจนเหลือ < `MIN_NEEDS` → ยัง synthesize ต่อ + warning บอกสาเหตุในบรรทัดเดียวกัน | ข้อห้าม 4.13 + ข้อ 3.7(ข) |
| warning แยกตัวเลขสองแกน | ข้อห้าม 4.15 |
| Need ที่ถูกกรองยังอยู่ในตาราง `needs` ครบ (ไม่ถูกลบ) | immutable rule 6 |

### 5.8 merge route — `tests/unit/test_api_plos.py`

| test | ยืนยันอะไร |
|---|---|
| merge ด้วย Need นอกขอบเขต → **200** ไม่ใช่ 422 และไม่มี warning ใน response body | ข้อ 3.8 |
| merge ด้วย Need นอกขอบเขต → มี `logger.warning` | ตามรอยได้ว่า PLO ข้อนี้มาจากไหน |
| เงื่อนไข floor/ceiling เดิมยังทำงานเหมือนเดิมทุกเคส | ข้อห้าม 4.14 |

### 5.9 models — `tests/unit/test_models.py`

| test | ยืนยันอะไร |
|---|---|
| `ExtractedSkill` ไม่ระบุ `is_graduate_capability` → `True` | default รักษาพฤติกรรมเดิม |
| `ProgramCreateRequest` ไม่ระบุ `scope_th` → `""` และ validate ผ่าน | ฟอร์มไม่บังคับกรอก |
| `ProgramMetadata` ที่ deserialize จากแถวเก่า (ไม่มีคีย์ `scope_th`) ผ่าน | แถวเก่าอ่านได้ |

---

## 6. ลำดับการลงมือ

| # | งาน | ต้องไปพร้อมกันไหม | เหตุผล |
|---|---|---|---|
| 1 | `models.py` (สาม model) + `orm.py` + **migration เดียว** | **ใช่ — คอลัมน์สามตารางต้องอยู่ revision เดียว** | ธงใหม่ + scope + กติกาใหม่ ต้องทำให้ re-extract เกิด**ครั้งเดียว** ([ticket 03](issues/03-extraction-prompt-and-cache.md) ข้อ 4) แยก migration = จ่ายสองรอบ |
| 2 | `prompts/extract_skills.py` (parameter + สามบล็อกถ้อยคำ) | ต้องมาหลัง 1 | ต้องมี `scope_th` บน model ก่อนถึงจะมีอะไรส่งเข้า prompt |
| 3 | `skill_extraction.py` — `_SkillItem`, `scope_th` จาก metadata, cache key, เขียนธงลงแถว | **ต้องไปพร้อม 2** | สคีมาใน `_SkillItem` กับบรรทัดสคีมาใน prompt เป็นสัญญาเดียวกัน แยกกันเมื่อไรได้ ValidationError |
| 4 | `need_combination.py` — counter สองตัวที่ `_Group` และที่ `Need` | หลัง 1+3 | ต้องมีธงบนแถวก่อนถึงจะนับได้ |
| 5 | `need_grouping.py` — `is_in_scope()` | หลัง 1 | อ่าน `@property` บน `Need` |
| 6 | `plo_synthesis.py` — กรอง + log สองบรรทัด | หลัง 5 | — |
| 7 | `api/routes/plos.py` — `logger.warning` ที่ merge route | หลัง 5 | ใช้ predicate เดียวกัน |
| 8 | `Intake.tsx` — ช่อง `scope_th` + helper text | หลัง 1 (API รับ field แล้ว) | ทำหลังได้เพราะ backend รับค่าว่างอยู่แล้ว |
| 9 | `scripts/eval_scope_guard.py` + รัน `B0`/`B1`/ผลจริง | **หลัง 1-8 ครบ** | `B1` ต้องรันบน branch ใหม่ที่มีธงครบ; `B0` ต้องเก็บ**ก่อน** merge |
| 10 | checkpoint / report UI | **บล็อกอยู่ — รอ [ticket 06](issues/06-checkpoint-two-buckets.md)** | หัวข้อ 3.9 |

### จุดที่ต้องระวังตามลำดับเวลา

- **`B0` ต้องเก็บก่อน merge branch** — `B0` คือ branch เดิม ก่อนธงใหม่ ถ้า merge ไปแล้ว
  ต้องย้อน checkout มารันซึ่งเสียเวลาและเสี่ยงรันคนละ config
- **deploy → re-extract หนึ่งรอบทั้งระบบ** เป็นราคาที่ประกาศไว้แล้ว ไม่ต้องเตือนใน UI
  (ข้อ 3.3.3)
- **`prune_cache --delete` รันทีหลัง** เมื่อมั่นใจแล้วว่าไม่ต้อง rollback
  (`uv run python -m curriculum_agent.data.prune_cache` รายงานอย่างเดียวก่อน)
- **ห้าม merge ก่อน 9 ผ่าน hard gate `FP = 0` ที่ระดับ Need** — ถ้าไม่ผ่าน fallback คือ
  ปิดสวิตช์กรอง (หยุดเรียก `is_in_scope` ที่จุดเดียวใน 6) แล้วปล่อยธงให้ designer ดู
  ไม่ใช่ผ่อนเกณฑ์

---

## ภาคผนวก — สรุปจุด "ยังไม่ตัดสิน"

| # | เรื่อง | ใบที่ควรตอบ |
|---|---|---|
| 1 | ของตั้งต้นในฟอร์ม intake เป็น static placeholder หรือ auto-seed จาก ISCED-F / ประกาศ กมอ. | [02](issues/02-scope-statement-shape.md) (หรือใบใหม่) |
| 2 | เพดานความยาวของ `scope_th` — scope ยาวกว่า ~150 ตัวอักษรเริ่มปนไหม | [07](issues/07-eval-protocol.md) รอบแรกที่รันจริง |
| 3 | แต่ละรายการในก้อน "นอกขอบเขต" ที่ checkpoint แสดงอะไร | [06](issues/06-checkpoint-two-buckets.md) |
| 4 | ถ้อยคำ "แก้ scope statement แล้วต้องรันอะไรใหม่บ้าง" | [06](issues/06-checkpoint-two-buckets.md) |
| 5 | สามก้อนอยู่ที่ checkpoint, `plo_report`, หรือทั้งสอง | [06](issues/06-checkpoint-two-buckets.md) |
| 6 | `plo_report` / มคอ.2 exporter ต้องรายงาน Need ที่ถูกกันไหม รายงานให้ใคร | [06](issues/06-checkpoint-two-buckets.md) แล้วจึงแตกใบใหม่ |
| 7 | `summarize_need` ควรเห็นธงรายสมาชิกไหม และถ้าเห็นควรทำอะไร | ยังไม่มีใบ — ต้องตั้งใหม่ |

**อีกสองข้อที่รู้แต่ไม่ใช่ของ map นี้** (บันทึกไว้ อย่าไป "แก้" ระหว่างทาง):

1. เฉลยมนุษย์ TCISM มี **4 PLO** ส่วน rule 6 กำหนด 6-10 และ `MIN_NEEDS = 6`
2. theme ของมนุษย์ **ตัดข้าม KSEC** (A ผสม K+S, C ผสม K+E) ส่วนกฎห้าม cluster ข้าม bucket
   → `need_combination` ผลิต theme แบบนั้นไม่ได้เชิงโครงสร้าง

ทั้งสองข้อต้องเป็น map ใหม่หรือการทบทวน immutable rule ไม่ใช่ ticket ในนี้
