# Map: PLO synthesis ที่ไม่หลุด scope ของหลักสูตร

Label: `wayfinder:map`

## Destination

spec เดียวที่ `.scratch/plo-scope-guard/spec.md` พร้อมส่งไปลงมือ — ปิดช่องที่ `plo_synthesis`
หยิบ Need ที่ไม่ควรเป็น PLO ของหลักสูตรนี้ขึ้นมาเป็น PLO เพราะ demand_score สูง

**สองแกน** (แกนที่สองเพิ่มหลัง [ticket 02](issues/02-scope-statement-shape.md) —
หลักฐานจากหลักสูตรจริงบอกว่าแกนแรกจับอาการที่ใหญ่ที่สุดไม่ได้):

1. **อยู่ในสาขาไหม** — Need ที่ตลาดต้องการจริงแต่อยู่นอกขอบเขตของหลักสูตรนี้
2. **บัณฑิตทำได้ไหม** — Need ที่เป็นกิจกรรมของสถาบัน/หลักสูตร/อาจารย์ ไม่ใช่สมรรถนะของ
   คนที่เรียนจบ ("บริหารทรัพยากรอย่างคุ้มค่า", "รับรองอัตราการได้งานทำ")

สองแกนไม่ทับกัน: "การสร้างเครือข่ายความร่วมมือระดับสากล" อยู่ในสาขาของวิทยาลัยนานาชาติเต็ม ๆ
แต่ไม่ใช่สิ่งที่บัณฑิตคนหนึ่งทำ

จบ map เมื่อไม่เหลือการตัดสินใจค้าง: รูปของ scope statement, จุดที่ทั้งสองธงถูกอ่าน,
วิธีที่สองแกนประกอบกันตอนเลือก, พฤติกรรมตอนกรองแล้วเหลือน้อยกว่า MIN_NEEDS,
สิ่งที่ designer เห็นที่ checkpoint, และวิธีพิสูจน์ว่าได้ผล — ทั้งหมดตอบแล้วเขียนลง spec

## Notes

**Domain**: Thai higher-education curriculum design, MHESI (อว.) standards, OBE.
`.claude/skills/curriculum-design-agent/` เป็น canonical source ของกฎ OBE / prompt template /
data schema — ทุก session ที่แตะเนื้อหา PLO ต้องอ่านก่อน. `CLAUDE.md` เป็นคู่มือปฏิบัติของ repo
(path, command, convention) และมี **Immutable rules** ที่ทุก ticket ต้องไม่ชน โดยเฉพาะ
rule 2 (traceability), rule 6 (6-10 PLO + Need ที่ไม่ถูกใช้ต้องเก็บไว้และมองเห็นได้),
rule 7 (HITL ทุก stage boundary)

**Skills ที่ทุก session ควรเรียก**: `curriculum-design-agent` เสมอ; แล้ว `grilling` + `domain-modeling`
ถ้า ticket ไม่ได้ระบุ type อื่น

**Standing preferences**:
- ตอบภาษาไทย, pordee mode (กระชับ, คง technical term เป็นอังกฤษ)
- **Plan, don't do** — map นี้ผลิต decision ไม่ใช่ code. ปลายทางคือ spec ที่คนอื่นเอาไปทำ
- Tracker: local markdown (`.scratch/plo-scope-guard/`), ยังไม่ได้รัน `/setup-matt-pocock-skills`

**สภาพโค้ดตอนตั้ง map** (2026-09-04, main @ a5823b9):
- `ExtractedSkill.is_field_relevant` มีอยู่แล้ว (`models.py:244`, `orm.py:65`) ตัดสินโดย extraction model
- ธงนั้น **ตายที่ need_combination** — clustering ไม่ดู classification เลย และ `cluster_skills.py:36`
  สั่งชัดว่า off-field skill ยังต้องอยู่ในกลุ่มใดกลุ่มหนึ่ง
- `demand_score` = mandate + frequency ล้วน ไม่มีเทอม field-relevance (`stages/demand.py`)
- `Need.classification_coverage` วัด off-field แทนไม่ได้ เพราะกฎ "requirement wins" ทับ
  (`skill_extraction.py:215`) — skill นอกสาขาที่สภาวิชาชีพพูดถึงออกมาเป็น `requirement`
- `_EXTRACTION_CONTRACT` = sha256(schema + **system prompt**); system prompt static ล้วน,
  `field_th`/`program_name_th` อยู่ใน **user header แบบมีเงื่อนไข** และอยู่ใน cache key

**ชุดทดสอบประจำ map นี้** (ตั้งขึ้นที่ ticket 02, ทุก prototype ต่อจากนี้ใช้ชุดเดียวกัน
ไม่งั้นตัวเลขเทียบกันไม่ได้):
- evidence: `Data/ความต้องการของผู้มีส่วนได้ส่วนเสีย การแป.docx` → 14 evidence item
- เฉลย: `Data/Needs_to_PLO_TCISM.xlsx` (13 Need → 4 theme → 4 PLO, งานของมนุษย์)
- หลักสูตร: ศิลปศาสตรบัณฑิต สาขาการแปลภาษาจีนและภาษาไทย (นานาชาติ), TCISM, ม.หอการค้าไทย
- CORE (ติดธง = false positive): ev06-09, ev14 · NOISE (ติดธง = true positive): ev10, ev11
- model: `gemma4:31b-cloud` ผ่าน ollama cloud (`EXTRACTION_PROVIDER=ollama`).
  **OpenRouter หมดเครดิต** — 402 `in_flight_budget_exhausted`; และ llama-3.3-70b เขียนไทย
  เพี้ยน (อักษรซีริลลิกปนในชื่อทักษะ)

**สองข้อที่หลักฐานจริงขัดกับ immutable rules — รายงานไว้ ไม่ใช่ของที่ map นี้แก้:**
1. เฉลยมนุษย์มี **4 PLO** ส่วน rule 6 กำหนด 6-10 และ `MIN_NEEDS = 6`
2. theme ของมนุษย์ **ตัดข้าม KSEC** (A ผสม K+S, C ผสม K+E) ส่วนกฎห้าม cluster ข้าม bucket
   → `need_combination` ผลิต theme แบบนั้นไม่ได้เชิงโครงสร้าง

ถ้าจะเอาสองข้อนี้ ต้องเป็น map ใหม่หรือการทบทวน rule ไม่ใช่ ticket ในนี้

## Decisions so far

<!-- one line per closed ticket: gist + link -->

- [01 — มาตรฐานไทยนิยาม "ขอบเขตสาขา" ไว้แล้วหรือยัง](issues/01-scope-boundary-standards.md):
  ตัวเพาะที่พึ่งได้เหลือ **ISCED-F detailed field (4 หลัก) แหล่งเดียว** — มคอ.1 ถูกยกเลิก
  ทั้งชุดโดยกฎกระทรวง 2565 ข้อ ๒ และไม่เคยเขียนฝั่งลบเลย, AUN-QA ไม่มีข้อความเรื่องขอบเขต
  (ห้ามอ้างใน spec). **ฝั่ง "ไม่รวมอะไร" ไม่มีมาตรฐานไหนเพาะเป็นภาษาไทยได้** ซึ่งเป็นฝั่งที่
  map นี้ต้องการที่สุด
- [08 — เอาตัวบท "มาตรฐานคุณวุฒิในสาขาวิชา" ชุดหลัง 2565 มาให้อ่าน](issues/08-fetch-post-2565-standards.md):
  ตัวบทจริง (แพทยศาสตร์ ๒๕๖๖ + เทคนิคการแพทย์ ๒๕๖๗, เก็บที่ `sources/`) **ไม่มีหัวข้อ
  "ลักษณะของสาขา"** และฝั่งลบยังศูนย์ — แต่หัวข้อ "๑. ด้านความรู้" เป็น seed ฝั่งบวก
  **ภาษาไทยที่ยังบังคับใช้** ดีกว่า ISCED-F แลกกับที่ครอบเฉพาะสาขาที่มีสภาวิชาชีพ.
  ของแถม: 4 ด้านของประกาศตรงกับ KSEC หนึ่งต่อหนึ่ง
- [02 — scope statement เขียนยังไงถึงใช้ได้จริง](issues/02-scope-statement-shape.md):
  **free text ช่องเดียว ฝั่งบวกล้วน แจกแจงเป็นรายการ** — prototype บนหลักสูตรจริงพบว่า
  รายการ "ไม่รวมถึง" **ทำให้แย่ลง** (0/8 เทียบ control 3/9 และเป็น variant เดียวที่ทำ
  false positive) ส่วนที่เขียนกว้างหรือลอย ๆ ก็แย่กว่าไม่มี. เฉพาะแบบแคบ+แจกแจงที่ช่วย
  (4/8) แต่เพดานอยู่แค่ครึ่งเดียว → scope statement เป็น guard เดี่ยวไม่ได้.
  ผลเต็ม: [`research/02-prototype-findings.md`](research/02-prototype-findings.md)
- [09 — prompt แยก "สมรรถนะบัณฑิต" ออกจาก "กิจกรรมของสถาบัน"](issues/09-graduate-capability-prompt.md):
  แกนที่สองเป็น **ธงในสคีมา `is_graduate_capability`** (5/9 = 56%, false positive 1) —
  ไม่ใช่กติกาที่ตัดทิ้งเงียบ (ลด CORE และ institutional ไปด้วยโดยไม่มีร่องรอย) และไม่ใช่
  การเขียนใหม่ที่ชั้นสกัด (แต่งเติมจนชื่อทักษะไม่ตรง `evidence_span_th` = ชน rule 2;
  ที่ทางของการเขียนใหม่คือ `summarize_need`).
  **และเปิดบั๊ก: scope statement ใน user header ถูกอ่านเป็นหลักฐาน** — ผลิตทักษะที่ลอก
  ข้อความ scope คำต่อคำ 11 รายการบน evidence ที่ไม่มีคำเหล่านั้นอยู่เลย.
  ผลเต็ม: [`research/09-prototype-findings.md`](research/09-prototype-findings.md)

- [04 — ธงสองแกนขึ้นถึงระดับ Need](issues/04-two-axis-flags-on-need.md) (รวม ticket 10 เข้ามา):
  **bool แยกสองตัวบน `ExtractedSkill`, counter สองตัว store บน `Need`, `@property` = `count > 0`
  เป็นกฎ any ที่เดียว**. สองแกนอยู่**นอก `classification`** ทั้งคู่ เพราะ `requirement wins`
  จะทับกฎใหม่ตรงจุดที่ต้องการมันที่สุด (ทักษะจากวิสัยทัศน์สถาบันเป็น `requirement` เสมอ).
  ไม่ใช้ majority — recall แค่ 56% การตัดแรงคือตัดของถูกทิ้ง. migration ต้อง backfill
  `jsonb_array_length(member_skill_ids)` ไม่ใช่ default 0. **ห้ามตัดที่ระดับ stakeholder**
  (เฉลยมนุษย์เก็บ Need ของผู้บริหาร/อาจารย์ไว้ครบ ตัดแค่เนื้อหาบางส่วน)

- [05 — selection filter ใน plo_synthesis](issues/05-synthesis-selection-filter.md):
  **กรองก่อน `synthesis_order` และก่อน `MAX_CORE_PLOS`** (กรองหลังเพดานจะได้ 7 PLO
  ทั้งที่มี Need ในขอบเขตรออยู่ท้ายแถว) ผ่าน predicate เดียว `is_in_scope(need)` ที่
  `need_grouping.py` ข้าง `MIN_NEEDS`/`MAX_CORE_PLOS` — เนื้อในเป็นของ ticket 11.
  **ไม่เว้นเลข** เพราะช่องว่างแปลว่า "ร่างไม่สำเร็จ" อยู่แล้ว. warning `MIN_NEEDS` เดิม
  ต้องบอกสาเหตุในบรรทัดเดียวกัน. merge route **ไม่กรองโดยเจตนา** (ทาง override
  ทางเดียว) log อย่างเดียว ไม่แตะ floor check. **ห้ามเพิ่ม branch "โปรแกรมนี้มี scope
  statement ไหม"** — default ของ ticket 04 ทำให้ predicate เป็น no-op เอง

- [12 — noise ที่สองแกนพลาด ทับกันแค่ไหน](issues/12-axis-overlap.md):
  **ทับกัน 100%** — ไม่มีทักษะตัวใดติดธงแกนเดียว `and`/`or` ให้ตัวเลขเท่ากันเป๊ะ
  (NOISE 5/9, CORE 1/29). และแกนที่สอง**ไม่ได้เพิ่มมิติ มันไปขยับธงสาขา**:
  เพิ่มแค่ช่อง `is_graduate_capability` โดยไม่มี scope statement แล้วธงสาขาขยับเอง
  จาก 3/9 เป็น 5/9 — โมเดลเข้าใจคำถามเดิมคมขึ้นแล้วตอบสองช่องด้วยคำตัดสินเดียว.
  วัดจากข้อมูลที่เก็บไว้แล้ว ไม่มีการเรียก LLM ใหม่.
  ผลเต็ม: [`research/12-overlap-findings.md`](research/12-overlap-findings.md)

- [11 — selection ใช้สองแกนร่วมกันยังไง](issues/11-two-axis-selection.md):
  **เก็บสองธงแยก ผ่านต้องผ่านทั้งคู่** — ไม่ยุบเป็นแกนเดียวเพราะช่องที่สองดันธงสาขา
  จาก 3/9 เป็น 5/9 (ticket 12) **มีมูลค่าแม้ตอบซ้ำ** ส่วน "ธงเดียวนิยามรวม" ยังไม่เคยวัด
  ยุบตอนนี้คือเดา. `is_in_scope()` คืน `bool` เหตุผลมาจาก counter ของ ticket 04 ฟรี ๆ.
  merge route **ไม่กันทั้งสองแกน** (ธง grad-OFF ไม่เคยมาเดี่ยว 0/38 + SMART gate
  จับ PLO ผิดรูปอยู่แล้ว + recall 56% ไม่พอจะ 422). warning บรรทัดเดียวแยกตัวเลข
  สองแกน เพราะวันที่สองตัวไม่เท่ากันคือวันที่สองแกนแยกกันจริง

- [13 — scope statement ใน system prompt ยังปนเป็นหลักฐานไหม](issues/13-scope-position.md):
  **ย้ายแล้วหายสนิท ไม่แลกอะไร** — ชื่อลอกวลีจาก scope 8 → **0** ขณะที่ recall (4/8)
  และ false positive (1) เท่ากันทั้งสองตำแหน่ง. และรูปของบั๊กอันตรายกว่าที่คิด:
  span **คัดลอกตรงตัวจริงแต่คัดจาก scope ไม่ใช่จากหลักฐาน** — วันที่ scope บังเอิญมีวลี
  ตรงกับหลักฐาน `is_grounded()` จะปล่อยผ่าน.
  ผลเต็ม: [`research/13-position-findings.md`](research/13-position-findings.md)
- [03 — scope statement เข้า extract prompt](issues/03-extraction-prompt-and-cache.md):
  **system prompt แบบมีเงื่อนไข** + `scope_th` เข้า cache key **แบบไม่มีเงื่อนไข**
  (กลับด้านจากที่ตั้งไว้ เพราะไม่มี key เดิมให้รักษาแล้ว) และ **ต้องไม่เข้า
  `_extraction_contract_fingerprint()`** — scope เป็น per-program input ไม่ใช่สัญญาเรื่อง
  รูปร่าง ถ้าเข้าไป `prune_cache` จะรายงาน `stale-contract` มั่วทั้งตาราง.
  **re-extract ครั้งเดียวจบ** ธงใหม่+scope+กติกาไปพร้อมกัน ไม่ prune ก่อน deploy
  (irreversible ก่อนจุดที่ยังถอยได้) ไม่เตือนใน UI

- [07 — eval protocol: พิสูจน์ยังไงว่า PLO เลิกหลุดสาขา](issues/07-eval-protocol.md):
  **TCISM ของจริง + เคสสังเคราะห์** (ยัด job posting สาขาอื่นเข้าคลัง — เฉลยรู้แน่นอน
  โดยการก่อสร้าง ไม่ต้องมี rubric หรือ LLM judge) ยัดทั้ง `employer` และ
  `professional_council` เพื่อวัดว่า guard กรองสมรรถนะที่สภาวิชาชีพสั่งไปกี่ใบ
  (**แก้หลังรันจริง**: ใบนี้เคยเขียนว่า "requirement wins ปกป้องมันจริง" — ไม่จริง
  `classification` ไม่เคยไปถึง `is_in_scope`).
  **วัดที่ระดับ Need ไม่ใช่ skill** เพราะกฎ any ทำให้ตัวเลข skill หลอก.
  เกณฑ์ **asymmetric: FP = 0 เป็น hard gate, recall แค่รายงาน** —
  Need ในสาขาที่ถูกกรองผิดคือ PLO ที่หายไปโดยไม่มีใครรู้ ส่วน Need นอกสาขาที่หลุดมา
  designer ลบได้ที่ checkpoint. **สอง baseline** (`B1−B0` = ช่องธงที่สองให้อะไร,
  `ผล−B1` = scope ให้อะไร). **fallback ประกาศล่วงหน้า: ปิดสวิตช์กรอง เหลือติดธงที่
  checkpoint**. รัน manual ไม่ใช่ CI

- [06 — checkpoint กับ report โชว์ Need ที่ถูกกันยังไง](issues/06-checkpoint-two-buckets.md):
  **ก้อนเดียว ป้ายบอกเหตุผลรายรายการ** ไม่ใช่สามก้อนอย่างที่ตกลงไว้ตอนเปิดใบ —
  ticket 12 วัดทีหลังว่าธงสองแกนทับกันเกือบทุกใบ หัวข้อแยกจะลิสต์ Need ใบเดียวกันซ้ำสองที่.
  รายละเอียด (ชื่อทักษะ + span) อยู่หลังการกด เพราะการสแกนใช้ป้ายพอ แต่การตัดสินว่า
  โมเดลอ่านผิดไหมต้องเห็นทักษะ. บล็อก "ต้องรันอะไรใหม่" หนึ่งครั้งต่อหน้า ไม่ใช่ต่อแถว.
  **ป้ายสภาวิชาชีพมี** และใช้ `source_stakeholder_types` ไม่ใช่ `classification_coverage`
  (อย่างหลังรวมวิสัยทัศน์สถาบันเข้ามาด้วย ทำให้ป้ายโกหก).
  ต่อยอด `UnusedNeeds` เดิม **ไม่ต้องแก้ API เลย** — `Need` และ `ExtractedSkill` เต็ม
  ถูกส่งอยู่แล้ว. [mockup](checkpoint-mockup.html)

- **`requirement` ไม่ได้รับการยกเว้นจาก guard** (ตัดสินหลังปิดทุกใบ จากผลรัน eval จริง):
  "requirement wins" ตัดสินว่าทักษะเป็นข้อกำหนดไหม ซึ่งคนละคำถามกับว่าสมรรถนะนั้น
  เป็นของหลักสูตรนี้ไหม — สภาวิชาชีพสั่งสิ่งที่หลักสูตรนี้ไม่ใช่ที่ทางที่จะสอนได้.
  แทนที่จะยกเว้นในโค้ด: **ติดป้ายที่ report** ให้เห็นก่อนอนุมัติ และ **merge route ไม่กัน**
  จึงหยิบกลับได้. โค้ดไม่เปลี่ยน เพิ่มแค่คอมเมนต์ว่าเป็นเจตนา

- **กฎ any → สัดส่วน `SCOPE_PASS_RATIO = 0.5`** (แก้หลังรัน pipeline เต็มครั้งแรก):
  clustering รวมทักษะข้าม evidence ทำให้ Need รอดกฎ any ตราบใดที่มีสมาชิกหลุดธงตัวเดียว —
  ของจริงคือ Need ที่สมาชิกติดธง 6 ใน 7 กลายเป็น core PLO อันดับสอง. กวาดค่าบน Need
  สิบใบ: any พลาด 2 ใน 3 ใบที่ควรกรอง ส่วน 0.34-0.60 กรองครบและไม่กรองผิด.
  แลกกับ core PLO ลดจาก 3 เหลือ 2 — PLO ที่หายคือ PLO ที่ไม่ควรมีตั้งแต่แรก.
  ผลเต็มพร้อมข้อจำกัด: [`research/14-full-pipeline-run.md`](research/14-full-pipeline-run.md)

## Not yet specified


- **หลักสูตรสหวิทยาการ**: "ในสาขา" แปลว่าอะไรเมื่อหลักสูตรมีสองขา (เช่น วิศวกรรมชีวการแพทย์,
  ธุรกิจดิจิทัล). scope statement เป็น free text อาจรับมือได้เอง หรืออาจต้องกฎแยก — ยังตอบไม่ได้
  จนกว่าจะเห็นว่า designer เขียนอะไรจริง (ticket 02).
  **ticket 01 ไม่ปิดช่องนี้และทำให้แคบลงด้วย**: ISCED-F ยุบหลักสูตรสหวิทยาการเหลือรหัส `0x88`
  ตามเวลาเรียนส่วนใหญ่ ไม่ได้บรรยายขอบเขตสองขา และ มคอ.1 ก็นิยามทีละสาขา — ไม่มีมาตรฐานไหน
  พูดถึงเคสนี้เลย
- **"ธงเดียวนิยามรวมสองเกณฑ์" ให้ผลเท่าไร**: ticket 11 เลือกเก็บสองธงเพราะช่องที่สอง
  ดัน recall ขึ้นจริง แต่ยังไม่มีใครวัดว่าธงเดียวที่มีนิยามครอบทั้งสองเกณฑ์จะให้ 5/9
  เท่าเดิมหรือกลับไป 3/9. ถ้า [ticket 07](issues/07-eval-protocol.md) วัดบนชุดใหญ่แล้ว
  ยังทับกัน 100% ข้อนี้จะกลายเป็นคำถามที่ต้องตอบก่อนจะเก็บสองคอลัมน์ไว้ถาวร
- **เขียนใหม่ที่ `summarize_need`** → เปิดเป็น
  [ticket 14](issues/14-summarize-need-scope-flags.md) แล้ว (grilling, frontier):
  ticket 09 ตัดการเขียนใหม่ออกจากชั้นสกัด (ทำลาย span) แต่ยืนยันว่ามนุษย์เขียนใหม่จริงที่
  ระดับ Need. `summarize_need` เห็นแต่ `skill_names` และ `_Group` เก็บมาเฉพาะ counter
  สองตัว ไม่ใช่ธงรายตัว ทั้งที่ `_build_groups` ถือ `ExtractedSkill` รายตัวอยู่แล้ว.
  สามรูปที่ใบนั้นต้องเลือก: ข้ามทักษะที่ติดธง / บอกโมเดลแล้วให้กันเอง / เขียนใหม่แบบ T3.
  ข้อที่ต้องกดก่อนตอบ: `SCOPE_PASS_RATIO` กรองใบที่ติดธงเกินครึ่งไปแล้ว เหลือให้ช่วยกี่ใบ,
  การเขียนจาก subset ทำให้ `source_evidence_ids` อ้างหลักฐานที่ประโยคไม่พูดถึง,
  และ (ค) เดินเข้าหาเส้น "Need ต้องไม่เป็น PLO เสร็จรูป". **ต้นทุน cache = ศูนย์** —
  prompt นี้ไม่ผ่าน `llm_cache` ต่างจากใบ 03
- **มคอ.2 exporter ต้องรายงาน Need ที่ถูกกันไหม**: ticket 06 ตอบเฉพาะ**หน้าจอที่ designer
  อ่านเอง** ส่วนเอกสารที่ส่ง MHESI เป็นคนละคำถามและคนละผู้อ่าน — `exporters/` ไม่ถูกแตะ
  ในงานรอบนี้ ต้องเป็นใบใหม่

## Out of scope

- **ปุ่ม override ดึง Need นอกสาขากลับมาเป็น PLO** — `POST /plos/from-needs` ไม่กัน Need นอกสาขา
  โดยเจตนา (ดู ticket 05) เลยเป็นทาง override อยู่แล้ว ไม่ต้องสร้างของใหม่
- **อาการหลุด scope แบบอื่น** — กว้างเกินหลักสูตร / ผิดระดับปริญญา / generic ใช้ได้ทุกหลักสูตร.
  map นี้จับเฉพาะ "นอกสาขาเลย" ซึ่งเป็นอาการเดียวที่โค้ดมีสัญญาณค้างอยู่แล้ว
- **แก้ clustering prompt / summarize prompt** — scope statement ไม่เข้า
  `build_program_context_th`. ทำแล้วล้าง clustering cache ทั้งหมด และส่งสัญญาณขัดกับ
  `cluster_skills.py:36` ที่สั่งให้ off-field skill เข้ากลุ่ม
- **เทอม field-relevance ใน `demand_score`** — ปนสัญญาณ "ตลาดต้องการแค่ไหน" กับ
  "อยู่ในสาขาไหม" แล้วอ่านคะแนนไม่ออกทั้งคู่
- **เกณฑ์ scope ใน SMART gate** — ถึงจุดนั้นจ่ายค่า synthesis ไปแล้ว และ escalate PLO นอกสาขา
  ให้คนซ่อม คือให้คนซ่อมของที่ไม่ควรเกิด
