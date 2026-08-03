# Prompt Templates Reference

LLM prompts for each agent stage. When building or modifying a prompt, start from the relevant template here. If a needed prompt doesn't exist, add it to this file rather than scattering prompts across the codebase.

Every prompt template below is mirrored 1:1 in `src/curriculum_agent/prompts/` — one file per prompt module, each exporting typed builder functions that return OpenAI-style `list[dict[str, str]]` messages for Instructor. Current files:

| Prompt file | Used by | Purpose |
|---|---|---|
| `extract_metadata.py` | `stages/intake.py` | Extract vision/mission/identity from an uploaded document |
| `suggest_isced.py` | `stages/intake.py` | Suggest ISCED-F 2013 code + program names |
| `extract_skills.py` | `stages/skill_extraction.py` | Grounded skill extraction with KSEC + Bloom tagging + field-relevance judgement |
| `cluster_skills.py` | `stages/llm_clustering.py`, `stages/need_combination.py` | Group/merge skill names by meaning (index-based) |
| `summarize_need.py` | `stages/need_combination.py` | Turn one skill group into one market-demand sentence (a Need) |
| `stage_3_plo.py` | `stages/plo_synthesis.py` | Draft one PLO from one or more Needs |
| `smart_validator.py` | `stages/plo_synthesis.py` | Soft SMART judge (S-object / A-level / R-alignment only — hard checks are pure code) |

There is no `classify_evidence.py` or `plo_classify.py`. Evidence classification (`requirement`/`general`) is a pure code lookup from `StakeholderType` — see `stages/stakeholder_needs.py`'s `classify_evidence_type`, no prompt involved. `plo_report` no longer classifies PLOs generic vs specific — it assembles and exports only, also with no LLM call.

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

## Stakeholder evidence classification: no prompt

Evidence classification (`requirement` vs `general`) is decided entirely in code, from the `StakeholderType` alone — `classify_evidence_type` in `stages/stakeholder_needs.py`. `PROFESSIONAL_COUNCIL` and `INSTITUTIONAL_DIRECTION` are `requirement`; every other type is `general`. There is no LLM call and no prompt at this stage — the previous design asked a light model to judge each item `need`/`requirement`/`unclassified`, which was both a cost per item and the wrong question: a mandate is a property of who is speaking, not of how they phrased it. `need`/`want`/`unclassified` classification happens later, per skill — see `extract_skills.py` below and `classify_skills` in `stages/skill_extraction.py`.

---

## Stage 3: Skill extraction from raw evidence (grounded)

**Purpose:** extract structured, evidence-grounded skill mentions from one piece of evidence. Runs per evidence item, cache-first (keyed on a text slice + classification + model + program field/name).

**Model:** light (Typhoon 8B / Qwen 7B) — `complete_light`

**File:** `prompts/extract_skills.py` — `build_extract_skills_prompt(evidence_text, classification, field_th="", program_name_th="")`

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
- ทักษะที่อ่านแล้วไม่เข้าข่ายสาขาวิชาของหลักสูตรเลย ให้คงไว้แต่ตั้ง
  is_field_relevant = false ห้ามตัดทิ้งเอง ผู้ออกแบบหลักสูตรจะเป็นผู้ตัดสิน

ตอบเป็น JSON object: { skills: [ {
  skill_name_th: วลีทักษะภาษาไทย,
  skill_name_en: ชื่อภาษาอังกฤษมาตรฐาน (เช่น 'Data Analysis') ห้ามเว้นว่าง,
  ksec_category: K|S|E|C — K=ความรู้, S=ทักษะ,
  E=คุณธรรมจริยธรรม, C=คุณลักษณะบุคคล
  (เลือกได้เพียงค่าเดียว ห้ามตอบว่าผสมกัน),
  bloom_level: remember|understand|apply|analyze|evaluate|create
  — ระดับ Bloom ด้าน Cognitive เท่านั้น,
  evidence_span_th: ข้อความที่คัดลอกตรงตัวจาก evidence,
  is_field_relevant: true|false — ทักษะนี้อยู่ในขอบเขตของสาขาวิชาหรือไม่,
  confidence: 0.0-1.0
} ] }
สกัดไม่เกิน 8 ทักษะต่อข้อความ เน้นทักษะที่วัดได้จริง

[ประเภทหลักฐาน: {classification}]
[หลักสูตร: {program_name_th}]   # only if present
[สาขาวิชา: {field_th}]          # only if present
{evidence_text}
```

`field_th` and `program_name_th` (sourced from `state["metadata"]`) are what make the "no off-field skills" rule answerable — without them the model was told to exclude off-field skills without being told what the field was. A skill judged off-field is kept with `is_field_relevant=false`, never silently dropped — the designer sees it at the checkpoint and can promote it. `classification` (`requirement`/`need`/`want`/`unclassified`) is not part of this prompt's output at all: it is computed afterward, in pure code, by `classify_skills` once every evidence item in the program has been extracted (see `data-schemas.md` for the precedence rules).

`evidence_span_th` is not trusted on the model's word: the caller (`stages/skill_extraction.py`) re-checks every span against the actual evidence text with `is_grounded()` and drops any skill whose quote is too short (< 12 chars) or doesn't literally occur in the source. This is the one place in the pipeline where a prompt instruction ("copy verbatim, don't invent") is backed by a pure-code verification instead of trusted outright.

---

## need_combination: skill-name clustering and merging

**Purpose:** group extracted-skill *names* (already deduped and bucketed by KSEC — see `data-schemas.md`) into candidate Needs. No downstream quota merge: every candidate group a bucket produces becomes its own Need. Index-based: the model assigns numeric indices into a name list, never rewrites the names themselves, so `stages/llm_clustering.py`'s `validate_assignments()` can enforce "every index exactly once" in pure code afterward.

**Model:** heavy (`complete_heavy`) — this is a reasoning-over-labels task, not a light-model classification

**File:** `prompts/cluster_skills.py` — two builders:

- `build_cluster_skills_prompt(skill_names)` — first-pass grouping of a batch of skill names by meaning, returns `{clusters: [{label_th, member_indices}]}`.
- `build_merge_clusters_prompt(cluster_labels)` — merges same-meaning cluster labels produced across multiple first-pass batches, returns `{groups: [[index, ...]]}`.

Because clustering and merging both run *inside* one KSEC bucket (bucketing happens before any of this in `stages/need_grouping.py`), no prompt here ever needs to ask the model to keep KSEC tags apart — it structurally cannot see skills from a different bucket.

---

## need_combination: Need statement summarization

**Purpose:** turn one finished skill group (all one KSEC tag, post-merge) into the one market-demand sentence that becomes `Need.statement_th`.

**Model:** light (`complete_light`)

**File:** `prompts/summarize_need.py` — `build_summarize_need_prompt(skill_names, sample_evidence, ksec, note_th=None)`

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

**Purpose:** restate one or more market Needs (already at least 6 core, no upper cap, post-`need_combination`) as a single graduate-side PLO. Called once per Need by the stage loop (list of length 1), and reused by the designer-driven `POST /programs/{id}/plos/from-needs` endpoint with a longer list when the designer chooses to merge several Needs into one PLO — same function, same rules, whether it's 1 Need or several.

**Model:** heavy (`complete_heavy`) — config-switchable to a proprietary model per project policy, never hardcoded

**File:** `prompts/stage_3_plo.py` — `build_plo_from_need_prompt(metadata, needs, note_th=None)`

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
  statement_th, statement_en, bloom_level,
  action_verb_th, source_need_ids, rationale_th, distinctive_feature_th
(ไม่ต้องระบุ evidence ใด ๆ — ระบบจะผูก evidence จาก need ที่ให้มาเอง)

[สำหรับแต่ละ Need ที่ให้มา:]
need_id: {need_id}
ความต้องการของตลาด: {statement_th}
หมวดสมรรถนะ: {ksec_category}
ระดับ Bloom ที่เหมาะสม: {bloom_level}
ความถี่ที่ถูกกล่าวถึง: {freq} ครั้ง (demand {demand_score})
```

`plo_id` and `source_evidence_ids` are deliberately absent from the draft schema. Each is computed in code: the id by `format_plo_id`/`next_plo_id`, the evidence trail as the union of the contributing Needs' own verified `source_evidence_ids`. Asking the model for either invited it to contradict the data — it answered "PLO1" for every Need (collapsing a whole set into one upserted row) and invented evidence ids that pointed nowhere. Program context (`{field}`, `{degree_level}`, `{vision_th}` from `ProgramMetadata`) is included in the real prompt; see the file for the exact block.

Both templates take an optional `note_th`. When present it is appended to the **user** message under `ข้อกำหนดเพิ่มเติมจากผู้ออกแบบหลักสูตร:`; the system message carries an unconditional line saying the note guides wording and does not override the rules above it. See `prompts/designer_note.py`.

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

## plo_report: no prompt

`plo_report` no longer classifies PLOs generic vs specific — that call read the fraction of `SS`-tagged Needs behind a PLO, and the `SS`/`GS` KSEC split it depended on no longer exists. The stage is pure assembly and export now: it loads each PLO's source Needs, resolves the evidence trail, and puts the assembled report (every PLO with its Bloom level, KSEC tag, SMART soft flags, escalation status, evidence drill-down) into state — no LLM call.

---

## Prompt design tips specific to this project

**Always anchor the model in OBE language.** The opening line "ผู้เชี่ยวชาญ OBE" / "AUN-QA" matters — it shifts the model into education-domain register and away from generic helpful-assistant mode.

**Show good and bad examples.** Especially for PLO synthesis, the model has seen many bad PLOs in pretraining (academic web content with vague outcomes). Counter this with explicit examples of what to avoid.

**Be explicit about Thai.** Instruct the model to write in Thai for student-facing statements. Without this, models like Qwen and Llama drift to English.

**Constrain to schema.** Use Instructor/Pydantic. If you can't, ask the model for `JSON only, no preamble` and parse defensively.

**Keep Need summaries short.** PLO synthesis passes each Need's statement, KSEC tag, Bloom level, and frequency/demand — not full evidence text. Summarize in ≤200 tokens; the full evidence chain stays in the database, the prompt only needs the gist.

**The floor is enforced upstream, not by asking nicely.** PLO synthesis never asks the model for a target PLO count — it calls the per-Need prompt once per Need, one PLO out per Need in. There is no upper cap: every core group `need_combination` finds becomes a Need, and one Need becomes one PLO. A core count below `MIN_NEEDS` (6) only logs a policy warning for the designer to address at the checkpoint. If a prompt anywhere asks an LLM to directly produce "a set of N PLOs", that's a regression to the old batch-synthesis design — don't reintroduce it.

**Never let a clustering/merge prompt cross a KSEC bucket.** Every skill-name clustering and merge call in `need_combination` is invoked per-bucket by the caller (`stages/need_grouping.py`'s `bucket_by_ksec`) — the prompt itself never receives skills from more than one KSEC tag at a time. If you add a new grouping prompt, bucket before you call it; don't rely on prompt wording to keep tags apart, since a model asked nicely can still mix them and there is no downstream check that would catch it.
