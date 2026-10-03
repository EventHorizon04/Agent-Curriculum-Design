# Prompt Templates Reference

Why each agent stage's prompt says what it says. Read this before changing one; a rule here usually replaced something that failed in a measured way, and the note says which.

**This file is the reasoning; it is not the prompts.** Each prompt is a Python literal returned by a builder in `src/curriculum_agent/prompts/`, and the verbatim text of every one of them is in [`docs/prompt-inventory.md`](../../../../docs/prompt-inventory.md), rendered from those builders by `scripts/dump_prompts.py`. Three copies used to sit in this file instead, and all three had drifted — the extraction one still asked for “ทักษะที่ตลาดแรงงานต้องการ” months after that framing was removed for reading a สภาวิชาชีพ standard as a job ad. A copy of a prompt starts lying the first time a rule is edited, so what stays here is what the generated file cannot carry: why each rule exists, what it replaced, and what breaks if it is removed. Current builders:

| Prompt file | Used by | Purpose |
|---|---|---|
| `extract_skills.py` | `stages/skill_extraction.py` | Grounded skill extraction with KSEC + Bloom tagging + field-relevance judgement |
| `cluster_skills.py` | `stages/llm_clustering.py`, `stages/need_combination.py` | Group/merge skill names by meaning (index-based) |
| `summarize_need.py` | `stages/need_combination.py` | Turn one skill group into one market-demand sentence (a Need) |
| `stage_3_plo.py` | `stages/plo_synthesis.py` | Draft one PLO from one or more Needs |
| `smart_agent.py` | `stages/smart_agent.py` | The SMART validation agent: rubric + tool contract, its tool observations, and the repair instruction it hands to synthesis |

There is no `extract_metadata.py` or `suggest_isced.py` either: intake collects program metadata the designer types, with no document upload and no LLM-suggested ISCED code. There is no `classify_evidence.py` or `plo_classify.py`. Evidence classification (`requirement`/`general`) is a pure code lookup from `StakeholderType` — see `stages/stakeholder_needs.py`'s `classify_evidence_type`, no prompt involved. `plo_report` no longer classifies PLOs generic vs specific — it assembles and exports only, also with no LLM call.

All prompts assume:
- LLM is Thai-capable (Typhoon, Qwen) or proprietary (Claude, GPT-4o)
- Output is structured via Instructor → Pydantic
- One LLM slot per stage — `extraction`, `clustering`, `need_combination`, `plo_synthesis`, `validation` — each with its own provider and model, declared once in `SLOTS` (`config.py`)

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

Evidence classification (`requirement` vs `general`) is decided entirely in code, from the `StakeholderType` alone — `classify_evidence_type` in `stages/stakeholder_needs.py`. `PROFESSIONAL_COUNCIL` and `INSTITUTIONAL_DIRECTION` are `requirement`; every other type is `general`. There is no LLM call and no prompt at this stage — the previous design asked a model to judge each item `need`/`requirement`/`unclassified`, which was both a cost per item and the wrong question: a mandate is a property of who is speaking, not of how they phrased it. `need`/`want`/`unclassified` classification happens later, per skill — see `extract_skills.py` below and `classify_skills` in `stages/skill_extraction.py`.

---

## Stage 3: Skill extraction from raw evidence (grounded)

**Purpose:** extract structured, evidence-grounded skill mentions from one piece of evidence. Runs per evidence item, cache-first (keyed on a text slice + classification + model + program field/name).

**Model:** extraction (`complete_extraction`, its own `EXTRACTION_PROVIDER`/`EXTRACTION_MODEL`) — not `light`. This is the fan-out stage: one call per *window* of every evidence item, so it exhausts a token quota before any other stage has run, and it ran the Thai endpoint's out. It gives up little by moving, since extraction names skills rather than writing prose anyone reads.

**File:** `prompts/extract_skills.py` — `build_extract_skills_prompt(evidence_text, classification, field_th="", program_name_th="", scope_th="")`

> ข้อความเต็มของ prompt นี้อยู่ใน [`docs/prompt-inventory.md`](../../../../docs/prompt-inventory.md)
> ซึ่ง `scripts/dump_prompts.py` render จาก builder จริง ไม่ได้คัดลอกด้วยมือ

`field_th` and `program_name_th` (sourced from `state["metadata"]`) are what make the "no off-field skills" rule answerable — without them the model was told to exclude off-field skills without being told what the field was. A skill judged off-field is kept with `is_field_relevant=false`, never silently dropped — the designer sees it at the checkpoint and can promote it. `classification` (`requirement`/`need`/`want`/`unclassified`) is not part of this prompt's output at all: it is computed afterward, in pure code, by `classify_skills` once every evidence item in the program has been extracted (see `data-schemas.md` for the precedence rules).

`evidence_span_th` is not trusted on the model's word: the caller (`stages/skill_extraction.py`) re-checks every span against the actual evidence text with `is_grounded()` and drops any skill whose quote is too short (< 12 chars) or doesn't literally occur in the source. This is the one place in the pipeline where a prompt instruction ("copy verbatim, don't invent") is backed by a pure-code verification instead of trusted outright.

---

## need_combination: skill-name clustering and merging

**Purpose:** group extracted-skill *names* (already deduped and bucketed by KSEC — see `data-schemas.md`) into candidate Needs. No downstream quota merge: every candidate group a bucket produces becomes its own Need. Index-based: the model assigns numeric indices into a name list, never rewrites the names themselves, so `stages/llm_clustering.py`'s `validate_assignments()` can enforce "every index exactly once" in pure code afterward.

**Model:** `clustering` (`complete_clustering`, its own `CLUSTERING_PROVIDER`/`CLUSTERING_MODEL`) — this is a reasoning-over-labels task, and it holds a whole KSEC bucket in one context, which is what the larger model is for

**File:** `prompts/cluster_skills.py` — two builders:

- `build_cluster_skills_prompt(skill_names)` — first-pass grouping of a batch of skill names by meaning, returns `{clusters: [{label_th, member_indices}]}`.
- `build_merge_clusters_prompt(cluster_labels)` — merges same-meaning cluster labels produced across multiple first-pass batches, returns `{groups: [[index, ...]]}`.

Because clustering and merging both run *inside* one KSEC bucket (bucketing happens before any of this in `stages/need_grouping.py`), no prompt here ever needs to ask the model to keep KSEC tags apart — it structurally cannot see skills from a different bucket.

---

## need_combination: Need statement summarization

**Purpose:** turn one finished skill group (all one KSEC tag, post-merge) into the one market-demand sentence that becomes `Need.statement_th`.

**Model:** `need_combination` (`complete_need_combination`). Its provider ships unset, so it follows `LLM_PROVIDER` — the Thai-first default this sentence needs belongs to that setting, and this slot inherits it rather than pinning it

**File:** `prompts/summarize_need.py` — `build_summarize_need_prompt(skill_names, ksec, bloom_level, *, note_th=None, program_context=None, skill_frequencies=None)`

**Sees the skills and nothing else.** Evidence text used to be pasted in as samples; it is not any more. The skills already carry what extraction found in that evidence, the raw quotes only gave the model longer Thai to drift on, and traceability is untouched — a Need's `source_evidence_ids` come from its member skills.

**The sentence must be PLO-ready.** `plo_synthesis` drafts exactly one PLO per Need and is handed nothing but this sentence, so a placeholder or a skill list does not merely weaken the PLO — it makes the synthesis model invent the capability with no evidence behind it. Hence the task/object/context rule and the hard rejections below.

**Task, object and — only when the group shares one — context.** This used to be an unconditional "ต้องมีครบ 3 ส่วน", which asked every group for a work context it might not actually have in common. It is now **"what most of the group shares"**, not a frequency threshold: on the stored corpus every skill name has frequency 1 (91/91), so a rule like "under X% of the group's total frequency must not decide the object" is degenerate — with 18 equal members each is 5.5%, and any X above that bans every member at once. `skill_frequencies` is passed to the model (and listed as a third column in the user turn, only when the caller supplies it) precisely so the rule starts to bite once a corpus has names that repeat, instead of being dead weight until then.

**The opening is free, and that is a decision.** "ตลาดแรงงานต้องการ..." was mandatory until `a5823b9`/`e09b2d6`: it carried nothing the rest of the sentence did not and spent characters against the 40-character floor. Several framings are offered instead, and `test_summarize_need.py` pins both halves — that the openings are offered, and that the old mandated frame is *not* present. What that opening used to carry is now stated on its own: a Need may be a requirement but not a finished PLO.

**Three rules guard the opposite failure.** Every other rule pushes against a sentence too vague to draft a PLO from; these push against one that is a real demand generalised until it belongs to nobody. "ทักษะการสื่อสาร" clears every pure-code guard below and still describes no program in particular. The last of the three — could a reader still name the profession with the field removed? — cannot be code: the sentence is wrong only relative to the skill group it came from.

**Five more rules came from reading the stored corpus, not from a failure predicted in advance.** The apply Bloom label used to read "ประยุกต์ใช้ในงานจริงได้" — every stored apply-level Need came out wrapped as "ประยุกต์ใช้ <resource> ในการ <task>" because the model was copying the label's own verb. The label was reworded ("นำไปลงมือทำงานจริงได้"), and a dedicated **wrapper rule** forbids that sentence shape directly regardless of level, asking for the task as the main verb with the resource moved into a "โดยใช้..." clause. An **actor rule** rejects a sentence describing what the institution or its management does (building partnerships, setting policy) rather than what one new graduate does. An **off-profession rule** rejects another profession's work (building a translation tool, in a translation program) as the sentence's main task — *using* that tool to do this profession's own work is still fine. Members excluded by either rule go to `not_covered_indices` with a reason code (`low_freq` / `not_graduate` / `off_task`) rather than disappearing silently — the same never-fail, log-only measurement discipline as `supporting_indices`, never stored, never able to fail the call. Two smaller rules forbid a level qualifier unless most of the group shares it, and a floating quantifier ("หลายด้าน") in place of naming which ones. The qualifier rule is on the same majority test as the context-only-when-shared rule above, not "absent from every member's name" — measurement showed that bar is wrong: stored PLO2's "อย่างลึกซึ้ง" is present, in 1 of that Need's 18 member names ("การตรวจทานคำศัพท์เทคนิคเฉพาะทางกฎหมายอย่างลึกซึ้ง"), and another stored Need's "ขั้นสูง" came from 1 of 15 — both one-member outliers generalised into the whole sentence. Only "เชิงลึก" was invented outright, in none of its group's 3 names.

**`designer_input_used`** records whether the optional designer note changed a word choice (`used: bool`, `detail_th`), under the same discipline: logged once per run (`need_combination.run`), never stored — there is no threshold yet, only a first distribution to look at, same as `supporting_indices` below.

> ข้อความเต็มของ prompt นี้อยู่ใน [`docs/prompt-inventory.md`](../../../../docs/prompt-inventory.md)
> ซึ่ง `scripts/dump_prompts.py` render จาก builder จริง ไม่ได้คัดลอกด้วยมือ

**Output validation (pure code, drives Instructor retries).** `need_combination._NeedStatement` rejects the following, and each raised message names what it found so the retry prompt can quote it:

| Check | Implemented by | Rejects |
|---|---|---|
| No code identifiers | `need_grouping.find_code_identifier` | `หน.getDefault`, `get_default`, `calculate()`, `กลยุทธ์chant` |
| Long enough to carry three parts | `MIN_STATEMENT_CHARS` (40) | `ตลาดต้องการคนเก่ง` |
| Not a joined list | `need_grouping.looks_like_a_skill_list` | more than 2 commas, or more than one list boundary opening a `การ`/`ความ` phrase — Thai enumerates with spaces and `และ`, not commas |
| Names a capability | `need_grouping.find_vague_phrase` | `ทักษะที่จำเป็น`, `ด้านต่างๆ`, `ตามที่ตลาดต้องการ`, `ความสามารถทางวิชาชีพ`, `ทักษะการทำงาน` (the last two only when nothing continues them: `ทักษะการทำงานเป็นทีม` passes) |

If every attempt fails, `stages/need_combination.py` writes a comma-joined skill-name list prefixed `[ต้องทบทวน]` — deliberately the shape the validator rejects, so it cannot pass for a usable Need, and marked so the designer fixes it at the checkpoint instead of `plo_synthesis` guessing from a list of words.

---

## Stage 5 (plo_synthesis): one Need → one PLO (the most important prompt)

**Purpose:** restate one or more market Needs (post-`need_combination`) as a single graduate-side PLO. Called once per Need by the stage loop (list of length 1), and reused by the designer-driven `POST /programs/{id}/plos/from-needs` endpoint with a longer list when the designer chooses to merge several Needs into one PLO — same function, same rules, whether it's 1 Need or several.

**Model:** `plo_synthesis` (`complete_plo_synthesis`, its own `PLO_SYNTHESIS_PROVIDER`/`PLO_SYNTHESIS_MODEL`) — not clustering's. The two were one slot until they had to go different ways: clustering wants the larger model, while a PLO statement is Thai a designer submits to MHESI under their own name. Both the draft call and the SMART repair call go through this slot, so a repair is never answered by a different model than wrote the draft. Config-switchable per project policy, never hardcoded

**File:** `prompts/stage_3_plo.py` — `build_plo_from_need_prompt(metadata, needs, note_th=None)`

**The acronyms are spelled out, in Thai.** `MHESI` reaches a model as four letters that could stand for anything, and one that cannot place which ministry's standard it is writing to falls back on generic learning-outcome phrasing. The whole prompt is Thai and the default provider serves Thai-first models, so the Thai name is the form the model has actually read in curriculum documents. Same reason `OBE` and `PLO` each carry one clause of definition rather than being assumed.

> ข้อความเต็มของ prompt นี้อยู่ใน [`docs/prompt-inventory.md`](../../../../docs/prompt-inventory.md)
> ซึ่ง `scripts/dump_prompts.py` render จาก builder จริง ไม่ได้คัดลอกด้วยมือ

`plo_id` and `source_evidence_ids` are deliberately absent from the draft schema. Each is computed in code: the id by `format_plo_id`/`next_plo_id`, the evidence trail as the union of the contributing Needs' own verified `source_evidence_ids`. Asking the model for either invited it to contradict the data — it answered "PLO1" for every Need (collapsing a whole set into one upserted row) and invented evidence ids that pointed nowhere. Program context (`{name_th}`, `{degree_level}`, `{duration_years}`, `{field}` from `ProgramMetadata`) is included in the real prompt; see the file for the exact block. There is no `{vision_th}` — the vision reaches synthesis as evidence behind a Need, not as a metadata field.

Both templates take an optional `note_th`. When present it is appended to the **user** message under `ข้อกำหนดเพิ่มเติมจากผู้ออกแบบหลักสูตร:`; the system message carries an unconditional line saying the note guides wording and does not override the rules above it. See `prompts/designer_note.py`.

Every draft this prompt produces goes past the validation agent and then the pure-code gate (below) before it becomes a persisted `PLO` — this prompt alone does not guarantee a SMART-passing statement.

---

## plo_synthesis: the duplicate check before drafting

`prompts/need_dedup.py`. The text is in `docs/prompt-inventory.md` §8; this is why it says what it says.

- **Labels, not ids.** Needs are sent as `N1`, `N2`, … in demand order. A UUID is 36 characters the model has to copy exactly; short indices are what a model returns reliably (`supporting_indices` showed the same).
- **A duplicate is the same main task and main object**, whatever the wording or context — the checkable definition the 2026-09-29 pipeline proposal gives for set-level redundancy, with its example pair.
- **"Same topic, same tool, same source is not enough."** The evidence-overlap measurement is why: Needs drawn from the same documents share much of their evidence while asking for different things, and a model left to its own reading groups them the same way.
- **An empty answer is named as valid.** A model asked to find duplicates otherwise finds some.
- **The structural rules are stated and then enforced again in code** (`accept_groups`). Stating them keeps a good grouping from being thrown away for a rule the model never saw; enforcing them keeps a bad one from reaching synthesis.

---

## SMART validation agent prompts

**Purpose:** the S/M/R **hard** criteria (the declared verb appears in the statement, no forbidden word used, non-empty evidence trail) are never checked by an LLM at all — they are pure code in `stages/smart_rules.py` (`hard_failures()`), because they are mechanically checkable and a model is a slower, less reliable way to check them. The agent covers the five **soft** verdicts that genuinely need judgement, and instructs the repairs that fix the hard ones.

**Model:** validation (`complete_validation`) — its own slot, and specifically not `heavy` (clustering) or `synthesis` (which writes the Thai).

**File:** `prompts/smart_agent.py` — `build_smart_agent_prompt`, `build_tool_observation`, `build_refusal_observation`, `build_repair_observation`, `build_agent_repair_prompt`.

**Shape.** A structured action loop, not native tool-calling: Instructor is in `Mode.JSON` for every slot, so reading a `tool_calls` envelope would mean hand-parsing JSON or keying the shared client cache on `(provider, mode)`, and it would tie the loop to providers that implement tool-calling when running the whole pipeline on one endpoint is supported. The model answers one `ValidationStep` per turn — `reasoning_th` first, so it reasons before it commits — carrying a discriminated action: `call_tool`, `request_repair`, or `finish`. The loop executes the action and appends the result as the next user turn. A malformed action is a Pydantic `ValidationError`, which Instructor re-asks with the error attached.

The five soft verdicts in `finish` ask exactly what the old judge asked, and the four clauses with scar tissue behind them are unchanged: `measurable_ok` is about a real instrument and not about wording ("การไม่มีคำห้ามยังไม่นับว่าวัดได้"), `relevant_needs_ok` is judged against the Needs shown and nothing else ("ห้ามอ้างกรอบอื่นที่ไม่ได้แสดงไว้"), `time_bound_ok` defaults true, and `วิสัยทัศน์` appears nowhere. `tests/unit/test_smart_agent_prompt.py` pins all four — they are how `obe-principles.md` is held in place, and the prompt is a new place it could drift silently.

**What the prompt says it cannot do.** The system message states outright that the code-decided criteria cannot be declared passed and that the code re-checks the final statement, because a model that believes it can sign off on M spends its turns arguing instead of instructing a repair. It also states that the agent does not write the sentence itself.

`build_agent_repair_prompt` has **no `note_th` parameter**, and adding one would be a mistake. The designer's note reaches the draft prompt and nothing else; that invariant used to rest on `_build_fix_prompt` happening not to take the argument, and now rests on the signature. `ValidationContext` omits the note for the same reason — a validator that could read it could relay the wording into an instruction, and the note would reach a repair prompt second-hand.

The repair prompt carries the instruction, the original statement, the declared Bloom level and verb, and nothing else — no tool results, no sibling PLOs, no rubric recital. The model that wrote the diagnosis is not the model that writes the fix, so the instruction has to stand on its own. It repeats the forbidden-word list, because a repair is the last model call before a statement ships, and it asks for `action_verb_th` to follow the sentence: a rewrite that changes the verb in the text but not the field fails S forever.

**Tool observations** are Thai text built by the same module, so no prompt string is inlined in stage code. `build_repair_observation` reports the rewrite **and** the code's verdict on it, both before and after — handed only the new sentence, the agent would have to trust its own reading of a criterion pure code had just decided, and could not tell a rewrite it likes from one that passes.

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

**The count is enforced by the stage, never by asking nicely.** PLO synthesis never asks the model for a target PLO count — it calls the per-Need prompt once per Need, one PLO out per Need in. The 6-10 policy is applied around that loop: a core count below `MIN_NEEDS` (6) logs a policy warning for the checkpoint, and above `MAX_CORE_PLOS` (10) the stage synthesizes only the 10 highest-`demand_score` core Needs and names the rest in a warning. If a prompt anywhere asks an LLM to directly produce "a set of N PLOs", that's a regression to the old batch-synthesis design — don't reintroduce it.

**Never let a clustering/merge prompt cross a KSEC bucket.** Every skill-name clustering and merge call in `need_combination` is invoked per-bucket by the caller (`stages/need_grouping.py`'s `bucket_by_ksec`) — the prompt itself never receives skills from more than one KSEC tag at a time. If you add a new grouping prompt, bucket before you call it; don't rely on prompt wording to keep tags apart, since a model asked nicely can still mix them and there is no downstream check that would catch it.
