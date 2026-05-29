---
name: curriculum-design-agent
description: Build, develop, or extend an AI agent that helps Thai higher-education curriculum designers create programs that meet กระทรวงอุดมศึกษา (MHESI) standards and Outcome-Based Education (OBE) principles. Use this skill whenever the user is working on curriculum design automation, PLO/YLO/CLO generation, OBE-aligned program design, Backward Curriculum Design, stakeholder needs analysis, skill extraction from job markets via data science (EDA, text mining, topic modeling, embeddings), or any task involving Thai LLMs (Typhoon, Qwen) for educational content. Trigger on phrases like "หลักสูตร", "PLO", "YLO", "OBE", "BCD", "curriculum agent", "stakeholder needs", "skill extraction", "Bloom taxonomy", "มคอ.", "CHECO", "AUN-QA", or when designing/coding any component of this specific agent system. Also trigger when the user asks to scaffold, prompt, schema, or wire up any stage of the pipeline.
---

# Curriculum Design Agent — Development Skill

## What this skill builds

An AI agent that helps Thai higher-education curriculum designers produce programs meeting MHESI (กระทรวงอุดมศึกษา) standards and OBE (Outcome-Based Education) principles. The agent runs a 5-stage pipeline:

1. **Intake** — gather program metadata (field, degree level, duration, vision, professional council, accreditation body)
2. **Stakeholder needs discovery** — collect from job postings, professional standards, alumni feedback, MHESI subject benchmarks (มคอ.1)
3. **Data-science skill extraction** — EDA, keyword extraction, topic modeling, embedding-based clustering to find truly high-demand skills, distinguishing *needs* from *wants*
4. **PLO synthesis** — convert skill clusters into SMART Program Learning Outcomes using Bloom Taxonomy verbs, balancing subject-specific and generic outcomes
5. **YLO derivation** — break each PLO across years 1–4 with progressive Bloom levels (NOT directly into CLO), aligning with CHECO format

The agent is human-in-the-loop: each stage produces output that the curriculum designer reviews before the next stage runs.

## When the user is working on this, what to do

**First, identify which stage they're on.** The 5 stages have different needs — read the right reference file before generating code or content:

- Architecture, tech choices, model selection → `references/tech-stack.md`
- OBE concepts, PLO/YLO/Bloom rules, SMART criteria, MHESI alignment → `references/obe-principles.md`
- Writing LLM prompts for any stage → `references/prompts.md`
- Pydantic schemas, data models, evidence trail → `references/data-schemas.md`
- Stage-by-stage implementation plan → `references/development-phases.md`

For any non-trivial coding task on this project, **read the relevant reference file first** before writing code. The references encode design decisions that matter — for example, why YLO is derived before CLO, why we use dual-model strategy, and which Thai NLP libraries handle which job. Don't rely on memory of these decisions.

## Core design commitments — never violate these

Some decisions are load-bearing. If the user asks something that conflicts with these, surface the conflict before complying:

**OBE flow is fixed: PLO → YLO → CLO, never PLO → CLO directly.** This is the central design choice. The agent stops at YLO and hands off to humans for CLO. Year-level outcomes (YLO) align with CHECO's "ความคาดหวังเมื่อสิ้นปีการศึกษา" requirement and provide the road map showing Bloom-level progression across years.

**Every PLO must trace back to stakeholder evidence.** Fabricated PLOs that look plausible but lack evidence will fail accreditation review. The system must keep an evidence trail: stakeholder source → extracted skill → cluster → PLO. Use `StakeholderEvidence` and `SkillCluster` models from `references/data-schemas.md`.

**SMART + single Bloom action verb per outcome.** Avoid the words รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก in any PLO/YLO — they are unmeasurable. Use one observable action verb per outcome from Bloom Taxonomy. See `references/obe-principles.md` for the verb list.

**Thai language is primary.** All user-facing artifacts (PLO, YLO, exported documents) are in Thai. Use Thai-aware LLMs (Typhoon, Qwen) and Thai-aware NLP (PyThaiNLP) — not generic English tooling. Code, comments, and variable names can be English.

**Human-in-the-loop at every stage boundary.** The agent never auto-runs all 5 stages. Each stage produces a checkpoint where the designer reviews and can edit before the next stage. Implement this with LangGraph's interrupt mechanism.

**Open-source first, paid as fallback.** Default to Typhoon/Qwen via Ollama. Allow a config switch to swap in proprietary APIs (Claude, GPT-4o) for the synthesis-heavy stages 3–4 if the user has budget. Never hardcode a paid API as the only option.

## Tech stack at a glance

For full justification and alternatives, see `references/tech-stack.md`.

- **LLM serving (PoC):** Ollama running Typhoon 2 8B for light tasks, Qwen 2.5 32B (or Llama 3.3 70B Q4) for synthesis. Production: vLLM.
- **Agent orchestration:** LangGraph (state machine with interrupt for human review). Pydantic + Instructor for structured output.
- **Thai NLP:** PyThaiNLP for tokenization/normalization, WangchanBERTa optional, BGE-M3 for embeddings (handles Thai well).
- **Skill extraction:** KeyBERT + BERTopic + scikit-learn. Pandas/Polars for EDA. DuckDB for analytical queries on job-posting corpora.
- **Vector store:** Qdrant (PoC + production) or pgvector if Postgres is already deployed.
- **Data acquisition:** Playwright for JS-heavy sites, BeautifulSoup + httpx for simple, Apache Tika or unstructured.io for PDFs/Word.
- **Backend/UI:** FastAPI + Streamlit (PoC). Next.js if production polish is needed.
- **Storage:** PostgreSQL for structured (PLO, YLO, versions), MinIO for raw files, DuckDB for ad-hoc analytics.
- **Deployment:** Docker Compose for PoC, Kubernetes only at scale.

## Development phases

For detailed week-by-week breakdown, see `references/development-phases.md`.

- **Phase 1 (4–6 weeks): MVP, single field, manual data input.** Prove the pipeline works end-to-end on one program (e.g. Computer Science) with hand-curated job postings and standards. UI in Streamlit.
- **Phase 2 (4–6 weeks): Automated data acquisition.** Add scrapers for 2–3 job sites, document parsing for มคอ.1 and council standards. Move to Qdrant. Implement evidence trail.
- **Phase 3 (4 weeks): Production hardening.** CHECO/มคอ.2 export, PLO/YLO version control, multi-tenant if multiple faculties, vLLM serving, evaluation framework comparing agent output to human-designed curricula.

## Coding patterns to follow

When implementing any stage:

1. **Define Pydantic models first.** Every artifact (Program, Stakeholder, SkillCluster, PLO, YLO, EvidenceTrail) has a schema in `references/data-schemas.md`. Use them to type LLM output via Instructor.

2. **Use the dual-model pattern for cost control.** Light tasks (classify, extract, summarize) → Typhoon 8B. Heavy reasoning (PLO synthesis, YLO Bloom progression) → Qwen 32B or larger. Wire model choice through config, not hardcoded.

3. **Each stage is an isolated LangGraph node** with typed input and output. Stages don't reach into each other's state — they pass data forward only. This makes individual stages testable and replayable.

4. **Always preserve evidence.** When a skill becomes a cluster becomes a PLO becomes a YLO, the chain of citations must be retrievable. Store `source_ids: list[str]` on every derived artifact.

5. **Prompts go in `prompts.md`, not inline.** When generating any LLM prompt for this project, base it on a template from `references/prompts.md`. If a template doesn't exist for the task, create one in that file.

## When generating code

If creating a new file in this project, start with these defaults unless the user specifies otherwise:

- Language: Python 3.11+
- Project structure: src/ layout (`src/curriculum_agent/...`)
- Type hints: required, use Pydantic for data models
- LLM client: `instructor` patched on top of `openai` client pointed at Ollama (`base_url="http://localhost:11434/v1"`)
- Logging: `loguru` for simplicity, structured JSON in production
- Config: `pydantic-settings` reading from `.env`
- Testing: `pytest` with fixtures for mocked LLM responses

A starter `docker-compose.yml` and project skeleton are in `scripts/`. Read them before scaffolding new infrastructure.

## What this skill does NOT cover

- General LLM prompt engineering (use the prompting skill or web docs)
- Generic agent design patterns unrelated to OBE/curriculum (use LangGraph docs)
- Thai language teaching content (this is for designing curricula, not teaching)
- Course-level outcome (CLO) derivation — by design, the agent stops at YLO

If the user asks about something outside scope, answer briefly and note that this skill is curriculum-design-agent-specific.

## Quick orientation

User said "let's start" → read `references/development-phases.md`, propose Phase 1 plan
User asked about a model choice → read `references/tech-stack.md`
User wants to write a PLO/YLO prompt → read `references/prompts.md` and `references/obe-principles.md`
User wants to define data shape → read `references/data-schemas.md`
User asked "is this a good PLO?" → check it against the SMART + Bloom rules in `references/obe-principles.md`
User wants Docker setup → read `scripts/docker-compose.yml` template

Pull the right file, then act. Don't try to remember everything from this SKILL.md alone.
