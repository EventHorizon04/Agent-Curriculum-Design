# Review — guidance 3 ไฟล์ที่อยู่หลัง cache fingerprint

`skill_extraction.md` · `skill_clustering.md` · `cluster_merging.md`
เทียบกับ `prompts/extract_skills.py` และ `prompts/cluster_skills.py`

รอบนี้ **review ล้วน ไม่แตะโค้ด** ต่อจาก [รีวิวไฟล์แรก](market-need-synthesis-review.md)

---

## ทำไมสามไฟล์นี้อยู่ในเอกสารเดียว

ไม่ใช่เพราะเนื้อหาใกล้กัน แต่เพราะ **ราคาของการแก้เป็นก้อนเดียว**

| ไฟล์ | prompt builder | fingerprint ที่ hash มัน | แถวที่ตายถ้าแก้ |
|---|---|---|---|
| `skill_extraction.md` | `build_extract_skills_prompt` | `_EXTRACTION_CONTRACT` (`stages/skill_extraction.py:179-199`) | `kind=extraction` ทั้งตาราง |
| `skill_clustering.md` | `build_cluster_skills_prompt` | `_CLUSTERING_CONTRACT` (`stages/llm_clustering.py:109-141`) | `kind=clustering` ทั้งตาราง |
| `cluster_merging.md` | `build_merge_clusters_prompt` | `_CLUSTERING_CONTRACT` **ตัวเดียวกัน** | `kind=clustering` ทั้งตาราง |

fingerprint hash **system prompt ทั้งก้อน + JSON schema** ของ response model
แก้ตัวอักษรเดียวในสามไฟล์นี้ → แถวเก่ากลายเป็น `stale-contract` **อ่านไม่ได้ตลอดกาล**
(มองไม่เห็นด้วย เพราะ key ไม่ตรงแล้ว — นั่นคือเหตุผลที่ `kind`/`contract` ถูกเก็บเป็น
column ต่างหาก เพื่อให้ sweep บอกได้ว่าทำไมแถวเอื้อมไม่ถึง)

สองผลที่ตามมา และเป็นเหตุผลของรูปเอกสารนี้:

1. **`cluster_merging.md` กับ `skill_clustering.md` แชร์ fingerprint** → แก้ตัวหนึ่ง
   อีกตัวก็ตายไปด้วยฟรี ๆ ถ้าจะแก้ตัวหนึ่ง **ไม่มีเหตุผลที่จะไม่แก้อีกตัวพร้อมกัน**
2. `skill_extraction` แพงที่สุด — เป็น stage ที่ fan out **1 call ต่อ window ต่อ evidence**
   (ดู `chunk_evidence_text`) คือ stage ที่เผา quota ก่อนใครเพื่อน

### ⚠️ ตัวเลขจริง (วัดแล้ว 2026-09-18) — **ราคาที่กลัวกันแทบไม่มีอยู่จริง**

```
20 cache row(s): 3 live, 17 stale-model, 0 stale-contract, 0 orphaned-kind
  stale-model:  3 row(s) from clustering  on anthropic/claude-fable-5.1
  stale-model: 14 row(s) from extraction  on anthropic/claude-fable-5.1
```

`llm_cache` มี **20 แถว** และ **17 แถวตายไปแล้ว** — ตายเพราะ `stale-model` ไม่ใช่
`stale-contract`: ทั้งหมดเขียนตอนทดลอง `anthropic/claude-fable-5.1` ที่ค้างเป็นคอมเมนต์
ใน `config.py` แล้ว revert ทิ้งไปเมื่อ 2026-09-18

**เหลือของจริงที่จะเสีย 3 แถว** → ข้อโต้แย้ง "ต้องรวมแก้ทุกไฟล์ครั้งเดียวเพื่อจ่ายค่า
re-extract รอบเดียว" **แทบไม่มีน้ำหนักแล้ว** คลังทดสอบมี evidence 14 ชิ้น ซึ่งคือ
extraction 14 call — ถูกกว่าการรอให้ตัดสินครบทุกข้อมาก

ข้อสรุปเดิมของเอกสารนี้ ("ราคาต่ำสุดคือรวมทุกอย่างไว้ในการขยับ fingerprint ครั้งเดียว")
จึงต้องอ่านใหม่: **มันถูกในเชิงหลักการ แต่ตัวเลขบอกว่าจะแยกลงทีละไฟล์ก็ได้**
สิ่งที่ยังควรรวม คือความ *สอดคล้อง* ของกติกาข้ามไฟล์ ไม่ใช่ราคา

รันซ้ำได้ด้วย `uv run python -m curriculum_agent.data.prune_cache` (ไม่ลบอะไรถ้าไม่ใส่
`--delete`)

---

## ข้อสรุปสั้นที่สุด

**สามไฟล์นี้ตั้งคำถามชุดเดียวกับ [ใบ 01](issues/01-need-sentence-subject.md) /
[02](issues/02-curriculum-level-line.md) / [03](issues/03-need-rationale-th.md) ที่เปิดไว้แล้ว**
ไม่ใช่คำถามใหม่:

| ใบที่เปิดไว้ | คำถามเดียวกันในสามไฟล์นี้ |
|---|---|
| 01 · framing "ตลาดแรงงาน" vs ผู้มีส่วนได้ส่วนเสียทุกกลุ่ม | role line ของ `skill_extraction.md:7` |
| 02 · เส้นแบ่ง กว้าง/แคบ | `skill_clustering.md` กฎ 3 (Skill Family) ปะทะกฎ 4 (Occupational Identity) **ในไฟล์เดียวกัน** |
| 03 · `rationale_th` | `rationale_th` ของ cluster + `merge_rationale_th` |

→ **ตัดสิน 3 ใบนั้นก่อน แล้วลง prompt ทั้ง 4 ไฟล์ครั้งเดียว จ่ายค่า re-extract รอบเดียว**
นี่คือลำดับที่ถูกที่สุดทั้งในแง่เงินและในแง่ความสอดคล้อง (precedent: `a3f8d61e04c7`
ตั้งใจให้ธงใหม่ + scope + กติกาไปพร้อมกันเพื่อ re-extract ครั้งเดียวจบ)

---

## 1 · `skill_extraction.md` (359 บรรทัด)

| # | กฎ | สถานะ | เหตุผล |
|---|---|---|---|
| — | role line `:7` "ทักษะที่**ตลาดแรงงาน**ต้องการ" | ⚠️ **ชน** | ดู §ชน-A |
| — | ห้ามใช้ความรู้ภายนอก/คาดเดา/แต่ง `:17-20` | ✅ ซ้ำ | `extract_skills.py:56-57` |
| — | นิยามของทักษะ `:28` | ➕ ใหม่ · ฟรี | code ไม่มีนิยามเลย มีแต่ "ต้องเป็นวลี ห้ามคำโดด" (`:53`) |
| — | สิ่งที่ห้ามสกัด `:34-47` | ⚠️ **ชน + ขัดตัวเอง** | ดู §ชน-B |
| — | ตัวอย่าง ❌`Power BI` ✅`การวิเคราะห์ข้อมูลด้วย BI` `:51-65` | ➕ ใหม่ · ฟรี | ส่วน "ชื่อเครื่องมือเดี่ยวไม่ใช่ทักษะ" ไม่ชนอะไร |
| 1 | Evidence Grounding | ✅ ซ้ำ | `:56-59` ครบทั้ง "ตรงตัว" และ "อย่างน้อย 12 ตัวอักษร" |
| 2 | Skill Independence | ✅ ซ้ำ | `:54-55` |
| 3 | Skill Normalization | 🔧 **ทำตามไม่ได้** | ดู §ควรเป็นโค้ด |
| 4 | Occupational Identity + `{program_context}` | ➕ หลักการฟรี · **ตัวแปรไม่ฟรี** | ดู §ไม่ฟรี-A |
| 5 | Job Identity Test | ➕ ใหม่ · ฟรี | คู่กับกฎที่เพิ่งลงใน `summarize_need` (`a8a497b`) — ขยับขึ้นมาที่ชั้นสกัด |
| 6 | Field Relevance / `scope_th` | ✅ ซ้ำ | `:71-78` ตรงกันทุกประโยค รวม "ห้ามสกัดทักษะจากบรรทัดนี้" |
| 7 | Graduate Capability | ✅ ซ้ำ | `:66-69` |
| 8 | Bloom "ระดับต่ำที่สุดที่จำเป็น" | ➕ ใหม่ · ฟรี · ⚠️ มีผลข้างเคียง | code บอกแค่ "Cognitive เท่านั้น" (`:86-87`) · แต่ `merge_bloom` เอา **max** ของชื่อซ้ำ การกดให้ต่ำจึงกดระดับของทั้ง Need ลงด้วย ควรตั้งใจ ไม่ใช่ผลพลอยได้ |
| 9 | KSEC เลือกค่าเดียว | ✅ ซ้ำ | `:83-85` |
| 10 | Confidence rubric | 💤 **ไม่มีใครอ่าน** | ดู §ที่ไม่มีใครอ่าน |
| — | checklist 1-9 `:318-326` | ส่วนใหญ่ซ้ำ | ข้อ 4/5 มาจากลิสต์ §ชน-B · ข้อ 9 (ไม่เกิน 8) ซ้ำกับ `:93` |
| — | `:351` "ไม่เกิน 8 ทักษะต่อ **evidence**" | ⚠️ ผิดหน่วย | code เขียน "ต่อ**ข้อความ**" (`:93`) และ evidence ถูกตัดเป็น window ก่อน → เพดานจริงคือ 8 ต่อ window ไม่ใช่ต่อ evidence |

## 2 · `skill_clustering.md` (304 บรรทัด)

| # | กฎ | สถานะ | เหตุผล |
|---|---|---|---|
| — | ห้ามลบ/ละเว้น/สร้างทักษะใหม่ `:13-15` | ✅ ซ้ำ | `cluster_skills.py:52-53` |
| — | `{program_context}` `:30` **ไม่มีเงื่อนไข** | ⚠️ ต้องแก้ก่อนใช้ | code ใส่แบบมีเงื่อนไข (`:27-32`) และ fingerprint **sample ทั้งสองแบบ** (`llm_clustering.py:131-139`) · แบบไม่มีเงื่อนไขทำให้โปรแกรมที่ไม่มี context เห็นปีกกาดิบ และทำ `test_no_program_context_leaves_the_prompt_unchanged` แดง |
| 1 | Complete Coverage | ✅ ซ้ำ | `:52-53` |
| 2 | Meaning-Based Grouping | ✅ ซ้ำ + ชัดขึ้น = ฟรี | `:49-51` |
| 3 | Skill Family Level | ⚠️ **ตึงกับกฎ 4 ในไฟล์เดียวกัน** | ดู §ชน-C |
| 4 | Occupational Identity Preservation | ➕ ใหม่ · ฟรี | |
| 5 | Job Identity Test (ชื่อกลุ่ม) | 💤 **ชื่อกลุ่มถูกทิ้ง** | ดู §ที่ไม่มีใครอ่าน |
| 6 | Semantic Correctness First | ➕ ฟรี · ตรงเจตนาโค้ดที่ prompt ไม่เคยพูด | `allocate_cluster_targets` docstring บอกเองว่า target เป็นเป้า **ไม่ใช่ cap** และ `validate_assignments` รับ partition ที่ได้มาเสมอ — prompt ปัจจุบันไม่เคยบอกโมเดล |
| 7 | Cluster Count `{target_clusters}` | ✅ ซ้ำ | `:40-46` |
| 8 | Cluster Label Quality (ห้าม "อื่น ๆ") | 💤 เหมือนข้อ 5 | |
| 9 | Cluster Rationale (`rationale_th`) | 💸 **ไม่ฟรี** | เพิ่ม field บน `ClusterAssignment` = schema เข้า fingerprint ตรง ๆ และเป็นเหตุผลของกลุ่มที่ชื่อกลุ่มยังถูกทิ้งอยู่ |
| — | ตารางท้ายไฟล์ `:235-303` | ✂️ ตัดก่อนใช้ | บันทึกเหตุผล ไม่ใช่คำสั่งถึงโมเดล และ flatten จนเสีย pipe |

## 3 · `cluster_merging.md` (310 บรรทัด)

**ไฟล์ที่คุ้มที่สุดในสามไฟล์** — เกือบทั้งไฟล์เป็นของใหม่ที่ไม่ชนอะไร และแก้ช่องที่ prompt
เดิมเปิดไว้จริง

| # | กฎ | สถานะ | เหตุผล |
|---|---|---|---|
| — | ห้ามสร้าง/ลบ/ละเว้นกลุ่ม `:15-19` | ✅ ซ้ำ | `cluster_skills.py:90-92` |
| — | **"ห้ามรวมเพียงเพราะ เกี่ยวข้องกัน / ทำงานร่วมกัน / อยู่ในสายงานเดียวกัน"** `:31-35` | ➕ ใหม่ · **ชิ้นที่ดีที่สุด** | prompt เดิมพูดแค่ "Some clusters share the same meaning and should be merged" (`:87-88`) ไม่มีเส้นแบ่ง "เกี่ยวข้อง vs เหมือน" เลย ซึ่งเป็นวิธีที่ merge กินความหมายหาย |
| 1 | Complete Coverage | ✅ ซ้ำ | `:90-92` |
| 2 | Merge Only Equivalent Competencies | ➕ ใหม่ | |
| 3 | Do NOT Merge Related + ตัวอย่าง `การแปลเอกสาร`/`การล่าม` | ➕ ใหม่ | ตัวอย่างตอบได้จาก label อย่างเดียว ซึ่งเป็นทั้งหมดที่ขั้นนี้เห็น — ทำตามได้จริง |
| 4 | Occupational Identity Preservation | ➕ ใหม่ | |
| 5 | Distinct Competency Preservation | ➕ ใหม่ | สอดคล้องกับ target≠cap ที่โค้ดตั้งใจอยู่แล้ว |
| 6 | Semantic Correctness First | ➕ ใหม่ | |
| 7 | Target Number of Groups | ✅ ซ้ำ | `:79-83` |
| 8 | Merge Decision Test | ➕ ใหม่ | ถามตรงจุด: รวมแล้ว Need/PLO ยังแยกความสามารถได้ไหม |
| 9 | Merge Rationale | 💸 **ไม่ฟรี** | `MergeGroupsResponse` มี `groups` อย่างเดียว (`llm_clustering.py:105-106`) |
| — | ตารางท้ายไฟล์ `:244-307` | ✂️ ตัดก่อนใช้ | |

---

> **อัปเดต 2026-09-18 — ชน-A และ ชน-C ปิดแล้วโดยใบ 01/02**
>
> - **ชน-A**: ใบ 01 ตอบว่าคง `บัณฑิต/หลักสูตร` → **ไม่รับ** role line
>   "ทักษะที่ตลาดแรงงานต้องการ" ของ `skill_extraction.md:7` ด้วยเหตุผลเดียวกัน
>   role line ของ `extract_skills.py` อยู่เหมือนเดิม
> - **ชน-C**: ใบ 02 ตอบว่ารับทิศ "ระดับหลักสูตร" และ**เส้นแบ่งเขียนลง `summarize_need`
>   แล้ว** — เวอร์ชันชั้น cluster ใช้เส้นเดียวกันนี้แปลงเป็นระดับกลุ่ม ไม่ใช่ตั้งเส้นใหม่
>   (ยังไม่ลง เพราะอยู่ใน `_CLUSTERING_CONTRACT` รอลงพร้อมก้อน)
> - **ชน-B ปิดแล้วเช่นกัน (2026-09-18)**: รับลิสต์ "ห้ามสกัด" เฉพาะครึ่งที่ไม่ชน และ
>   **ตัด 5 รายการฝั่งสถาบันออก** (ปัญหา/ความท้าทายขององค์กร · เป้าหมายขององค์กร ·
>   นโยบาย · งบประมาณ · ความร่วมมือระดับองค์กร) พร้อม **"หน้าที่งานเฉพาะ"** ซึ่งใกล้กับ
>   "หน้าที่วิชาชีพ" ที่กฎ 4/5 สั่งให้รักษาไว้จนโมเดลแยกไม่ออก ·
>   `guidances/skill_extraction.md` แก้แล้วพร้อมเหตุผลในไฟล์ · prompt จริงยังไม่แตะ
>   เพราะอยู่ใน `_EXTRACTION_CONTRACT` รอลงพร้อมก้อน
> - เหลือ **ชน-D** (`{program_context}` ต้องมีเงื่อนไข — เรื่องรูปแบบ ไม่ใช่การตัดสินใจ)
>
> **งานตามเก็บที่ปิดไปด้วย**: `skill_extraction.md` เพดาน "8 ทักษะต่อ evidence" แก้หน่วย
> เป็นต่อ window แล้ว · `rationale_th` ของ **Need** ทำเสร็จแล้ว (ใบ 03 — schema + ORM +
> migration + UI 2 จุด) ส่วนเวอร์ชัน cluster/merge ยังรอก้อน

## §ชน — สี่จุดที่ต้องตัดสินก่อนแตะ prompt

### ชน-A · role line ของ extraction กลับคำตัดสินเดียวกับใบ 01

`skill_extraction.md:7` สั่งให้สกัด "ทักษะหรือสมรรถนะที่**ตลาดแรงงาน**ต้องการ"

`extract_skills.py:13-21` บันทึกไว้ว่านี่คือถ้อยคำที่ **ถอดออกไปแล้ว** และบอกเหตุผล:
evidence มี `StakeholderType` ทุกกลุ่ม ส่วน prompt ถูกบอกแค่ `requirement`/`general`
ไม่เคยรู้ว่ากำลังอ่านของใคร — มาตรฐานสภาวิชาชีพ บทสัมภาษณ์ศิษย์เก่า และวิสัยทัศน์ของ
สถาบันเอง ถูกขุดหา "สิ่งที่ตลาดแรงงานต้องการ" เหมือนกันหมด

`institutional_direction` คือเคสที่คมที่สุด เพราะกติกาข้างล่างในไฟล์เดียวกัน (กฎ 7)
สั่งให้ **ติดธง** กิจกรรมของสถาบัน ไม่ใช่ทิ้ง → framing ที่กรองมันทิ้งตั้งแต่ต้น
**ทำให้ธงนั้นไร้ความหมาย**

**มี test ตรึงไว้สองตัว**: `test_the_task_line_does_not_narrow_the_corpus_to_the_labour_market`
และ `test_the_task_line_says_the_evidence_may_come_from_any_stakeholder`

> **สิ่งที่ต้องตัดสิน**: เหมือนกับ [ใบ 01](issues/01-need-sentence-subject.md) — ถ้าตอบว่า
> "ไม่รับ `ผู้ปฏิบัติงาน`" ที่ใบ 01 คำตอบที่นี่ก็คือ "ไม่รับ role line นี้" โดยอัตโนมัติ
> ทั้งคู่คือคำถามเดียวกัน: pipeline นี้ฟังเสียงตลาดแรงงาน หรือฟังผู้มีส่วนได้ส่วนเสียทุกกลุ่ม

### ชน-B · ลิสต์ "ห้ามสกัด" ขัดกับกฎ 7 ของตัวเอง และขัดกับผลวัดจริง

`skill_extraction.md:34-47` ห้ามสกัด **งบประมาณ** · **ความร่วมมือระดับองค์กร** ·
**เป้าหมายขององค์กร** · **นโยบาย**

`skill_extraction.md:225-233` (กฎ 7 ของไฟล์เดียวกัน) สั่งให้ตั้ง
`is_graduate_capability=false` เมื่อข้อความกล่าวถึง **การจัดสรรงบประมาณ** ·
**ความร่วมมือระดับสถาบัน** · **กิจกรรมเชิงนโยบาย** — "โดย**ยังคงเก็บรายการดังกล่าวไว้**"

**สามรายการเดียวกัน อยู่ทั้งในลิสต์ "ห้ามสกัด" และในกฎ "เก็บไว้แต่ติดธง"**

โค้ดเลือกข้างไว้แล้ว และเลือกด้วยผลวัด — `extract_skills.py:62-65` เขียนไว้ตรง ๆ ว่า
ถ้อยคำปัจจุบันคัดมาจาก prototype ที่วัดได้ recall 56% ที่ false positive 3% และว่า
*"the variant that let the model drop off-scope skills itself also took 3 core skills
and 6 institutional ones with it, leaving no trace of either"*

> **สิ่งที่ต้องตัดสิน**: รับลิสต์นี้เฉพาะครึ่งที่ไม่ชน (ชื่อตำแหน่งงาน ชื่ออาชีพ
> ชื่อเครื่องมือ/ซอฟต์แวร์/เทคโนโลยีเดี่ยว กิจกรรมครั้งเดียว) และ **ตัด 4 รายการฝั่ง
> สถาบันออก** — หรือจะกลับคำตัดสินที่วัดมาแล้ว ซึ่งต้องวัดใหม่ ไม่ใช่แค่แก้ถ้อยคำ
> · ข้อเสนอของผม: รับครึ่งแรก ตัดครึ่งหลัง แล้วเขียนเหตุผลไว้ในไฟล์ guidance

### ชน-C · Skill Family ปะทะ Occupational Identity ในไฟล์เดียวกัน

`skill_clustering.md` กฎ 3 บอกให้รวม `Python / R / SQL` ขึ้นเป็น
**การวิเคราะห์และจัดการข้อมูล** ("ห้ามละเอียดเกินไป")
กฎ 4 บอกว่า `การแปลเอกสารธุรกิจ / สัญญา / กฎหมาย` **ห้าม** รวมขึ้นเป็น การสื่อสาร
(ให้เป็น การแปลเอกสารวิชาชีพ)

สองข้อนี้ไม่ได้ขัดกันโดยตรง — ข้อ 4 อนุญาตให้รวมขึ้น **หนึ่งชั้น** แต่ไม่ถึงชั้นที่
อัตลักษณ์หาย ปัญหาคือ **ไม่มีอะไรบอกว่าชั้นนั้นอยู่ตรงไหน** ซึ่งเป็นคำถามเดียวกับ
[ใบ 02](issues/02-curriculum-level-line.md) เป๊ะ ๆ เพียงแต่เกิดที่ชั้น cluster แทนชั้น Need

> **สิ่งที่ต้องตัดสิน**: ปิดใบ 02 ก่อน แล้วถ้อยคำที่นี่เขียนตามเส้นเดียวกัน — ไม่ใช่ตั้ง
> เส้นที่สองที่ชั้น cluster ซึ่งจะเถียงกับเส้นที่ชั้น Need

### ชน-D · `{program_context}` ของ clustering ต้องมีเงื่อนไข

รายละเอียดอยู่ในตารางข้อ 2 — เป็นเรื่องรูปแบบมากกว่าการตัดสินใจ แต่ต้องแก้ก่อนใช้
ไม่งั้น test แดงและโปรแกรมที่ไม่มี context เห็นปีกกาดิบ

---

## §ไม่ฟรี

### ไม่ฟรี-A · `{program_context}` ของ extraction (กฎ 4)

`build_extract_skills_prompt` **ไม่มี** พารามิเตอร์นี้ ที่ใกล้ที่สุดคือ `field_th` กับ
`program_name_th` ซึ่งอยู่ใน **user message** (`:95-99`) ไม่ใช่ system

นี่เป็นการออกแบบ ไม่ใช่ความบังเอิญ: `_extraction_contract_fingerprint` เรียก
`build_extract_skills_prompt("", "")` แล้วเอาเฉพาะ system message ไป hash
(`skill_extraction.py:193-196`) → **field กับชื่อหลักสูตรอยู่นอก fingerprint** ทุกโปรแกรม
จึงใช้ contract เดียวกัน แล้วให้ cache key รับความต่างรายโปรแกรมไปแทน
(รูปเดียวกับที่ `scope_th` ถูกจงใจใส่แบบมีเงื่อนไข — `extract_skills.py:40-44`)

**ย้าย context เข้า system = fingerprint ขยับ และขยับทุกโปรแกรมพร้อมกัน** ถ้าจะทำ
ให้ทำในก้อนเดียวกับการแก้อื่น ๆ ไม่ใช่แยกครั้ง

### ไม่ฟรี-B · `rationale_th` ของ cluster และ `merge_rationale_th`

เหมือน [ใบ 03](issues/03-need-rationale-th.md) แต่ **แพงกว่า** เพราะสองตัวนี้อยู่ใน schema
ที่ fingerprint hash โดยตรง:

- `ClusterAssignment` (`llm_clustering.py:96-99`) มี `label_th` + `member_indices`
- `MergeGroupsResponse` (`:105-106`) มี `groups` อย่างเดียว

เพิ่ม field → `model_json_schema()` เปลี่ยน → `_CLUSTERING_CONTRACT` เปลี่ยน →
clustering cache ตายทั้งตาราง

และก่อนจะทำ ต้องตอบคำถามข้างล่างนี้ให้ได้ก่อน เพราะมันฟ้องว่าปลายทางยังไม่มี

---

## §ที่ไม่มีใครอ่าน — สองจุดที่เจอระหว่างรีวิว

### `confidence` ถูกเขียนลง DB แล้วไม่ถูกอ่านที่ไหนเลย

grep ทั้ง `src/` กับ `frontend/src/` เจอ 5 จุด และทุกจุดเป็น **ฝั่งเขียน**:
`orm.py:72` (column) · `models.py:272` (field) · `extract_skills.py:91` (ขอจากโมเดล) ·
`skill_extraction.py:152` (parse) · `:597` (บันทึก) — **ไม่มี filter ไม่มี sort
ไม่มี UI ไม่มี threshold**

ผลต่อกฎ 10 ของ guidance:

- **ครึ่งที่เป็น rubric** (0.90-1.00 / 0.70-0.89 / 0.50-0.69) เปลี่ยนเฉพาะค่าที่ไม่มีใครอ่าน
  → จ่าย token ในทุก call ของ stage ที่แพงที่สุด เพื่อความละเอียดที่ไม่มีปลายทาง
- **ครึ่งที่มีผลจริง** ("ต่ำกว่า 0.50 ไม่ควรเสนอทักษะนั้น") คือการให้โมเดล **ตัดทิ้งเอง**
  ซึ่งชนกับ "ห้ามตัดทิ้งเอง" ที่ code ย้ำสองที่ (`:61`, `:68-69`) ด้วยเหตุผลที่วัดมาแล้ว

> **ข้อเสนอ**: ถ้าจะรับกฎ 10 ให้ทำ **ฝั่งอ่านก่อน** — เช่น แสดง confidence ที่ checkpoint
> หรือใช้เรียงลำดับสิ่งที่ผู้ออกแบบต้องดูก่อน แล้วค่อยขอความละเอียดจากโมเดล
> ไม่ใช่กลับกัน · ถ้าไม่มีใครจะอ่าน ให้ปล่อย rubric ทิ้ง

### `label_th` ของ cluster ถูกทิ้งทันทีที่ได้มา

`cluster_skill_names` คืน `list[list[int]]` (`llm_clustering.py:201-203`) — label หายไปที่
`validate_assignments` และ `need_combination` ก็ส่ง `("", g)` เข้าไปอีกที ชื่อกลุ่มไม่เคย
ถูกเก็บ ไม่เคยแสดง ไม่เคยกลายเป็นชื่อ Need (ชื่อ Need มาจาก `summarize_need`)

ผลต่อกฎ 5 / 8 / 9 ของ `skill_clustering.md` — ทั้งสามข้อคุมภาษาของ field ที่ไม่มีใครอ่าน

**แต่อย่าด่วนสรุปว่าให้ถอด `label_th` ออก**: การบังคับให้โมเดลตั้งชื่อกลุ่มคือการบังคับให้
มันผูกมัดกับเหตุผลของการจัดกลุ่มก่อนตอบ ซึ่งอาจทำให้ index assignment ดีขึ้นแม้ชื่อจะ
ถูกทิ้ง — เป็นสมมติฐานที่ **ทดสอบได้** (เทียบ partition ที่ได้จาก prompt ที่ขอ label กับ
ที่ไม่ขอ บนชุด TCISM เดิม) และควรทดสอบก่อน ไม่ใช่เดา

> ถ้าคำตอบคือ "label มีผลต่อคุณภาพ" → กฎ 5/8 คุ้มค่าที่จะรับ
> ถ้าคำตอบคือ "ไม่มีผล" → ทั้ง label และ rationale ควรออกจาก schema ไปพร้อมกัน
> ประหยัด token ทุก call และทำให้ fingerprint ขยับครั้งเดียว

---

## §ควรเป็นโค้ด ไม่ใช่ prompt

### กฎ 3 `Skill Normalization` — สั่งแล้วทำตามไม่ได้

กฎสั่งให้ยุบ `Data Analytics` / `Data Analysis` / `วิเคราะห์ข้อมูล` ให้เหลือชื่อมาตรฐานเดียว

**extraction ถูกเรียก 1 call ต่อ window** โมเดลใน call หนึ่งไม่เคยเห็นสิ่งที่อีก call สกัดได้
จะ normalize ข้ามคลังได้ต้องเห็นทั้งคลัง ซึ่งโครงนี้ไม่ได้ให้เห็น — กฎนี้จึงทำได้อย่างมาก
แค่ "อย่าเขียนซ้ำในคำตอบเดียวกัน" ซึ่งกฎ 2 พูดไว้แล้ว

**ของจริงอยู่ในโค้ดแล้ว**: `normalize_need_name` + `dedupe_with_bloom_max`
(`need_grouping.py`) ยุบชื่อซ้ำภายใน KSEC bucket ก่อน cluster และ
`_compute_skill_importance` ใช้ normaliser ตัวเดียวกันเพื่อให้คะแนนตกบน bucket เดียวกัน

> ถ้าอยากได้ normalization ที่ข้าม call จริง ๆ จุดที่ควรแตะคือ dedupe ไม่ใช่ prompt —
> และนั่นทับกับไอเดีย evidence-aware clustering ที่บันทึกไว้ว่า **ตัวขวางจริงคือ dedupe
> ที่ยุบชื่อซ้ำก่อน cluster**

---

## §สิ่งที่ต้องทำก่อนสามไฟล์นี้จะเป็น prompt ได้

ซ้ำกับรีวิวไฟล์แรกเกือบทั้งหมด — รูปเอกสารเหมือนกันทั้ง 4 ไฟล์:

1. **ตัดตารางท้ายไฟล์** — `skill_clustering.md:235-303` และ `cluster_merging.md:244-307`
   (`skill_extraction.md` เป็นไฟล์เดียวที่จบสะอาดที่ output schema)
2. **`{program_context}` / `{scope_th}` / `{target_clusters}` / `{target_groups}`** เป็น
   placeholder ที่ต้อง substitute และ **ต้องมีเงื่อนไข** ทุกตัว — code ปัจจุบันทำครบแล้ว
   ทั้งสี่ตัว ถ้าเอา guidance ไปทับตรง ๆ จะเสียเงื่อนไขไปหมด
3. **ไม่มีไฟล์ไหนมีช่อง designer note** — ต่างจาก `market_need_synthesis` ตรงที่ prompt
   จริงของสองตัวนี้ (`cluster_skills`, `extract_skills`) ก็ไม่มีเหมือนกัน จึงไม่เสียอะไร
4. **ภาษาของ prompt ต่างกัน** — `extract_skills` เป็นไทย แต่ `cluster_skills` /
   `merge_clusters` เป็น **อังกฤษทั้งก้อน** (ยกเว้นกฎ `label_th`) ส่วน guidance เขียนไทยหมด
   การเปลี่ยนภาษาของ prompt คือการเปลี่ยนตัวแปรที่ไม่มีใครวัด ควรแยกออกจากการเปลี่ยนกติกา
   ไม่งั้นถ้าผลแย่ลงจะไม่รู้ว่าเพราะกติกาหรือเพราะภาษา

**test ที่จะแดงถ้าเอา guidance ไปทับตรง ๆ**:
`test_the_task_line_does_not_narrow_the_corpus_to_the_labour_market` ·
`test_the_task_line_says_the_evidence_may_come_from_any_stakeholder` ·
`test_the_graduate_capability_rule_asks_for_a_flag_rather_than_a_deletion` ·
`test_no_program_context_leaves_the_prompt_unchanged` ·
`test_cluster_prompt_forbids_dropping_off_field_skills` ·
`test_the_scope_line_carries_the_sentence_that_forbids_mining_it`

---

## §ข้อเสนอ — ลำดับที่ถูกที่สุด

1. **ตัดสินใบ 01 → ได้คำตอบของ ชน-A ฟรี** (คำถามเดียวกัน)
2. **ตัดสินใบ 02 → ได้คำตอบของ ชน-C ฟรี** (คำถามเดียวกัน)
3. **ตัดสิน ชน-B** — ไม่ต้องเปิดใบใหม่ ตอบได้ในบรรทัดเดียว: รับครึ่งที่ไม่ชน ตัด 4 รายการ
   ฝั่งสถาบันออก (ข้อเสนอในรีวิวนี้) หรือจะกลับคำ ซึ่งต้องวัดใหม่
4. **ทดสอบสมมติฐาน `label_th`** ก่อนตัดสินใบ 03 — ผลของมันเปลี่ยนคำตอบของ
   กฎ 5/8/9 ทั้งชุด และเป็นการทดลองที่ไม่ต้องแก้ schema (เทียบ partition สองแบบ)
5. **ลงครั้งเดียว 4 ไฟล์** — `summarize_need` (ฟรี) + สามไฟล์นี้ (จ่าย re-extract
   + re-cluster รอบเดียว) แล้วรัน eval ชุดเดิมของ
   [ticket 07](../plo-scope-guard/issues/07-eval-protocol.md)
   เกณฑ์เดิม: **FP = 0 เป็น hard gate, recall แค่รายงาน**

**ถ้าอยากได้ของฟรีก่อนโดยไม่จ่ายอะไรเลย — ไม่มี**: `cluster_merging.md` หลักการรวมกลุ่ม
(`:25-35`, กฎ 2/3/8) คือชิ้นที่คุ้มที่สุดและไม่ชนอะไรเลย แต่มันอยู่ใน `_CLUSTERING_CONTRACT`
เหมือนกัน **ราคาต่ำสุดคือรวมทุกอย่างไว้ในการขยับ fingerprint ครั้งเดียว** นั่นคือข้อสรุปหลัก
ของรีวิวนี้

---

## §งานตามเก็บที่เจอระหว่างทาง

- `skill_extraction.md:351` เขียนเพดาน "8 ทักษะต่อ evidence" ผิดหน่วย — ของจริงคือ
  ต่อ window ควรแก้ในไฟล์ guidance ไม่ว่าจะรับกฎอื่นหรือไม่
- `confidence` ไม่มีฝั่งอ่าน — เป็นได้ทั้ง "ฟีเจอร์ที่ยังไม่ได้ต่อ" และ "field ที่ควรถอด"
  ตัดสินแล้วบันทึก ไม่ควรค้างอยู่กึ่งกลาง
- prompt ของ clustering/merging เป็นภาษาอังกฤษขณะที่ทั้ง pipeline เป็นไทย — ไม่ใช่บั๊ก
  แต่ไม่มีที่ไหนบันทึกว่าทำไม ควรมีเหตุผลเขียนไว้ หรือเปลี่ยนให้ตรงกัน
