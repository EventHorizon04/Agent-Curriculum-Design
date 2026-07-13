---
name: curriculum-design-agent
description: Use when working on any component of this curriculum design agent — writing or reviewing PLOs, building stage prompts, defining data schemas, or coding pipeline stages. Triggers on "หลักสูตร", "PLO", "OBE", "stakeholder needs", "skill extraction", "Bloom", "SMART", "มคอ.", "CHECO", "AUN-QA", or any request to generate/validate learning outcomes.
---

# Curriculum Design Agent — Domain Skill

## What this project builds

An AI agent helping Thai higher-education curriculum designers produce programs meeting MHESI standards and OBE principles. 5-stage pipeline, human-in-the-loop at every boundary:

1. **Intake** — program metadata (field, degree level, duration, vision, professional council)
2. **Stakeholder needs** — collect evidence from job postings, professional standards, alumni feedback, มคอ.1; classify each item need/requirement/want
3. **Skill extraction** — EDA, keyword extraction, embedding clustering, Bloom-level tagging; want-heavy clusters marked optional
4. **PLO synthesis** — convert core skill clusters into 6–10 SMART PLOs using Bloom verbs, plus an optional non-blocking pass producing 1–4 supplementary PLOs from want-based clusters
5. **PLO report** — classify PLOs generic vs specific for designer review and export

**The agent's scope ends at PLO.** OBE chain is PLO → YLO → CLO, but YLO/CLO are faculty work. If asked to generate YLOs or CLOs, surface the scope boundary before complying.

## Read the right reference first

- OBE concepts, Bloom verbs, SMART criteria, forbidden words → `references/obe-principles.md`
- Writing or modifying any LLM prompt → `references/prompts.md`
- Pydantic schemas, evidence trail → `references/data-schemas.md`

Don't rely on memory of these rules — read the file before generating PLO content, prompts, or schemas.

## Rules that catch real failures

Agents without this skill reliably make these mistakes. Check every learning-outcome output against:

1. **Exactly 6–10 main PLOs.** Optional PLOs synthesized from want-based clusters (`is_optional=True`, ids prefixed `OPT`) are exempt from this count.
2. **One Bloom action verb per outcome statement.** "ออกแบบและพัฒนา" or "อธิบายและประยุกต์ใช้" = two verbs = reject. Two verbs allowed only at adjacent Bloom levels, and prefer one.
3. **Every PLO carries evidence.** `source_cluster_ids` / `source_evidence_ids` non-empty. A PLO drafted "from general knowledge" without stakeholder evidence is a fabrication that fails accreditation — don't produce one, even as a placeholder.
4. **Forbidden words** in any outcome statement: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก. Replace with observable verbs (เข้าใจ → อธิบาย/วิเคราะห์).
5. **Every PLO passes all five SMART checks before it leaves PLO synthesis.** S (one Bloom verb + named, non-generic object), M (no forbidden word), and R-evidence (non-empty trail) are **hard fails** that trigger the SMART retry loop (max 3 attempts, retry prompt names the violated criterion). A (Bloom level plausible for qualification/resources) and R-alignment (vision/mission fit) are **soft fails** that surface as human-review flags, not blockers. Full rubric with Thai definitions and pass/fail examples in `references/obe-principles.md` — implement any `SMARTValidator` against that file, don't re-derive from memory.
6. **Balance:** 60–70% subject-specific, 30–40% generic PLOs.
7. **Thai is primary** for all student-facing statements. Code and comments in English.

## Coding patterns

- Pydantic models first; type LLM output via Instructor. Schemas in `references/data-schemas.md`.
- Dual-model: light tasks (classify/extract) → Typhoon 8B; synthesis → heavy model. Wire through config.
- Each stage is an isolated LangGraph node with typed I/O; HITL via `interrupt`.
- Prompts based on templates in `references/prompts.md`; new prompts get added there and mirrored in `src/curriculum_agent/prompts/`.

## Out of scope

YLO/CLO derivation (by design), general prompt engineering, generic agent patterns, teaching content. Project paths/commands/stack live in CLAUDE.md, not here.
