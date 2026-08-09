---
name: curriculum-design-agent
description: Use when working on any component of this curriculum design agent — writing or reviewing PLOs, building stage prompts, defining data schemas, or coding pipeline stages. Triggers on "หลักสูตร", "PLO", "OBE", "stakeholder needs", "skill extraction", "Bloom", "SMART", "มคอ.", "CHECO", "AUN-QA", or any request to generate/validate learning outcomes.
---

# Curriculum Design Agent — Domain Skill

## What this project builds

An AI agent helping Thai higher-education curriculum designers produce programs meeting MHESI standards and OBE principles. 6-stage pipeline, human-in-the-loop at every stage boundary except one shared checkpoint (see stage 3/4 below):

1. **Intake** — where the program sits, nothing else. The form asks for the institutional hierarchy largest-first (มหาวิทยาลัย → คณะ → สาขาวิชา/ภาควิชา), then degree level and duration. A program is identified by that hierarchy, not by a name: `program_id` is slugged from `field`, and `name_th`/`name_en`, `program_goals_th`, `program_objectives_th`, `isced_code`, `professional_council` all remain on the model — accepted by the API, populated on older rows — but have no input. The institution's own vision/mission/philosophy/identity is **not** metadata: the designer records it at stage 2 as evidence under `stakeholder_type=institutional_direction`, which is what a PLO the institution's direction demands traces to.
2. **Stakeholder needs** — collect evidence from job postings, professional standards, alumni feedback, มคอ.1, and 15 stakeholder types split external/internal (`STAKEHOLDER_GROUP`); classify each evidence item `requirement`/`general` — a pure code lookup from `StakeholderType` (`classify_evidence_type`), no LLM call. `need`/`want`/`unclassified` is not decided here at all — see stage 3.
3. **Skill extraction** — grounded LLM extraction per evidence item: each skill carries a verbatim quote (`evidence_span_th`) verified to actually occur in its source evidence, plus an `is_field_relevant` judgement from the same call; ungrounded skills are dropped. After the whole corpus is extracted, `classify_skills` assigns each skill name `requirement`/`need`/`want`/`unclassified` in pure code, since that classification depends on cross-evidence frequency
4. **Need combination** — group extracted skills into core Needs (at least 6, no upper cap, plus optional want-based Needs), one KSEC tag per Need, grouping and merging always within a single KSEC bucket (`K`, `S`, `EC`), never across. Shares one human-review checkpoint with stage 3 — the designer reviews raw skills and distilled Needs together
5. **PLO synthesis** — one focused LLM call per Need, mapping each core Need to one SMART PLO one-to-one (at least 6, no upper cap), plus a designer-driven endpoint to merge several Needs into one PLO; an optional non-blocking pass produces supplementary PLOs from want-based Needs
6. **PLO report** — no classification. Assembles the reviewable report (every PLO with its Bloom level, KSEC tag, SMART soft flags, escalation status, evidence drill-down) and exports CHECO/มคอ.2

**The agent's scope ends at PLO.** OBE chain is PLO → YLO → CLO, but YLO/CLO are faculty work. If asked to generate YLOs or CLOs, surface the scope boundary before complying.

## Read the right reference first

- OBE concepts, Bloom verbs, SMART criteria, forbidden words → `references/obe-principles.md`
- Writing or modifying any LLM prompt → `references/prompts.md`
- Pydantic schemas, evidence trail → `references/data-schemas.md`

Don't rely on memory of these rules — read the file before generating PLO content, prompts, or schemas.

## Rules that catch real failures

Agents without this skill reliably make these mistakes. Check every learning-outcome output against:

1. **At least 6 main PLOs, no upper cap.** `need_combination` no longer merges core groups down to a quota — every core group clustering finds becomes its own Need, and PLO synthesis then maps one Need to one PLO, so the count carries through unchanged. A core count below 6 logs a policy warning for the designer to address at the checkpoint. Optional PLOs synthesized from want-based Needs (`is_optional=True`) are exempt from this count.
2. **One Bloom action verb per outcome statement.** "ออกแบบและพัฒนา" or "อธิบายและประยุกต์ใช้" = two verbs = reject. Two verbs allowed only at adjacent Bloom levels, and prefer one.
3. **Every PLO carries evidence.** `source_need_ids` / `source_evidence_ids` non-empty. A PLO drafted "from general knowledge" without stakeholder evidence is a fabrication that fails accreditation — don't produce one, even as a placeholder.
4. **Forbidden words** in any outcome statement: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก. Replace with observable verbs (เข้าใจ → อธิบาย/วิเคราะห์).
5. **Every PLO passes all five SMART checks before it leaves PLO synthesis.** Three **hard fails** drive the retry loop (max 3 attempts, retry prompt names the violated criterion): S-verb (exactly one Bloom action verb present), M-forbidden (no forbidden word), R-evidence (non-empty trail). Five **soft verdicts** come from the light-model judge — `specific_object_ok`, `measurable_ok`, `achievable_ok`, `relevant_needs_ok`, `time_bound_ok` — and never block; they land in `soft_flags` *and* in the matching `SMARTCheck` field, so `SMARTCheck.passed` reflects a flagged outcome instead of reporting success. R has a third, institutional component that is settled structurally: `plo_synthesis.run` warns once at program level if no Need behind any PLO carries `institutional_direction`. Full rubric with Thai definitions and pass/fail examples in `references/obe-principles.md` — implement any `SMARTValidator` against that file, don't re-derive from memory.
6. **Thai is primary** for all student-facing statements. Code and comments in English.

## Coding patterns

- Pydantic models first; type LLM output via Instructor. Schemas in `references/data-schemas.md`.
- Dual-model: light tasks (classify/extract) → Typhoon 8B; synthesis → heavy model. Wire through config.
- Each stage is an isolated LangGraph node with typed I/O; HITL via `interrupt`.
- Prompts based on templates in `references/prompts.md`; new prompts get added there and mirrored in `src/curriculum_agent/prompts/`.

## Out of scope

YLO/CLO derivation (by design), general prompt engineering, generic agent patterns, teaching content. Project paths/commands/stack live in CLAUDE.md, not here.
