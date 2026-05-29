# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Curriculum Design Agent

AI agent that helps Thai higher-education curriculum designers produce programs meeting MHESI (กระทรวงอุดมศึกษา) standards and Outcome-Based Education (OBE) principles. The agent runs a 5-stage pipeline (intake → stakeholder needs → data-science skill extraction → PLO synthesis → YLO derivation) with human-in-the-loop review at every stage boundary. It stops at YLO and hands off to faculty for course-level outcomes.

**Current state:** Proof-of-concept implemented. All modules under `src/`, Docker services, Streamlit UI, FastAPI backend, test suite, migrations, and exporters are scaffolded and in place. The codebase matches the design below — read existing code before adding new files.

## Skill

The `curriculum-design-agent` skill (`.skill` file in the repo root) is the canonical source for OBE rules, prompt templates, data schemas, and architectural decisions. **When working on PLO/YLO/OBE content, prompts, or schemas, defer to that skill.** This CLAUDE.md is the project-local operating manual — paths, commands, conventions. The skill is the domain manual.

## Stack

- **Language:** Python 3.11+, dependency management via `uv`
- **Agent:** LangGraph (state machine with `interrupt` for HITL)
- **LLM:** Ollama serving Typhoon 2 8B (light) + Qwen 2.5 32B (heavy). Dual-model pattern — see `src/curriculum_agent/llm.py`
- **Structured output:** Instructor + Pydantic v2 (no hand-parsing JSON). The `openai` package is a dependency because Instructor uses OpenAI-compatible API to talk to Ollama — not for the OpenAI cloud service.
- **Thai NLP:** PyThaiNLP for tokenization, BGE-M3 for embeddings
- **Skill extraction:** KeyBERT + BERTopic + scikit-learn
- **Vector store:** Qdrant
- **Storage:** PostgreSQL (structured), MinIO (raw files), DuckDB (analytics)
- **API/UI:** FastAPI backend, Streamlit frontend
- **Deployment:** Docker Compose for PoC

## Running it

```bash
# First-time setup
cp .env.example .env        # edit LIGHT_MODEL / HEAVY_MODEL if needed
docker compose up -d

# Pull models on first start
docker exec ca-ollama ollama pull scb10x/typhoon2-8b-instruct
docker exec ca-ollama ollama pull qwen2.5:14b   # or :32b if 24GB+ VRAM

# Install dev dependencies
uv sync --all-extras

# Run DB migrations (required before first API start)
uv run alembic upgrade head

# Run tests (asyncio_mode = "auto" — no @pytest.mark.asyncio needed)
uv run pytest                              # all tests
uv run pytest tests/unit/test_models.py    # validators only
uv run pytest -k "ylo"                     # YLO-related tests

# Lint & format
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/

# Run API locally (against Docker services)
uv run uvicorn curriculum_agent.api.main:app --reload

# Run UI locally (against Docker services)
uv run streamlit run streamlit_app/app.py
```

## Seed data

The `Data/` directory holds real-world inputs used during Stage 2 (stakeholder needs) and Stage 3 (skill extraction):

- `Data/Occupation Data.xlsx` — Thai job-market occupation taxonomy
- `Data/Skills.xlsx` — structured skill taxonomy aligned with the occupation data
- `Data/linkedin_offers2026-04-30.csv` — scraped LinkedIn job postings (April 2026 snapshot) for skill-frequency analysis

These files feed the NLP pipeline; do not reformat them without checking scraper/parser compatibility.

## Architecture diagrams

- `docs/diagrams/curriculum_agent_architecture_poc.svg` — component diagram of the PoC (services, data flows, LLM routing)
- `docs/diagrams/curriculum_design_agent_workflow.svg` — stage-by-stage workflow with HITL checkpoints

Read these before touching `graph.py` or the stage handlers.

## Code conventions

- **Type hints required.** Every function signature. Use `from __future__ import annotations`.
- **Pydantic v2** for anything crossing a boundary (LLM I/O, API requests, DB rows).
- **`loguru`** for logging. Don't import the stdlib `logging` module directly.
- **Async-first** in API and stage handlers. Sync only for pure CPU work (NLP, math).
- **No hand-parsing LLM JSON.** Always go through Instructor → Pydantic.
- **Thai for student-facing strings.** Code, comments, variable names, log messages: English.
- **Repository pattern** for data access — `src/curriculum_agent/data/repositories.py`. Don't sprinkle SQL throughout.
- **Prompts live in `src/curriculum_agent/prompts/`**, one file per prompt, returned by typed builder functions. Don't inline prompts in stage code.

## Immutable rules

These are project decisions. If a request conflicts with one, surface the conflict before complying.

1. **PLO → YLO → CLO. Never PLO → CLO directly.** The agent stops at YLO. CLO is faculty work.
2. **Every PLO/YLO must trace to evidence.** `source_cluster_ids` and `source_evidence_ids` are non-empty. Pydantic validators enforce this; do not weaken them.
3. **Forbidden words in PLO/YLO statements:** รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก. The Pydantic model rejects these — do not bypass.
4. **One Bloom action verb per outcome.** Two verbs allowed only if at adjacent levels.
5. **Bloom level monotonically non-decreasing across years for the same PLO.** `YLOMatrix.validate_coverage()` enforces this.
6. **Human-in-the-loop at every stage boundary.** Stages never auto-chain into the next without checkpoint approval.
7. **Open-source LLM by default.** Paid APIs (Claude, GPT-4o) are config-switchable for synthesis stages but never hardcoded.

## Project layout

```
src/curriculum_agent/
  models.py            ← Pydantic schemas (PLO, YLO, SkillCluster, etc.)
  graph.py             ← LangGraph state machine, HITL interrupts
  llm.py               ← Ollama client, dual-model routing
  config.py            ← pydantic-settings, reads .env
  prompts/             ← one file per LLM prompt, typed builder fns
  stages/              ← intake, stakeholder_needs, skill_extraction, plo_synthesis, ylo_derivation
  data/                ← repositories, postgres, qdrant, minio_store
  nlp/                 ← thai_tokenizer, embedding, extraction (KeyBERT/BERTopic)
  scrapers/            ← per-site job scrapers
  parsers/             ← document parsers (Tika, มคอ.1)
  exporters/           ← CHECO, มคอ.2, Excel matrix
  api/                 ← FastAPI routes
streamlit_app/         ← UI pages (one per stage)
tests/unit/            ← validators, schema, pure functions
tests/integration/     ← LLM mocked, full stages
```

## Where to find things

- **OBE rules / Bloom verbs / SMART criteria** → curriculum-design-agent skill `references/obe-principles.md`
- **Prompt templates for any stage** → skill `references/prompts.md`, then mirrored in `src/curriculum_agent/prompts/`
- **Data schema decisions** → skill `references/data-schemas.md`, implemented in `src/curriculum_agent/models.py`
- **Tech stack rationale & alternatives** → skill `references/tech-stack.md`
- **Phase plan / what to build next** → skill `references/development-phases.md`
- **Service config** → `docker-compose.yml`, `.env.example`
- **DB schema** → managed by Alembic in `migrations/`. Never edit DB by hand.

## Common pitfalls

- **Don't skip the SMART validator after Stage 3 generation.** The synthesis LLM will produce plausible-looking PLOs that fail SMART. The validator is the safety net — a separate prompt run on a smaller model.
- **Don't pass full evidence text into Stage 3 prompts.** Summarize each cluster in ≤200 tokens. Full evidence stays in Postgres/Qdrant for drill-down, not in the synthesis prompt.
- **Don't ask the model for "as many PLOs as needed."** Always 4–6. More leads to overlap.
- **Test Pydantic validators before integration tests.** They're the cheapest, most important guardrail. If a validator is wrong, every downstream test is suspect.
- **Don't `git push` model files.** Ollama models live in the Docker volume. `.env` files with API keys are gitignored — keep it that way.
- **Don't refactor the OBE flow to "save a stage."** Skipping YLO and going straight from PLO to CLO is the single most common bad idea. It breaks CHECO compliance.

## When in doubt

Read the skill. Then check the relevant reference file. Then write code.
