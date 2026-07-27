# Prompt Templates Reference

LLM prompts for each agent stage. When building or modifying a prompt, start from the relevant template here. If a needed prompt doesn't exist, add it to this file rather than scattering prompts across the codebase.

Every prompt template below is mirrored 1:1 in `src/curriculum_agent/prompts/` — one file per prompt module, each exporting typed builder functions that return OpenAI-style `list[dict[str, str]]` messages for Instructor. Current files:

| Prompt file | Used by | Purpose |
|---|---|---|
| `extract_metadata.py` | `stages/intake.py` | Extract vision/mission/identity from an uploaded document |
| `suggest_isced.py` | `stages/intake.py` | Suggest ISCED-F 2013 code + program names |
| `classify_evidence.py` | `stages/stakeholder_needs.py` | Classify evidence need/requirement/unclassified (want is pure code) |
| `extract_skills.py` | `stages/skill_extraction.py` | Grounded skill extraction with KSEC + Bloom tagging |
| `cluster_skills.py` | `stages/llm_clustering.py`, `stages/need_combination.py` | Group/merge skill names by meaning (index-based) |
| `summarize_need.py` | `stages/need_combination.py` | Turn one skill group into one market-demand sentence (a Need) |
| `stage_3_plo.py` | `stages/plo_synthesis.py` | Draft one PLO from one or more Needs |
| `smart_validator.py` | `stages/plo_synthesis.py` | Soft SMART judge (S-object / A-level / R-alignment only — hard checks are pure code) |
| `plo_classify.py` | `stages/plo_report.py` | LLM fallback for generic/specific PLO classification |

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

**Purpose:** classify each piece of stakeholder evidence. `want` is deliberately **not** an LLM option — `COMMUNITY`/`PARENT` evidence is assigned `want` in pure code (`WANT_ONLY_TYPES` in `stages/stakeholder_needs.py`) before this prompt ever runs; every other stakeholder type is sent to the LLM, which can only choose between `need`, `requirement`, and `unclassified`.

**Model:** light (Typhoon 8B / Qwen 7B)

**File:** `prompts/classify_evidence.py` — `build_classify_evidence_prompt(evidence)`

```
คุณเป็นผู้เชี่ยวชาญด้านการออกแบบหลักสูตร OBE ตามมาตรฐาน MHESI
จงจัดประเภทข้อมูลความต้องการจากผู้มีส่วนได้ส่วนเสียออกเป็น 1 ประเภท:
- requirement: ข้อกำหนด/มาตรฐานที่ต้องปฏิบัติตาม (compliance) บังคับต้องมี
- need: ความต้องการของตลาดที่ทำให้หลักสูตรทันสมัยและตรงงานจริง
- unclassified: ข้อมูลที่ไม่ชัดเจนพอที่จะจัดประเภท

ตอบเป็น JSON object ที่มี field:
  classification: string (requirement|need|unclassified)
  classification_rationale_th: string (เหตุผลสั้น ๆ ภาษาไทย ไม่เกิน 2 ประโยค)

แหล่งที่มา: {source_name} ({stakeholder_type})
ข้อความ: {raw_text_th}
(EN) {raw_text_en}   # only if present
```

Pair with the `_ClassifyResult` Pydantic model (`classification: Literal["need", "requirement", "unclassified"]`, `classification_rationale_th: str`).

---

## Stage 3: Skill extraction from raw evidence (grounded)

**Purpose:** extract structured, evidence-grounded skill mentions from one piece of evidence. Runs per evidence item, cache-first (keyed on a text slice + classification + model).

**Model:** light (Typhoon 8B / Qwen 7B) — `complete_light`

**File:** `prompts/extract_skills.py` — `build_extract_skills_prompt(evidence_text, classification)`

```
คุณเป็นผู้เชี่ยวชาญวิเคราะห์ทักษะจากข้อความ
จากข้อความ evidence จงระบุทักษะที่ตลาดแรงงานต้องการ

กติกา:
- แต่ละทักษะต้องเป็น 'วลี' หรือกลุ่มคำที่สื่อความสามารถ ห้ามเป็นคำโดดคำเดียว
- ทักษะแต่ละรายการต้องไม่ซ้ำและไม่คาบเกี่ยวกัน (unique, independent)
  ห้ามเขียนสิ่งเดียวกันด้วยถ้อยคำต่างกัน
- evidence_span_th ต้องคัดลอกข้อความ 'ตรงตัว' จาก evidence ที่ทำให้สรุปทักษะนี้ได้
  ห้ามเรียบเรียงใหม่ ห้ามแต่งเพิ่ม ถ้าไม่มีข้อความรองรับ ห้ามเสนอทักษะนั้น
- evidence_span_th ต้องเป็นวลีที่สมบูรณ์ ยาวอย่างน้อยประมาณ 12 ตัวอักษร
  คัดลอกตรงตัวจาก evidence ห้ามตัดมาเป็นเศษคำหรืออักขระเดี่ยว ๆ
- ทักษะที่ไม่เกี่ยวข้องกับสาขาวิชาของหลักสูตร ห้ามเสนอ

ตอบเป็น JSON object: { skills: [ {
  skill_name_th: วลีทักษะภาษาไทย,
  skill_name_en: ชื่อภาษาอังกฤษมาตรฐาน (เช่น 'Data Analysis') ห้ามเว้นว่าง,
  ksec_category: K|GS|SS|C|E — K=ความรู้, GS=ทักษะทั่วไป,
  SS=ทักษะเฉพาะสาขา, C=คุณลักษณะบุคคล, E=คุณธรรมจริยธรรม
  (เลือกได้เพียงค่าเดียว ห้ามตอบว่าผสมกัน),
  bloom_level: remember|understand|apply|analyze|evaluate|create
  — ระดับ Bloom ด้าน Cognitive เท่านั้น,
  evidence_span_th: ข้อความที่คัดลอกตรงตัวจาก evidence,
  confidence: 0.0-1.0
} ] }
สกัดไม่เกิน 8 ทักษะต่อข้อความ เน้นทักษะที่วัดได้จริง

[ประเภทหลักฐาน: {classification}]
{evidence_text}
```

`evidence_span_th` is not trusted on the model's word: the caller (`stages/skill_extraction.py`) re-checks every span against the actual evidence text with `is_grounded()` and drops any skill whose quote is too short (< 12 chars) or doesn't literally occur in the source. This is the one place in the pipeline where a prompt instruction ("copy verbatim, don't invent") is backed by a pure-code verification instead of trusted outright.

---

## need_combination: skill-name clustering and merging

**Purpose:** group extracted-skill *names* (already deduped and bucketed by KSEC — see `data-schemas.md`) into candidate Needs, then merge candidate groups down to the 6–10 quota. Both operations are index-based: the model assigns/merges numeric indices into a name list, never rewrites the names themselves, so `stages/llm_clustering.py`'s `validate_assignments()` can enforce "every index exactly once" in pure code afterward.

**Model:** heavy (`complete_heavy`) — this is a reasoning-over-labels task, not a light-model classification

**File:** `prompts/cluster_skills.py` — three builders:

- `build_cluster_skills_prompt(skill_names)` — first-pass grouping of a batch of skill names by meaning, returns `{clusters: [{label_th, member_indices}]}`.
- `build_merge_clusters_prompt(cluster_labels)` — merges same-meaning cluster labels produced across multiple first-pass batches, returns `{groups: [[index, ...]]}`.
- `build_merge_to_target_prompt(cluster_labels, target_count)` — merges groups within one KSEC bucket down to an exact target count (the 6–10 quota mechanism); used by `_merge_bucket` in `stages/need_combination.py`, with a demand-ranked pure-code fallback (`_fuse_by_demand`) if the model returns the wrong count or fails outright.

```
คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ทักษะแรงงาน
รายการต่อไปนี้คือชื่อกลุ่มทักษะภายในหมวดสมรรถนะเดียวกัน
จงรวมกลุ่มที่มีความหมายใกล้เคียงกันเข้าด้วยกัน ให้เหลือ {target_count} กลุ่มพอดี

กติกา:
- ผลลัพธ์ต้องมี {target_count} group พอดี ไม่มากไม่น้อยกว่านี้
- ทุก index ต้องปรากฏใน groups ครั้งเดียวเท่านั้น ห้ามตกหล่น ห้ามซ้ำ
- ห้ามใช้ index ที่ไม่มีในรายการ
- เลือกรวมกลุ่มที่ทำงานลักษณะเดียวกันหรือใช้ทักษะร่วมกันก่อน
  ห้ามรวมกลุ่มที่ไม่เกี่ยวข้องกันเพียงเพื่อให้ครบจำนวน

ตอบเป็น JSON object:
{ groups: [ [index ของกลุ่มที่ควรรวมเข้าด้วยกัน] ] }
```

Because clustering and merging both run *inside* one KSEC bucket (bucketing happens before any of this in `stages/need_grouping.py`), no prompt here ever needs to ask the model to keep KSEC tags apart — it structurally cannot see skills from a different bucket.

---

## need_combination: Need statement summarization

**Purpose:** turn one finished skill group (all one KSEC tag, post-merge) into the one market-demand sentence that becomes `Need.statement_th`.

**Model:** light (`complete_light`)

**File:** `prompts/summarize_need.py` — `build_summarize_need_prompt(skill_names, sample_evidence, ksec)`

```
คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ความต้องการของตลาดแรงงาน
จากกลุ่มทักษะที่ให้มา จงสรุปเป็น 'ความต้องการของตลาด' หนึ่งประโยค

กติกา:
- เขียนเป็นประโยคเดียว มุมมองของ 'ตลาดแรงงานต้องการอะไร'
  ไม่ใช่มุมมองผู้เรียนหรือผลลัพธ์การเรียนรู้
- ต้องสื่อถึงความสามารถจริงที่ใช้ทำงานได้ ไม่ใช่แค่ชื่อหมวดทักษะ
- ห้ามเป็นเพียงการนำชื่อทักษะมาต่อกันด้วยเครื่องหมายจุลภาค
- ความยาวไม่เกิน 2 บรรทัด

ตอบเป็น JSON object ที่มี field:
  statement_th: string (ประโยคภาษาไทย)
  statement_en: string (ประโยคภาษาอังกฤษ)

หมวดสมรรถนะ: {ksec_label} ({ksec})
ทักษะในกลุ่มนี้: {skill_names, joined}
ตัวอย่างข้อความ evidence: {sample_evidence}
```

If this call fails, `stages/need_combination.py` falls back to a plain comma-joined skill-name list rather than blocking the stage — a degraded but still evidence-grounded `Need.statement_th`.

---

## Stage 5 (plo_synthesis): one Need → one PLO (the most important prompt)

**Purpose:** restate one or more market Needs (already 6–10 core, post-`need_combination`) as a single graduate-side PLO. Called once per Need by the stage loop (list of length 1), and reused by the designer-driven `POST /programs/{id}/plos/from-needs` endpoint with a longer list when the designer chooses to merge several Needs into one PLO — same function, same rules, whether it's 1 Need or several.

**Model:** heavy (`complete_heavy`) — config-switchable to a proprietary model per project policy, never hardcoded

**File:** `prompts/stage_3_plo.py` — `build_plo_from_need_prompt(metadata, needs)`

```
คุณเป็นผู้เชี่ยวชาญ OBE ตามมาตรฐาน MHESI
จงแปลง 'ความต้องการของตลาด' หนึ่งข้อ ให้เป็น PLO หนึ่งข้อ
[ถ้ามีหลาย Need: จงรวม 'ความต้องการของตลาด' ที่ให้มาทั้งหมด ให้เป็น PLO เพียงหนึ่งข้อ]

กติกา:
- เขียนจากมุมผู้เรียน: 'บัณฑิตทำอะไรได้' ไม่ใช่ 'ตลาดต้องการอะไร'
- ใช้คำกริยาแสดงพฤติกรรมตาม Bloom เพียง 1 คำ
- ห้ามใช้คำที่วัดไม่ได้: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก
- ต้องระบุวัตถุของกริยาให้เจาะจง ห้ามใช้คำกว้างเช่น 'ความรู้ที่จำเป็น'
- source_need_ids ต้องเป็น need_id ที่ให้มาทั้งหมด ห้ามเพิ่มหรือตัดทิ้ง
  [ถ้ามีหลาย Need: ต้องครอบคลุมสาระของทุกความต้องการที่ให้มา ห้ามละข้อใดข้อหนึ่ง]

ตอบเป็น JSON object ที่มี field: plo (object) โดย plo มี field:
  plo_id, statement_th, statement_en, bloom_level, is_subject_specific,
  action_verb_th, source_need_ids, source_evidence_ids, rationale_th,
  distinctive_feature_th

[สำหรับแต่ละ Need ที่ให้มา:]
need_id: {need_id}
ความต้องการของตลาด: {statement_th}
หมวดสมรรถนะ: {ksec_category}
ระดับ Bloom ที่เหมาะสม: {bloom_level}
ความถี่ที่ถูกกล่าวถึง: {freq} ครั้ง (demand {demand_score})
```

`source_evidence_ids` on the returned draft is a fallback, not the source of truth: `synthesize_from_needs()` in `stages/plo_synthesis.py` prefers the union of the contributing Needs' own `source_evidence_ids` (already verified upstream) over trusting the model to echo IDs correctly. Program context (`{field}`, `{degree_level}`, `{vision_th}`, etc. from `ProgramMetadata`) is also included in the real prompt — omitted above for brevity; see the file for the exact block.

Every draft this prompt produces goes through the SMART hard-check retry loop (below) before it becomes a persisted `PLO` — this prompt alone does not guarantee a SMART-passing statement.

---

## SMART soft judge prompt

**Purpose:** the S/M/R **hard** criteria (one Bloom verb present, no forbidden word, non-empty evidence trail) are never checked by an LLM at all — they are pure code in `stages/smart_rules.py` (`hard_failures()`), because they're mechanically checkable and a model is a slower, less reliable way to check them. This prompt covers only the three **soft** criteria that genuinely need judgement: S-object quality, A-level plausibility, R-alignment with vision. Its output becomes `PLO.soft_flags` for human review — it never blocks or retries.

**Model:** light (`complete_light`)

**File:** `prompts/smart_validator.py` — `build_smart_soft_judge_prompt(statement_th, vision_th, degree_level)`

```
คุณเป็นผู้ตรวจสอบคุณภาพ PLO ประเมิน 3 ข้อ ตอบเป็น JSON:
specific_object_ok: กรรมของกริยาเจาะจง (ไม่ใช่คำกว้างเช่น 'ความรู้' 'ทักษะที่จำเป็น')
achievable_ok: ระดับ Bloom เหมาะกับระดับปริญญา
relevant_alignment_ok: สอดคล้องกับวิสัยทัศน์หลักสูตร
notes_th: เหตุผลสั้นๆ สำหรับข้อที่ไม่ผ่าน

PLO: {statement_th}
ระดับปริญญา: {degree_level}
วิสัยทัศน์: {vision_th}
```

The hard-fail retry loop this soft judge sits alongside is code, not a prompt: `stages/plo_synthesis.py`'s `_ensure_smart()` calls `hard_failures()`, and on a hard fail re-prompts the PLO-drafting model (`_build_fix_prompt`) naming the specific violated criterion, up to 3 attempts, before setting `smart_escalated=True`. See `obe-principles.md` for the full hard/soft rubric.

---

## PLO generic/specific classification (plo_report)

**Purpose:** the plo_report stage's generic-vs-specific call for each PLO. Method D: first try a pure-code decision from the KSEC mix of the PLO's source Needs (fraction of SS among resolved Needs — ≥0.67 → specific, ≤0.33 → generic); only the ambiguous middle band falls through to this LLM prompt.

**Model:** light (`complete_light`)

**File:** `prompts/plo_classify.py` — `build_plo_classify_prompt(statement_th, bloom_level, cluster_summaries)` (the `cluster_summaries` parameter name predates the Need rename in the code and is stale, but the argument it's actually given is a list of Need summaries — see `_need_summary()` in `stages/plo_report.py`)

```
คุณเป็นผู้เชี่ยวชาญ OBE ทำหน้าที่จำแนกประเภทของ PLO
ว่าเป็น 'generic' (ทักษะทั่วไปที่ถ่ายโอนข้ามสาขาได้ เช่น การสื่อสาร
การคิดวิเคราะห์ การทำงานเป็นทีม) หรือ 'specific'
(ทักษะ/ความรู้เฉพาะสาขาหรือวิชาชีพ)
ตอบเป็น JSON ที่มี field 'classification' (ค่า 'generic' หรือ 'specific')
และ 'rationale_th' (เหตุผลสั้น ๆ เป็นภาษาไทย)

PLO statement: {statement_th}
Bloom level: {bloom_level}
Skill clusters ที่เกี่ยวข้อง: {summary_block}
```

---

## Prompt design tips specific to this project

**Always anchor the model in OBE language.** The opening line "ผู้เชี่ยวชาญ OBE" / "AUN-QA" matters — it shifts the model into education-domain register and away from generic helpful-assistant mode.

**Show good and bad examples.** Especially for PLO synthesis, the model has seen many bad PLOs in pretraining (academic web content with vague outcomes). Counter this with explicit examples of what to avoid.

**Be explicit about Thai.** Instruct the model to write in Thai for student-facing statements. Without this, models like Qwen and Llama drift to English.

**Constrain to schema.** Use Instructor/Pydantic. If you can't, ask the model for `JSON only, no preamble` and parse defensively.

**Keep Need summaries short.** PLO synthesis passes each Need's statement, KSEC tag, Bloom level, and frequency/demand — not full evidence text. Summarize in ≤200 tokens; the full evidence chain stays in the database, the prompt only needs the gist.

**The 6–10 range is enforced upstream, not by asking nicely.** PLO synthesis never asks the model for "6 to 10 PLOs" — it calls the per-Need prompt once per Need, one PLO out per Need in. The 6–10 count is guaranteed by `need_combination`'s quota (`allocate_quota` in `stages/need_grouping.py`) before synthesis ever runs. If a prompt anywhere asks an LLM to directly produce "a set of 6–10 X", that's a regression to the old batch-synthesis design — don't reintroduce it.

**Never let a clustering/merge prompt cross a KSEC bucket.** Every skill-name clustering and merge call in `need_combination` is invoked per-bucket by the caller (`stages/need_grouping.py`'s `bucket_by_ksec`) — the prompt itself never receives skills from more than one KSEC tag at a time. If you add a new grouping prompt, bucket before you call it; don't rely on prompt wording to keep tags apart, since a model asked nicely can still mix them and there is no downstream check that would catch it.
