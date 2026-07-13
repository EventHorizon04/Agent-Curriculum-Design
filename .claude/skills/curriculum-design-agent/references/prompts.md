# Prompt Templates Reference

LLM prompts for each agent stage. When building or modifying a prompt, start from the relevant template here. If a needed prompt doesn't exist, add it to this file rather than scattering prompts across the codebase.

All prompts assume:
- LLM is Thai-capable (Typhoon, Qwen) or proprietary (Claude, GPT-4o)
- Output is structured via Instructor → Pydantic
- Light tasks → small model, heavy reasoning → large model

## Pattern: prompts have three sections

```
[ROLE & CONTEXT]
You are an expert in Thai higher-education curriculum design under the
OBE framework. ...

[TASK]
Given the following <input>, produce <output> that satisfies <criteria>.

[RULES]
- Use Thai for all student-facing statements
- Follow Bloom Taxonomy
- Forbidden words: ...
- Output schema: <Pydantic model>
```

Always include rules. The model will drift toward generic English-academic style without them.

---

## Stage 2: Stakeholder needs classification

**Purpose:** classify each piece of stakeholder evidence as need / requirement / want.

**Model:** light (Typhoon 8B / Qwen 7B)

```
คุณเป็นผู้เชี่ยวชาญด้านการพัฒนาหลักสูตรระดับอุดมศึกษาตามแนวทาง OBE

งาน: จากข้อความที่ผู้มีส่วนได้ส่วนเสีย (stakeholder) ระบุไว้เกี่ยวกับ
ความต้องการของผู้สำเร็จการศึกษาในสาขา {field} ระดับ {degree_level}
ให้จำแนกข้อความว่าเป็นประเภทใด:

- "need" = ความต้องการที่จำเป็น (ผู้สำเร็จการศึกษาทุกคนต้องมี) ต่อตลาดแรงงาน และ/หรือตามความต้องการของผู้ประกอบการ 
- "requirement" = ข้อกำหนดที่บังคับโดยมาตรฐานวิชาชีพ กฎหมาย มาตรฐานกระทรวง มหาวิทยาลัย และสภาวิชาชีพ
- "want" = ความต้องการเพิ่มเติม (มีดีกว่า แต่ไม่จำเป็นทุกคน)

ข้อความ:
{evidence_text}

แหล่งที่มา: {stakeholder_type} — {source_name}

เกณฑ์การตัดสิน:
- ถ้าเป็นทักษะที่กล่าวถึงซ้ำในหลายแหล่ง และมีผลโดยตรงกับความสามารถในการทำงาน
  หลักของวิชาชีพ → "need"
- ถ้าเป็นข้อกำหนดของสภาวิชาชีพหรือมาตรฐานบังคับ → "requirement"
- ถ้าเป็นทักษะที่นายจ้างบางรายต้องการเพิ่ม หรือเป็นความสามารถพิเศษ → "want"

ส่งคำตอบเป็น JSON ตาม schema ที่กำหนด พร้อมเหตุผลสั้นๆ ว่าทำไมจัดประเภทนี้
```

Pair with `EvidenceClassification` Pydantic model.

---

## Stage 3: Skill extraction from raw evidence

**Purpose:** extract structured skill mentions from one piece of evidence.

**Model:** light to medium (Typhoon 8B / Qwen 14B)

```
คุณเป็นผู้เชี่ยวชาญในการวิเคราะห์ทักษะวิชาชีพในสาขา {field}

งาน: จากข้อความต่อไปนี้ ให้สกัดทักษะ (skill) ที่ระบุชัดเจน
หรือสามารถอนุมานได้อย่างมีเหตุผล

ข้อความ:
{raw_text}

สำหรับแต่ละทักษะที่สกัดได้ ให้ระบุ:
1. ชื่อทักษะภาษาไทยที่ใช้กันทั่วไปในวงวิชาการ
2. ประเภท: knowledge / psychomotor / affective / mixed
3. is_subject_specific: ทักษะเฉพาะสาขาวิชา (true) หรือเป็น generic
   transferable skill (false)
4. confidence: ความมั่นใจในการสกัด (0.0-1.0)

หลักเกณฑ์:
- อย่าสร้างทักษะที่ไม่มีหลักฐานในข้อความ
- ใช้ชื่อทักษะที่ปรากฏในมาตรฐานวิชาชีพหรือมคอ.1 หากเป็นไปได้
- ทักษะหนึ่งข้อ = หนึ่ง action verb ที่ชัดเจน ห้ามรวมหลายทักษะเป็นข้อเดียว
- ถ้าข้อความระบุ "ความรู้เรื่อง X" ให้แปลงเป็น "อธิบาย X ได้"
- ถ้าข้อความระบุ "เข้าใจ Y" ให้แปลงเป็น "อธิบาย Y" หรือ "วิเคราะห์ Y"
  ตามบริบท

ส่งคำตอบเป็น list ของ ExtractedSkill objects
```

---

## Stage 3: Skill cluster naming and description

**Purpose:** after K-means/HDBSCAN clusters skills, an LLM gives each cluster a canonical name and description.

**Model:** medium (Qwen 14B / 32B)

```
คุณเป็นผู้เชี่ยวชาญในการจัดหมวดหมู่ทักษะวิชาชีพ

ข้อมูล: ทักษะต่อไปนี้ถูกจัดกลุ่มร่วมกันโดยอัลกอริธึมจัดกลุ่มทาง data science
ให้ตั้งชื่อกลุ่มทักษะนี้ และอธิบายว่ากลุ่มนี้แทนความสามารถอะไร

ทักษะในกลุ่ม:
{skill_list}

ตัวอย่างจากข้อความต้นฉบับ (เพื่อให้เห็นบริบท):
{sample_quotes}

ส่งคำตอบ:
1. canonical_name_th: ชื่อที่สื่อความสามารถของกลุ่มนี้ในภาษาไทย
   (ใช้คำที่นักออกแบบหลักสูตรเข้าใจ ไม่ใช่ศัพท์เทคนิคจำเพาะ)
2. canonical_name_en: ภาษาอังกฤษ
3. description_th: คำอธิบายความสามารถของกลุ่มนี้ ความยาว 2-3 ประโยค
4. is_subject_specific: เฉพาะสาขา (true) หรือ generic (false)
5. skill_type: หลักของกลุ่มนี้ (knowledge/psychomotor/affective/mixed)

ห้ามใช้ชื่อที่กว้างเกินไปเช่น "ทักษะทางวิชาชีพ" หรือ "ความรู้พื้นฐาน"
ตั้งชื่อให้สื่อความสามารถจริงที่กลุ่มนี้แทน
```

---

## Stage 4: PLO synthesis (the most important prompt)

**Purpose:** convert top skill clusters into 6–10 PLOs.

**Model:** heavy (Qwen 32B / Llama 70B / Claude / GPT-4o)

```
คุณเป็นผู้เชี่ยวชาญด้านการออกแบบหลักสูตรระดับอุดมศึกษาตามแนวทาง OBE
ที่ผ่านการรับรอง AUN-QA

บริบทหลักสูตร:
- สาขาวิชา: {field}
- ระดับ: {degree_level} ({duration_years} ปี)
- วิสัยทัศน์มหาวิทยาลัย/คณะ: {vision_th}
- อัตลักษณ์นิสิต: {student_identity}
- วัตถุประสงค์ของหลักสูตร: {program_objectives}
- สภาวิชาชีพ: {professional_council}

ข้อมูลจากขั้น skill extraction (skill clusters ที่ผ่านการคัดกรองแล้ว):
{cluster_summaries_with_evidence}

งาน: เขียน Program Learning Outcomes (PLOs) จำนวน 6-10 ข้อ
ที่ผู้สำเร็จการศึกษาทุกคนต้องทำได้

หลักเกณฑ์ที่ต้องปฏิบัติตามอย่างเคร่งครัด:

1. SMART:
   - Specific: ชัดเจนว่าผู้เรียนต้องทำอะไร
   - Measurable: วัดและประเมินได้
   - Achievable: ทำได้ภายในระยะเวลา {duration_years} ปี
   - Relevant: สอดคล้องกับวัตถุประสงค์หลักสูตรและ stakeholder needs
   - Timely: บรรลุได้เมื่อสำเร็จการศึกษา

2. Bloom Taxonomy:
   - ใช้ action verb ตาม Bloom เพียงตัวเดียวต่อ PLO
   - PLO ระดับ bachelor ส่วนใหญ่อยู่ที่ Apply / Analyze / Evaluate / Create
   - หลีกเลี่ยงคำต้องห้าม: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก

3. ความสมดุล:
   - ต้องมีทั้ง subject-specific (60-70%) และ generic transferable (30-40%)
   - ครอบคลุมอย่างน้อย 2 ด้านจาก: cognitive / psychomotor / affective

4. การมีหลักฐาน:
   - ทุก PLO ต้องอ้างอิง cluster_id ที่เป็นที่มา
   - ให้เหตุผล (rationale_th) ว่าทำไม PLO นี้จำเป็น

5. จุดเด่น:
   - หลักสูตรนี้ควรมี PLO ที่แตกต่างหรือเด่นกว่าหลักสูตรในสาขาเดียวกัน
   - ระบุในแต่ละ PLO ว่าจุดเด่นคืออะไร (ถ้ามี)

ตัวอย่าง PLO ที่ดี:
"PLO1: ออกแบบบรรจุภัณฑ์โดยคำนึงถึงทรัพย์สินทางปัญญาและความยั่งยืนทาง
สิ่งแวดล้อมได้"
- Action verb: ออกแบบ (Create)
- Subject-specific
- Measurable: มีงานออกแบบที่ผ่านการตรวจสอบ
- Source: cluster ID 12, 17, 23 (จากนายจ้าง 47 ราย, สภาวิชาชีพ)

ตัวอย่าง PLO ที่ไม่ดี:
"ผู้เรียนมีความเข้าใจในหลักการบรรจุภัณฑ์"
ปัญหา: คำว่า "เข้าใจ" วัดไม่ได้, ไม่ระบุระดับ Bloom, ไม่มีหลักฐาน

ส่งคำตอบเป็น list ของ PLO objects ตาม schema
```

---

## SMART validator prompt

**Purpose:** independent check of a generated PLO. Used as a guardrail after PLO synthesis, inside the SMART retry loop — on a hard fail (S / M / R-evidence), re-prompt the synthesis model naming the specific violated criterion (not a generic "try again"), max 3 attempts before escalating to human review. Soft fails (A / R-alignment) become checkpoint warnings, not retries. See `obe-principles.md` for the hard/soft rubric.

**Model:** light to medium (Qwen 14B is fine)

```
ตรวจสอบว่า learning outcome ต่อไปนี้ผ่านเกณฑ์ SMART หรือไม่

Outcome: {outcome_statement}

ประเมินทีละข้อ พร้อมเหตุผล:
1. Specific (S): ระบุพฤติกรรม/ความสามารถชัดเจนหรือไม่
2. Measurable (M): สามารถวัดและประเมินได้หรือไม่
3. Achievable (A): บรรลุได้ภายในระยะเวลา/ทรัพยากรของหลักสูตรหรือไม่
4. Relevant (R): สอดคล้องกับวัตถุประสงค์หลักสูตร {program_objectives} หรือไม่
5. Timely (T): มีกรอบเวลาชัดเจนหรือไม่

ตรวจคำต้องห้าม: outcome ใช้คำว่า "รู้", "จำ", "เข้าใจ", "ซาบซึ้ง",
"ตระหนัก", "ศรัทธา", "รัก" หรือไม่ (ถ้าใช้ ให้ fail Measurable)

ตรวจ Bloom verb: outcome มี action verb เพียงตัวเดียวที่ตรงกับระดับ
Bloom หรือไม่ (ถ้ามีหลายตัวที่ไม่อยู่ใน level ติดกัน ให้ fail Specific)

ส่งคำตอบเป็น SMARTCheck object พร้อม notes_th บอกว่าควรแก้ไขอย่างไร
ถ้ามีจุดที่ไม่ผ่าน
```

---

## Prompt design tips specific to this project

**Always anchor the model in OBE language.** The opening line "ผู้เชี่ยวชาญ OBE" / "AUN-QA" matters — it shifts the model into education-domain register and away from generic helpful-assistant mode.

**Show good and bad examples.** Especially for PLO synthesis, the model has seen many bad PLOs in pretraining (academic web content with vague outcomes). Counter this with explicit examples of what to avoid.

**Be explicit about Thai.** Instruct the model to write in Thai for student-facing statements. Without this, models like Qwen and Llama drift to English.

**Constrain to schema.** Use Instructor/Pydantic. If you can't, ask the model for `JSON only, no preamble` and parse defensively.

**Keep cluster summaries short.** When passing N clusters into PLO synthesis, summarize each in ≤200 tokens. The full evidence chain stays in the database; the prompt only needs the gist.

**Don't ask for too many PLOs at once.** 6–10 is the project's range. Asking for "as many as needed" leads to 12+ overlapping outcomes.
