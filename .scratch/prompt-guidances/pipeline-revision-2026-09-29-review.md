# รีวิว: ข้อเสนอปรับ pipeline 4 ขั้น (2 / 4 / 6 / 8) + ขั้นโค้ดใหม่

วันที่รีวิว: 2026-09-29 · ยังไม่แตะโค้ด · ต่อจาก
[market-need-synthesis-review.md](market-need-synthesis-review.md) และ
[three-file-review.md](three-file-review.md)

## เอกสารนี้รีวิวจาก prompt รุ่นไหน

ตาราง "เดิม → ใหม่" ในข้อเสนอ **อ้าง prompt รุ่น guidances (17 ก.ย.) ไม่ใช่โค้ดที่รันอยู่**
หลักฐานสามจุด:

| ข้อเสนอเขียนว่า "เดิม" | โค้ดจริงวันนี้ |
|---|---|
| "บังคับราว 4 กลุ่ม" | `target_clusters` มาจาก `allocate_cluster_targets` แบ่ง `MAX_CORE_PLOS` ตามสัดส่วนชื่อไม่ซ้ำ ([need_grouping.py:292](../../src/curriculum_agent/stages/need_grouping.py#L292)) · "4–12" เป็น fallback เมื่อไม่มี target ([cluster_skills.py:61](../../src/curriculum_agent/prompts/cluster_skills.py#L61)) |
| "output ไม่มี trace / ไม่มี rationale" | `rationale_th` ลงแล้ว บังคับ 20–240 ตัวอักษร + `find_vague_phrase` ([need_combination.py:88](../../src/curriculum_agent/stages/need_combination.py#L88)) |
| "ผล 5 ข้อ ไม่มีเกณฑ์เวลา → ตัด T ออก" | `time_bound_ok` default true อยู่แล้ว false เฉพาะเมื่อประโยคขัดกันเอง ([smart_agent.py:64](../../src/curriculum_agent/prompts/smart_agent.py#L64)) |

**ฉะนั้นอย่าอ่านคอลัมน์ "เดิม" เป็นสถานะปัจจุบัน** ส่วน "ใหม่" ยังอ่านได้ตามปกติ

---

## สรุปคำตัดสิน

| # | ข้อเสนอ | สถานะ | ราคา |
|---|---|---|---|
| A1 | ขั้น 4: `supporting_indices` / `not_covered_indices` + coverage | ✅ **ทำแล้ว (log อย่างเดียว)** — ผลวัดอยู่ใน [ใบ 18](../plo-scope-guard/issues/18-groups-too-large-for-one-sentence.md) | ฟรีจาก cache |
| A2 | ขั้น 6: บังคับกริยาเดียวด้วยโค้ด | ✅ **ทำแล้ว** — ดูท้ายไฟล์ | ฟรีจาก cache |
| A3 | ขั้น 6: `scope_ok` / `actor_ok` | **รับ** | ฟรี ข้อมูลมีอยู่แล้ว |
| A4 | ขั้น 3.5: Bloom จากมัธยฐานแทน max | **ต้องตัดสิน** — ขัดเหตุผลที่บันทึกไว้ | ฟรี code-only |
| A5 | temperature 0 ทุก slot | **รับ** | ฟรี |
| B1 | ขั้น 2: "จำนวนกลุ่มขึ้นกับข้อมูล" | **ปฏิเสธ — ลองแล้ว วัดแล้ว ถอยแล้ว** | — |
| B2 | ขั้น 2: `unassigned_indices` | **ปฏิเสธ** | — |
| B3 | ขั้น 1.5: filter ทิ้ง skill นอกขอบเขต | **ปฏิเสธ — ชนสถาปัตยกรรม scope guard** | — |
| C1 | ส่งความถี่เข้า prompt ขั้น 2/4 | รับได้ แต่ขั้น 2 เสีย cache ทั้งตาราง | ขั้น 4 ฟรี · ขั้น 2 แพง |
| D1 | ขั้น 8: Set-level Review | ของใหม่จริง ยังไม่มี | แพง ต้องมี checklist ภายนอก |
| D2 | ตัด `distinctive_feature_th` | ไม่ฟรี | column + UI + schema 8 จุด |
| D3 | ขั้น 9: Normalize | รับได้ แต่ต้องรัน gate ซ้ำ | เล็ก แต่มีกับดัก |

---

## A1 — `supporting_indices` / `not_covered_indices` คือคำตอบของใบ 18

ใบ 18 เปิดคำถามข้อ 5 ไว้ว่า *"ประโยคพูดถึงสมาชิกกี่ตัว เป็นคำถามที่โค้ดตอบยาก
(ไม่มี span ที่ระดับ Need)"* แล้วสรุปว่าถ้าตอบไม่ได้ ป้ายเตือนขนาดกลุ่มคือ proxy ที่ดีที่สุด

ข้อเสนอนี้ตอบคำถามนั้นตรง ๆ: **ให้โมเดลบอกเองว่าประโยคครอบสมาชิกตัวไหนบ้าง** แล้วโค้ด
คำนวณ coverage เทียบความถี่รวม · ไม่ใช่ proxy อีกต่อไป

สภาพปัจจุบันที่ทำให้มันจำเป็น — [summarize_need.py:204](../../src/curriculum_agent/prompts/summarize_need.py#L204):

```python
keywords = ", ".join(skill_names[:30])
```

ชื่อทักษะเข้า prompt เป็น **สตริงต่อกันเฉย ๆ ไม่มี index** ฉะนั้นคำตอบกลับมาอ้างสมาชิก
ไม่ได้แม้อยากอ้าง · เคส 15 สมาชิกในใบ 18 ที่ประโยคครอบ 2–3 ชื่อจึงเงียบสนิทโดยโครงสร้าง

**สิ่งที่ต้องระวังถ้าลงมือ**

1. `[:30]` ต้องหายไปหรือ index ต้องนับจากลิสต์ที่ส่งจริง ไม่งั้น mapping โกหก
   (กลุ่ม 18 ยังไม่ชน 30 แต่ไม่ใช่เหตุผลที่จะปล่อยไว้)
2. `not_covered_indices` **ไม่ใช่การลบ** — สมาชิกยังอยู่ใน `member_skill_ids` และ
   `source_evidence_ids` เหมือนเดิม ไม่งั้นชน immutable rule 2
3. เก็บที่ไหน: ถ้าแค่ log + ใส่ checkpoint artifact = ฟรี · ถ้าเก็บลง `Need` = column + migration
   · แนะนำเริ่มที่ log ก่อน เพราะยังไม่รู้ว่าเลข coverage กระจายยังไง
4. `complete_need_combination` **ไม่ผ่าน `llm_cache`** → แก้ prompt ขั้นนี้ไม่มีค่า stale-contract

**ราคาที่ไม่ฟรีจริง ๆ**: เลข 0.6 ในข้อเสนอ ("coverage < 0.6 ให้ติดธง") ไม่มีที่มา · ใบ 18
ข้อ 2 เขียนไว้เองว่า *"อย่าตั้งเลขก่อนมีเหตุผล"* → รอบแรกควรวัดการกระจายก่อน แล้วค่อยตั้งเส้น

---

## A2 — กริยาซ้อนไม่ถูกบังคับด้วยโค้ดเลย (บั๊กจริง)

immutable rule 4 เขียนว่า "หนึ่งกริยา Bloom ต่อหนึ่ง outcome สองตัวได้เฉพาะระดับติดกัน"

[smart_rules.py:30–46](../../src/curriculum_agent/stages/smart_rules.py#L30) ตรวจแค่ 3 อย่าง:

```python
class HardCriterion(StrEnum):
    S_VERB = "S_verb"        # action_verb_th ปรากฏในประโยคไหม
    M_FORBIDDEN = "M_forbidden"
    R_EVIDENCE = "R_evidence"
```

`action_verb_th in statement_th` ผ่านได้แม้ประโยคมีกริยา Bloom อีกสามตัว · ข้อเสนอรายงานว่า
PLO เดิม 6 ข้อใช้กริยาซ้อน — สอดคล้องกับสิ่งที่โค้ดตรวจ

**และเครื่องมือมีอยู่แล้ว** — ไม่ต้องใช้ PyThaiNLP ตามที่ข้อเสนอเขียน:
[bloom_verbs.py:207](../../src/curriculum_agent/stages/bloom_verbs.py#L207) `scan_statement_verbs()`
และ :238 `are_adjacent()` เขียนไว้เพื่อกฎนี้โดยตรง (docstring หัวไฟล์อ้าง rule 4 ตรงตัว)
ตอนนี้มันป้อนแค่ observation ให้ agent *พูดถึง* ปัญหา ไม่ได้ป้อน `hard_failures`

**ทำไมสำคัญกว่าที่เห็น**: `hard_failures` คือสิ่งเดียวที่ตั้ง `smart_escalated`
(CLAUDE.md: "the agent cannot pass itself") · กฎที่ไม่อยู่ใน `hard_failures` คือกฎที่ agent
เลือกไม่สนใจได้ และไม่มีอะไรข้างล่างสังเกต

**ราคาที่ต้องรู้ก่อนลงมือ**: เพิ่ม hard criterion = PLO ที่เคยผ่านจะ escalate ย้อนหลังเมื่อ
revalidate · และใบ 15 บันทึกไว้แล้วว่า repair budget ถูกเผาไปกับ soft flag จนหมด → เพิ่ม
hard check โดยไม่แก้เรื่อง budget ก่อน จะได้ `code_only` เพิ่มขึ้น ไม่ใช่ประโยคที่ดีขึ้น

---

## A3 — `scope_ok` / `actor_ok`: ข้อมูลมีอยู่แล้ว แต่ไม่ถึง validator

`ProgramCreateRequest.scope_th` มีอยู่แล้ว ([models.py:167](../../src/curriculum_agent/models.py#L167))
และถึง **extraction prompt** อยู่แล้ว ([extract_skills.py:9](../../src/curriculum_agent/prompts/extract_skills.py#L9))
— comment เขียนไว้ตรงตัวว่า *"Reaches the extraction model in the system prompt as the
yardstick for `is_field_relevant` **and nothing else**"*

ข้อเสนอนี้คือการเลิก "and nothing else" · validator ตัดสิน PLO อยู่ตอนนี้โดยไม่รู้ขอบเขตวิชาชีพเลย

เหมือนกันกับ `actor_ok`: `is_graduate_capability` มีที่ระดับ skill และ guard ทำงานที่ระดับ
Need (`SCOPE_PASS_RATIO`) · **ไม่มีอะไรตรวจที่ระดับ PLO** ประโยคที่ synthesis เขียนเป็น
พันธกิจสถาบันจาก Need ที่ผ่าน guard มาแล้ว ไม่มีตาข่ายรับ

ราคา: `SMARTCheck` อยู่ใน JSONB → เพิ่ม field ไม่ต้อง migration แต่ต้องมี default สำหรับแถวเก่า
· `soft_flags` เป็น `list[str]` โดยเจตนา (CLAUDE.md) → เพิ่มรหัสใหม่ปลอดภัย
· เพิ่มสมาชิก `SmartFindingCode` ต้องผ่าน `_uncovered_codes` drift guard ที่
[smart_vocabulary.py:119](../../src/curriculum_agent/smart_vocabulary.py#L119)

---

## A4 — Bloom มัธยฐานแทน max: ต้องตัดสิน ไม่ใช่รับเฉย ๆ

ข้อเสนอชี้อาการที่สังเกตได้จริง ("PLO เดิมเป็น 'ออกแบบ' เกือบครึ่ง") และข้อมูลที่ต้องใช้
**มีครบแล้ว** — `ExtractedSkill.bloom_level` อยู่ที่ [models.py:247](../../src/curriculum_agent/models.py#L247)
ฉะนั้นเป็นการแก้ code-only ไม่แตะ LLM ไม่แตะ cache

แต่มันขัดเหตุผลที่บันทึกไว้ที่ [need_grouping.py:372](../../src/curriculum_agent/stages/need_grouping.py#L372):

> ความสามารถเดียวกันที่สองแหล่งบรรยายด้วยระดับต่างกัน (remember vs analyze)
> สอนที่ระดับสูงกว่า — ระดับต่ำถูกครอบอยู่แล้ว

เหตุผลนั้นถูกสำหรับ **ชื่อเดียวกันจากสองแหล่ง** (`dedupe_with_bloom_max`)
แต่ `merge_bloom` ถูกเรียก**สองครั้ง** — ครั้งที่สองกับทั้งกลุ่ม ซึ่งเป็นคนละคำถาม:
กลุ่ม 15 สมาชิกมี `create` ตัวเดียว แล้วทั้งกลุ่มกลายเป็น `create`

**แยกสองที่เรียกออกจากกันคือทางที่ไม่ต้องล้มเหตุผลเดิม** — คง max ตอน dedupe ชื่อซ้ำ
เปลี่ยนเฉพาะตอนรวมกลุ่ม · ข้อเสนอไม่ได้แยกสองที่นี้ไว้

เลขในข้อเสนอ ("create ได้เฉพาะเมื่อน้ำหนักเกิน 50%") ยังไม่มีที่มา เหมือน A1

---

## A5 — temperature

`temperature=0` ตั้งไว้แล้วที่ [llm_clustering.py:170,195](../../src/curriculum_agent/stages/llm_clustering.py#L170)
และ [smart_agent.py:425](../../src/curriculum_agent/stages/smart_agent.py#L425)
· **ไม่ได้ตั้งที่ extraction, need_combination, plo_synthesis** → สาม slot นั้นใช้ default ของ provider

สำหรับงานวิจัยที่ต้องรายงานพารามิเตอร์ นี่คือช่องว่างจริง และแก้ได้ฟรี

⚠️ แต่เปลี่ยน temperature ของ extraction **ไม่ได้อยู่ใน cache key** → แถวเก่ายัง hit อยู่
ผลลัพธ์จะเป็นส่วนผสมของสองค่า จนกว่าจะ prune

---

## B1 — "จำนวนกลุ่มขึ้นกับข้อมูล": ลองแล้ว วัดแล้ว ถอยแล้ว

นี่คือ `guidances/skill_clustering.md` กฎ 6 กลับมา · [cluster_skills.py:28–38](../../src/curriculum_agent/prompts/cluster_skills.py#L28)
บันทึกผลไว้:

> Group counts on the TCISM corpus went from 11 and 15 to **16 and 48** against a
> budget of ten, which spreads `demand_score` across near-duplicates and makes the
> top-ten cut in `plo_synthesis` arbitrary.

และบันทึกต่อว่าทำไมมันย้อนแย้ง: ข้อความนั้น **จริงเกี่ยวกับโค้ด** (target เป็นเป้า ไม่ใช่เพดาน
`validate_assignments` รับทุก partition) แต่โมเดลอ่านเป็นใบอนุญาต

ข้อเสนอเขียนเหตุผลว่า "การกำหนดจำนวนตายตัวบังคับให้รวมงานที่ต่างกัน" — prompt ปัจจุบัน
ตอบข้อนี้ไว้แล้วโดยไม่ต้องปล่อยจำนวน: *"Two different competencies stay two groups even
when that leaves more groups than the target"* ([cluster_skills.py:169](../../src/curriculum_agent/prompts/cluster_skills.py#L169))

**ถ้าจะทำจริงต้องมีตัวเลขรอบใหม่มาหักตัวเลขรอบเก่า ไม่ใช่เหตุผล** — และใบ 07 ยังไม่มีฐาน variance

---

## B2 — `unassigned_indices`

ชนสองที่:

1. [cluster_skills.py:44–56](../../src/curriculum_agent/prompts/cluster_skills.py#L44) เขียนไว้ตรงข้ามตรงตัว —
   *"never drop, exclude, or set aside a skill for looking off-field — it still belongs
   to exactly one group"* พร้อมเหตุผล: ทุก skill มาจากหลักฐานที่ stakeholder ผลิตจริง
   skill "นอกสาขา" คือความต้องการที่หลักสูตรไม่ได้คาด ไม่ใช่ noise
2. [llm_clustering.py:58–92](../../src/curriculum_agent/stages/llm_clustering.py#L58) `validate_assignments`
   ซ่อม partial cover โดยทำ skill ที่ตกหล่นเป็น **singleton** — ซึ่งคือปัญหาที่ใบ 16 เพิ่งแก้ไป

ข้อเสนอเขียนว่า "unassigned ไม่ได้ถูกลบ ยังถูกรายงาน" — แต่ Need ที่ไม่มีมัน = evidence ที่มัน
อ้างหายจากทุก Need · ถ้าขนาดกลุ่มคือปัญหา (ใบ 18) การเอาสมาชิกออกจากการนับก็ไม่ได้ทำให้
กลุ่มที่เหลือซื่อสัตย์ขึ้น มันแค่ย้ายที่

---

## B3 — ขั้น 1.5 filter: ชนสถาปัตยกรรม ไม่ใช่ชนความเห็น

ข้อเสนอให้ตัด skill ที่ `is_field_relevant=false` หรือ `is_graduate_capability=false` ทิ้งก่อน cluster

ชนสามชั้น:

1. **"Requirement wins"** (CLAUDE.md) — skill ที่สภาวิชาชีพหรือวิสัยทัศน์ระบุ ยังเป็น
   `requirement` แม้โมเดลตีว่านอกสาขา · filter จะทิ้ง skill ที่ถูก mandate
2. **guard เป็นสมบัติของ Need ไม่ใช่ของ skill** — `passes_scope_axes` ใช้สัดส่วน
   (`SCOPE_PASS_RATIO = 0.5`) ของสมาชิก · ตัดทิ้งก่อน = ตัวนับเป็น 100% ทุกกลุ่มเสมอ
   `in_field_skill_count` / `graduate_capability_skill_count` บน `Need` กลายเป็นค่าตายตัว
   และ UI ที่เพิ่งเขียน (badge scope, banner, `coreOutlook`) ไม่มีอะไรจะแสดง
3. **ถอยงานทั้ง track** — `.scratch/plo-scope-guard/` ทั้งชุดคือคำตอบว่า "กรองช้า ไม่กรองเร็ว"
   และเหตุผลอยู่ใน `is_optional_group` docstring: `unclassified` ไม่ใช่ขยะ มันคือคลาสที่
   ไม่นับเข้าฝั่งไหน

**ที่กรองเร็วได้ผลจริงคือที่อื่น** — `is_graduate_capability` ถูกใช้แยกประชากรก่อน cluster
อยู่แล้ว (ใบ 16) ซึ่งเป็นการ**แบ่ง** ไม่ใช่การ**ทิ้ง**

---

## D1 — ขั้น 8 Set-level Review

ของใหม่จริง ไม่มีในระบบ · `plo_report` รายงาน แต่ไม่เสนอการกระทำระดับชุด

สิ่งที่มีให้ต่อยอดแล้ว:
- merge route มีอยู่ + บังคับกรอบ 6–10 + supersede ไม่ append (immutable rule 6)
- `cited_need_ids` derived แล้ว → "Need ที่ยังไม่ถูกใช้" ได้ฟรี
- `scope_th` มีแล้ว · `subject_benchmark_ref` เป็น field ว่างที่รอ checklist ภายนอกพอดี

สิ่งที่ยังไม่มีและเป็นราคาจริง:
- **checklist แกนวิชาชีพ** ไม่มีแหล่ง · ข้อเสนอเขียนเองว่าต้องมาจากภายนอก (EMT/PACTE/ผู้เชี่ยวชาญ)
  ไม่ใช่จากโมเดล — ถูกต้อง แต่แปลว่าต้องมี input ใหม่ทั้งชั้น
- `gap_no_evidence` ต้อง**ไม่**ให้โมเดลเติม — ตรงกับ immutable rule 2 พอดี รับได้
- วนไม่เกิน 1 รอบ: ต้องไปอยู่ในโค้ด ไม่ใช่ใน prompt

**ควรเป็นใบแยก ไม่ควรรวมกับอีก 3 ขั้น** — มันเป็น stage ใหม่ ไม่ใช่การแก้ prompt

---

## D2/D3 — สองข้อที่เขียนว่า "ตัดออก" แต่ไม่ฟรี

**`distinctive_feature_th`** อยู่ 8 จุด รวม DB column ([orm.py:120](../../src/curriculum_agent/data/orm.py#L120))
และ UI ([PloSynthesis.tsx:494](../../frontend/src/pages/PloSynthesis.tsx#L494)) · ตัด = migration + schema + UI

**ขั้น 9 Normalize** แก้ประโยคหลังผ่าน gate → ต้องรัน `hard_failures` ซ้ำ
กับดักนี้บันทึกไว้แล้วใน CLAUDE.md (`PUT` เขียนแถวที่อ่านกลับไม่ได้ ทำให้ `GET /plos/`
พังทั้งโปรแกรม) · "แค่ปรับเครื่องหมาย" ไม่ยกเว้นกฎนี้

---

## ราคา cache (ตัดสินก่อนเลือกลำดับ)

| ขั้น | prompt builder | อยู่ใน contract hash? |
|---|---|---|
| 1 Extraction | `extract_skills.py` | **ใช่** `_EXTRACTION_CONTRACT` — แพงที่สุด 1 call/window/evidence |
| 2 Clustering | `cluster_skills.py` | **ใช่** `_CLUSTERING_CONTRACT` |
| 3 Merge | `build_merge_clusters_prompt` | **ใช่** contract เดียวกัน |
| 4 Need Synthesis | `summarize_need.py` | **ไม่** — `complete_need_combination` ไม่ผ่าน `llm_cache` |
| 6 SMART | `smart_agent.py` | **ไม่** |

→ A1, A2, A3, A4, A5 ทั้งชุด **ไม่มีค่า stale-contract** · B1, B2, C1(ขั้น 2) มี

---

## ลำดับที่แนะนำ

1. **A2** (กริยาซ้อน) — บั๊กที่ยืนยันได้ ฟังก์ชันพร้อม แต่ดู repair budget ของใบ 15 ก่อน
2. **A1** (coverage) — ตอบใบ 18 ข้อ 5 · รอบแรก**วัดอย่างเดียว ไม่ตั้งธง** แล้วเอาการกระจายมาตั้งเลข
3. **A3** (scope/actor) — ข้อมูลพร้อม ตาข่ายที่ยังว่างอยู่จริง
4. **A5** (temperature) — ฟรี แต่ prune cache ด้วย
5. **A4** (Bloom) — ต้องตัดสินเรื่องแยกสองที่เรียกก่อน
6. **D1** (ขั้น 8) — ใบแยก ต้องมี checklist ภายนอกก่อน

ยังไม่ทำ: B1 B2 B3 D2

⚠️ [ใบ 07](../plo-scope-guard/issues/07-eval-protocol.md) ยังไม่มีฐาน variance — ข้อไหนที่ต้องเทียบ
"ก่อน/หลัง" ด้วยตัวเลข (A4 โดยเฉพาะ) ยังตัดสินด้วยรันเดียวไม่ได้

---

## บันทึกผล A2 (ลงมือแล้ว 2026-09-29)

**แก้ที่ผมเขียนผิดในรีวิวรอบแรก**: ผมเขียนว่า "ฟรี ฟังก์ชันมีอยู่แล้ว" โดยไม่ได้อ่านหัวไฟล์
`bloom_verbs.py` ซึ่ง**ห้ามต่อเข้า `hard_failures` ไว้โดยเจตนา** พร้อมเหตุผล (กริยาที่ตารางลืม
จะ hard-fail ผิด) · เงื่อนไขที่ gate ตั้งไว้คือ "จนกว่าคำศัพท์ได้เห็นโปรแกรมจริง" → วัดก่อน

### สิ่งที่วัดได้จาก PLO ที่เก็บจริง 9 ข้อ

`action_verb_th` **ไม่อยู่ใน**กริยาที่สแกนเจอ 6 ใน 9 ข้อ เพราะ field เองเป็นวลีหลายกริยา

| ประกาศไว้ | สแกนได้ | ระดับ |
|---|---|---|
| `ออกแบบและดำเนินการ` | ออกแบบ, ดำเนินการ | create + apply |
| `ออกแบบและดำเนินการตรวจสอบ` | ออกแบบ, ดำเนินการ, ตรวจสอบ | 3 ตัว |
| `ตีความและอธิบาย` | ตีความ, อธิบาย | understand + understand |
| `ประพฤติตน` | (ไม่มี) | ตารางไม่รู้จัก |

→ **กฎ 4 พังที่ field ที่ประกาศ ไม่ใช่ที่ประโยค** · `action_verb_th in statement_th` ผ่านหมด
เพราะ synthesis เขียนทั้งวลีลงประโยค

### ข้อกังวลของหัวไฟล์ไม่ตรงกับโหมดล้มที่วัดได้

ไม่มี PLO สักข้อที่ fail เพราะตารางลืมกริยา · โหมดล้มจริงคือ **scanner นับกริยาในอนุประโยครอง**
(`โดยใช้...` `เพื่อสร้าง...` นาม `แนวปฏิบัติ`) → สแกนประโยค flag 6/9 ในนั้น **4 ข้อถูกต้องอยู่แล้ว**

สแกน `action_verb_th` แทน → flag 3/9 **ถูกทุกข้อ ไม่มี false positive**

### กฎที่ลง

`smart_rules.declares_too_many_verbs` — สแกนเฉพาะวลีที่ประกาศ · 0 กริยา (ตารางไม่รู้จัก) **ผ่าน** ·
1 ผ่าน · 2 ผ่านเมื่อ**มีคู่ระดับใดคู่หนึ่ง**ติดกัน (ไม่ใช่ทุกคู่ เพราะ `levels_for_verb` คืน list
ตรงที่ rubric บอกว่าวัตถุเป็นตัวตัดสินระดับ) · ≥3 ตก

แตะ 7 ไฟล์: `smart_rules.py` · `smart_vocabulary.py` (code + `HARD_CODES` + label) ·
`bloom_verbs.py` (หัวไฟล์) · `stage_3_plo.py` (บอก synthesis ว่า `action_verb_th` ต้องเป็นกริยาเดียว
ไม่งั้น repair วนทุกข้อ) · `smart_agent.py` prompt · `frontend/src/constants/smart.ts` (mirror) ·
`CLAUDE.md` (rule 4 + pitfall)

ตรวจ: 892 tests · ruff/format/mypy สะอาด · `dump_prompts --check` up to date ·
frontend lint + tsc สะอาด · **mutation 7/7 แดง**

⚠️ PLO ที่เก็บอยู่ 3 ข้อจะ escalate เมื่อ revalidate — ตั้งใจ ไม่แตะแถวเก่า
