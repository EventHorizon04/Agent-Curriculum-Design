# 15 — ผลรันจริงได้ **PLO หลัก 0 ข้อ** และ `need` เป็นคลาสที่เอื้อมไม่ถึง

Map: [PLO synthesis ที่ไม่หลุด scope ของหลักสูตร](../map.md)
Type: bug / grilling
Status: open
Blocked by: (none)

## สิ่งที่วัดได้ (2026-09-18 จาก DB จริง ไม่ใช่การอนุมาน)

โปรแกรมเดียวในฐาน (ชุด TCISM) · evidence 14 · skills 99 · needs 10 · plos 8

```
plos:   OPT1..OPT8   →  is_optional = true ทั้งหมด   →  PLO หลัก = 0 ข้อ
needs:  9 ใน 10 เป็น is_optional = true
skills: classification = want 70 · unclassified 29 · need 0 · requirement 0
```

**immutable rule 6 กำหนด PLO หลัก 6-10 ข้อ ผลรันได้ 0** และไม่มีอะไรหยุดมัน —
`need_combination` log policy warning ตอน core < `MIN_NEEDS` แต่เป็นแค่บรรทัด log

## สาเหตุมีสองสาย และแยกกันอิสระ

### สาย 1 — `need` เอื้อมไม่ถึงในทางปฏิบัติ

`classify_skills` (`stages/skill_extraction.py`) ลำดับความสำคัญ:

```
1. named by requirement evidence  → requirement
2. name matches such a skill      → requirement
3. is_field_relevant = False      → unclassified
4. named by >1 evidence item      → need
5. otherwise                      → want
```

วัดจริง: **ชื่อทักษะ 99 ชื่อ มี 0 ชื่อที่ถูกตั้งโดย evidence มากกว่า 1 ชิ้น**

```sql
SELECT count(*) distinct_names, count(*) FILTER (WHERE n>1) more_than_one
FROM (SELECT lower(btrim(skill_name_th)) nm, count(DISTINCT source_evidence_id) n
      FROM skills GROUP BY 1) x;
-- 99 | 0
```

กฎข้อ 4 ต้องการให้โมเดลสกัดชื่อ **ตรงกันเป๊ะ** (หลัง `normalize_need_name` = trim +
lowercase + ยุบช่องว่าง) จาก evidence คนละชิ้น ซึ่งกับชื่อทักษะภาษาไทยแบบ free text
แทบไม่เกิด → **กฎ 4 ไม่เคยยิง และทุกอย่างที่ผ่านกฎ 3 ตกไปเป็น `want`**

นี่คือเรื่องเดียวกับที่ [idea: evidence-aware clustering] บันทึกไว้ว่า
**ตัวขวางจริงคือ dedupe ที่ยุบชื่อซ้ำ** — แต่ที่นี่ผลของมันหนักกว่า เพราะมันไม่ได้แค่
ทำให้กลุ่มเพี้ยน มันทำให้ทั้งโปรแกรมไม่มี PLO หลัก

**สิ่งที่ต้องตัดสิน**: `need` ควรวัดจากชื่อที่ตรงกันเป๊ะ หรือจากอย่างอื่น
(ชื่อที่ลงเอยใน Need เดียวกัน · ชื่อที่ cluster เดียวกัน · จำนวน stakeholder ที่ต่างกัน)
ทางที่ราคาถูกที่สุดคือย้ายการนับไปหลัง clustering ซึ่งยุบชื่อใกล้เคียงให้แล้ว —
แต่ `classification` ถูกใช้ตอน `is_optional_group` ซึ่งอยู่ **หลัง** clustering อยู่แล้ว
จึงอาจไม่ต้องรื้ออะไรมาก · ต้องไล่ลำดับให้ชัดก่อนเสนอ

### สาย 2 — evidence ฝั่งสถาบันยังไม่ถูก classify

`institutional_direction` 3 ชิ้น (ให้ skills 17 ตัว) ยังเก็บเป็น
`classification = 'general'` ทั้งที่ `REQUIREMENT_TYPES` มี `INSTITUTIONAL_DIRECTION`
ตั้งแต่ `037d53d` (2026-08-03) และ evidence ชุดนี้เก็บวันที่ 2026-09-08 — **กฎมีก่อนข้อมูล**

**โค้ดถูก ข้อมูลยังไม่ผ่านขั้นนั้น**: `stages/stakeholder_needs.run` reclassify ทุกชิ้น
ทุกรอบและเขียนกลับ (`bulk_insert`) ส่วน `StakeholderEvidence.classification` default
เป็น `"general"` → evidence ที่เพิ่มผ่าน API แล้วไม่เคยผ่าน stage 1 จะค้างเป็น general

ตรงกับ ERROR ที่เจอวันเดียวกัน (19:46 `Stage 4: no Needs`) — รอบนั้นคือรอบที่ graph
เดินโดยไม่อ่าน input จาก repository ซึ่งแก้ไปแล้วใน `pipeline-vs-manual-stage-input`
แต่ **ข้อมูลที่ค้างจากรอบนั้นยังไม่ถูกแก้**

ถ้า 17 ตัวนั้นได้เป็น `requirement` กฎข้อ 1 จะยิง และภาพรวมจะเปลี่ยนทันที

### สาย 3 (ไม่ใช่สาเหตุ แต่ทำให้เห็นชัด) — Need หลักใบเดียวถูก scope guard กรอง

ใบเดียวที่ `is_optional = false` คือ:

> ต้องการบัณฑิตที่สามารถ**ออกแบบหลักสูตรการเรียนการสอน**ภาษาไทยและภาษาจีนที่มีจุดเด่น…

`in_field_skill_count = 0 / 15` และ `graduate_capability_skill_count = 0 / 15`
→ `is_in_scope()` กรองออก **ถูกต้องแล้ว** — การออกแบบหลักสูตรเป็นภารกิจของสถาบัน
ไม่ใช่สมรรถนะของบัณฑิต scope guard ทำงานตรงตามที่ออกแบบ

แต่ผลลัพธ์รวมคือ: Need หลักมีใบเดียว และใบนั้นถูกกรอง → **PLO หลัก 0**

## รันใหม่ครบสายแล้ว — 2026-09-18 23:00-23:05 (ผลจริง ไม่ใช่การคาด)

ลำดับ: `GET /evidence/classify-stream` → `POST /needs/skills/run` → `POST /needs/combine/run`
→ `POST /plos/run` (คือปุ่มเดียวกับที่หน้าเว็บกด)

| ตัวชี้วัด | ก่อน | หลัง |
|---|---|---|
| evidence `requirement` | 0 | **3** |
| skills ทั้งหมด | 99 | 63 |
| skill `requirement` | 0 | **11** |
| skill `need` | 0 | **2** |
| skill `want` / `unclassified` | 70 / 29 | 32 / 18 |
| Needs | 10 | 11 |
| **core Needs** | 1 | **3** |
| Need ถูก `is_in_scope` กรองตอน synthesis | — | **4 ใบ** |
| **PLO หลัก** | **0** | **1** |
| PLO เสริม | 8 | 6 |
| escalated | 1 | 0 |

### สาย 2 — ยืนยันว่าเป็นสาเหตุจริง และแก้ได้ฟรี

รัน stage 1 อย่างเดียว (0 LLM call) ทำให้ `institutional_direction` 3 ชิ้นเป็น
`requirement` แล้วกฎข้อ 1 ของ `classify_skills` ยิงทันที **11 ตัว** จาก 0

### สาย 1 — ยังอยู่ครบ และตอนนี้มีหลักฐานรอบสอง

ชื่อทักษะ **62 ชื่อ ซ้ำข้าม evidence แค่ 1 ชื่อ** (รอบก่อน 99 ชื่อ ซ้ำ 0) →
`need` ได้มา 2 ตัวจากชื่อเดียวนั้น · กฎ `>1 evidence → need` **ยังแทบไม่ยิง**
คนละโมเดล คนละรอบ ผลเหมือนเดิม → **เป็นเรื่องนิยามของกฎ ไม่ใช่เรื่องข้อมูลไม่ครบ**

### ยังไม่ถึง `MIN_NEEDS` และ log พูดเองทั้งสองที่

```
need_combination: produced only 3 core Needs (policy is at least 6)
plo_synthesis:    produced 1 core PLOs, below the 6 minimum policy —
                  กรอง Need นอกขอบเขตออก 4 ใบก่อนร่าง (หลักฐานในขอบเขตไม่พอ)
```

Need ฝั่งสถาบันที่เพิ่งเลื่อนขึ้นเป็น `requirement` กลายเป็น core Need แล้วถูก
`is_in_scope` กรองออกที่ synthesis — **สองกลไกนี้ดันสวนกัน**: "requirement wins" ดึงเสียง
ของสถาบันเข้ามา ส่วน scope guard บอกว่ามันไม่ใช่สมรรถนะของบัณฑิต ทั้งคู่ทำถูกตามสเปก
(`is_in_scope` docstring เขียนไว้เองว่า requirement ไม่ได้รับการยกเว้น และเป็นการตัดสินใจ)
ผลรวมคือ Need ฝั่งสถาบันกิน core slot แล้วโดนกรองทิ้ง ซึ่งอธิบาย core 3 → PLO หลัก 1

### ข้อสังเกตแถม — SMART agent ใช้ budget หมดกับ soft flag

PLO1 เดินครบ 8 turn ทำ repair 2 ครั้งกับ `A_level` (soft flag ที่ **block ไม่ได้**)
แล้ว budget หมด → `code_only` · code gate ผ่าน ไม่ escalate
soft flag กินงบทั้งก้อนของ PLO ได้ ทั้งที่ตามนิยามมันไม่มีสิทธิ์ขวางอะไร — ควรดูว่า
ควรจำกัด repair ที่มาจาก soft flag อย่างเดียวหรือไม่

## วัดสามตัวเลือกจาก DB จริง — 2026-09-19 (ยังไม่แก้โค้ด)

### `classification` ไหลไปจุดเดียว

```
classify_skills (ต่อชื่อทักษะ) → classification_coverage (ต่อกลุ่ม หลัง clustering)
                               → is_optional_group() → Need.is_optional → PLO หลัก / OPT
```

`is_optional_group` (`stages/demand.py:80`) ทั้งฟังก์ชันคือ `want > requirement + need`
→ **`need` ไม่ได้แปลว่าอะไรในตัวเอง มันคือเสียงโหวตฝั่ง "กลุ่มนี้เป็นแกน" เท่านั้น**
กฎ 4 ไม่ยิง = ฝั่งนั้นเหลือ `requirement` ลำพัง

### ตัวเลือกทั้งสามยุบเหลือทางเดียว

| ตัวเลือกในใบนี้ | วัดแล้วได้อะไร |
|---|---|
| นับหลัง clustering | ย้ายจุดนับจาก "ชื่อ" → "กลุ่ม" — ทางเดียวที่ต่างจริง |
| ชื่อที่ลงเอยใน Need เดียวกัน | **เหมือนข้างบน** — `is_optional_group` นับ coverage ทั้งกลุ่มอยู่แล้ว |
| จำนวน stakeholder ที่ต่างกัน | **ไม่ต่างจาก evidence count เลย** ทั้งสองระดับ |

ชื่อทักษะ 62 ชื่อ: ซ้ำข้าม evidence **1 ชื่อ** · ซ้ำข้าม stakeholder **1 ชื่อ** — เลขเท่ากันเป๊ะ
เพราะ evidence คนละชิ้นในชุดนี้มาจาก stakeholder คนละประเภทอยู่แล้ว มันวัดสิ่งเดียวกันซ้ำ

### ถ้าย้ายจุดนับไปที่กลุ่ม — ผลบน 11 Need ที่มีอยู่

| need | ev | req | need | want | unc | เดิม | ใหม่ | in_scope |
|---|---|---|---|---|---|---|---|---|
| 117cea3e | 8 | 3 | 0 | 6 | 1 | เสริม | **หลัก** | ✓ |
| d7b1b6c3 | 8 | 2 | 0 | 3 | 3 | เสริม | **หลัก** | ✗ |
| f076cd90 | 6 | 5 | 0 | 3 | 1 | หลัก | หลัก | ✗ |
| 2f985a49 | 5 | 0 | 0 | 5 | 3 | เสริม | **หลัก** | ✓ |
| 75ba8ce4 | 5 | 1 | 0 | 2 | 2 | เสริม | **หลัก** | ✗ |
| 265e124a | 4 | 0 | 0 | 5 | 0 | เสริม | **หลัก** | ✓ |
| c113c439 | 4 | 0 | 0 | 4 | 1 | เสริม | **หลัก** | ✓ |
| ee0bc4e5 | 3 | 0 | 0 | 0 | 6 | หลัก | หลัก | ✗ |
| 2ac9e537 | 3 | 0 | 0 | 2 | 1 | เสริม | **หลัก** | ✓ |
| a396039d | 2 | 0 | 2 | 0 | 0 | หลัก | หลัก | ✓ |
| c838a60b | **1** | 0 | 0 | 2 | 0 | เสริม | เสริม | ✓ |

`is_in_scope` กรอง **ก่อน** ตัดเพดาน `MAX_CORE_PLOS` (`plo_synthesis.py:435` มาก่อน `:446`)

```
core Needs   3 → 10   (ทุกใบยกเว้นใบที่มาจาก evidence ชิ้นเดียว)
ผ่าน scope   1 → 6    → PLO หลัก 1 → 6 พอดี MIN_NEEDS · OPT เหลือ 1
```

### ราคาที่ต้องยอมรับ: `is_optional` แทบหมดความหมาย

นิยามใหม่แปลตรงตัวว่า "กลุ่มที่มาจาก evidence มากกว่าชิ้นเดียว = แกนหลักสูตร" ซึ่ง clustering
ยุบชื่อจากหลาย evidence เข้าด้วยกันเป็นปกติ → เกือบทุกกลุ่มผ่าน เหลือ optional แค่ใบที่
stakeholder รายเดียวพูดถึง · **ต้องตอบก่อนรับ**: ถ้าเกือบทุกกลุ่มเป็นหลัก ยังต้องมี `want`
กับ `is_optional_group` อยู่ไหม หรือกลายเป็น "6-10 ใบแรกตาม `demand_score`" ไปเลย

### สองอย่างที่เจอระหว่างวัด

**1. `unclassified` ทั้งกลุ่ม = ได้ core slot ฟรี** — `ee0bc4e5` เป็น core หลักอยู่ตอนนี้
ทั้งที่ทุก member เป็น `unclassified` 6 ตัว: `0 > 0` เป็น false → ไม่ optional
docstring เขียนเองว่า unclassified "ไม่นับให้ฝั่งไหน" แต่ผลจริงคือนับให้ฝั่งหลักโดยปริยาย
เพราะ default ของ `>` คือ false · กลุ่มที่โมเดลไม่แน่ใจทั้งกลุ่มไม่ควรเป็นแกนหลักสูตร
**แก้ได้แยกจากคำถามหลัก และแก้ฟรี**

**2. ทางที่ 4 ที่ใบนี้ไม่ได้เขียน** — 7 ใบผ่าน scope guard และ 6 ใน 7 เป็น optional อยู่
เรียง 7 ใบนั้นตาม `demand_score` คือชุด core ที่ใช้ได้ทันทีโดยไม่แตะ `classification` เลย
= **ให้ scope guard เป็นตัวตัด core/optional แทน `is_optional_group`** ส่วน want/need
ลดชั้นเป็นข้อมูลแสดงผล · ยังไม่เสนอ ต้องชั่งกับเจตนาเดิมของ optional PLO ก่อน

### ราคา implement — ทั้งสามทางไม่แตะ prompt

| ทาง | แตะอะไร | cache | re-extract |
|---|---|---|---|
| นับที่ระดับกลุ่ม | `is_optional_group` + จุดเรียกใน `need_combination` | ไม่ขยับ | **ไม่ต้อง** |
| ปิดช่อง unclassified | `is_optional_group` บรรทัดเดียว | ไม่ขยับ | ไม่ต้อง |
| ให้ scope guard ตัด core | slot selection ใน `plo_synthesis` | ไม่ขยับ | ไม่ต้อง |

ไม่ขยับ `_EXTRACTION_CONTRACT` / `_CLUSTERING_CONTRACT` → รันซ้ำแค่
`POST /needs/combine/run` + `POST /plos/run`

## สิ่งที่ต้องกดให้แตก

1. ~~แก้สาย 2 ก่อนแล้ววัดใหม่~~ **ทำแล้ว** — core PLO 0 → 1 ยังไม่ถึง 6
   สาย 2 เป็นสาเหตุจริงแต่ไม่ใช่สาเหตุเดียว
2. **ราคา re-extract ตอนนี้ต่ำผิดปกติ** — `llm_cache` มี 20 แถว live 3 stale-model 17
   (17 แถวมาจาก `anthropic/claude-fable-5.1` ที่เคยทดลองแล้ว revert config ไปแล้ว)
   → ข้อโต้แย้งเรื่อง "ต้องรวมแก้ prompt ครั้งเดียวเพื่อจ่ายค่า re-extract รอบเดียว"
   **แทบไม่มีน้ำหนักแล้ว** ของที่จะเสียมี 3 แถว
3. **`MIN_NEEDS` ควรหยุดอะไรได้ไหม** — ตอนนี้เป็น log warning เพราะ "โค้ดผลิต Need
   เพิ่มเองไม่ได้" ซึ่งยังจริง แต่ core = 0 ต่างจาก core = 4 เชิงคุณภาพ:
   โปรแกรมที่ไม่มี PLO หลักเลย ไม่ใช่โปรแกรมที่ Need น้อย
4. **เฉลยมนุษย์ TCISM มี 4 PLO** (บันทึกไว้ใน map ว่าขัด rule 6 อยู่แล้ว) — เทียบกับ
   ผลรันที่ได้ 0 หลัก + 8 เสริม การเทียบ recall/FP ตาม [ticket 07](07-eval-protocol.md)
   ต้องนิยามก่อนว่าจะเทียบกับ OPT ด้วยไหม

## ผลลัพธ์ที่ต้องได้

~~รันใหม่ให้ครบสายเพื่อดูว่า core count ขยับหรือไม่~~ **ทำแล้ว** — core PLO 0 → 1

เหลือข้อเดียว: **ตัดสินว่า `need` จะวัดจากอะไร** ตอนนี้มีตัวเลขครบทั้งสามทางแล้ว
ทางที่เหลือจริงมีทางเดียว (นับที่ระดับกลุ่ม → PLO หลัก 6) และมีผลข้างเคียงที่ต้องยอมรับ
คือ `is_optional` แทบหมดความหมาย — ตัดสินใจนี้ก่อน แล้วค่อยแตะโค้ด
