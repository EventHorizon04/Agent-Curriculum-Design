# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Curriculum Design Agent

AI agent that helps Thai higher-education curriculum designers produce programs meeting MHESI (กระทรวงอุดมศึกษา) standards and Outcome-Based Education (OBE) principles. The agent runs a 6-stage pipeline (intake → stakeholder needs → skill extraction → need combination → PLO synthesis → PLO report) with human-in-the-loop review at every stage boundary — except skill extraction and need combination, which share one checkpoint placed after need combination. **The agent's scope ends at PLO** — YLO and CLO derivation are faculty work and the code for them has been removed.

**Current state:** Proof-of-concept implemented. All modules under `src/`, Docker DB services, React UI, FastAPI backend, test suite, migrations, and exporters are in place. The codebase matches the design below — read existing code before adding new files.

## Skill

The `curriculum-design-agent` skill (`.claude/skills/curriculum-design-agent/`) is the canonical source for OBE rules, prompt templates, data schemas, and architectural decisions. **When working on PLO/OBE content, prompts, or schemas, defer to that skill.** This CLAUDE.md is the project-local operating manual — paths, commands, conventions. The skill is the domain manual.

## Stack

- **Language:** Python 3.11+, dependency management via `uv`
- **Agent:** LangGraph (state machine with `interrupt` for HITL)
- **LLM:** Ollama running **natively on the host** (no Ollama container) serving Typhoon 2 8B (light) + Qwen 2.5 7B/14B (heavy). Dual-model pattern — see `src/curriculum_agent/llm.py`
- **Structured output:** Instructor + Pydantic v2 (no hand-parsing JSON). The `openai` package is a dependency because Instructor uses OpenAI-compatible API to talk to Ollama — not for the OpenAI cloud service.
- **Clustering:** LLM-based (heavy model) — no embeddings/KeyBERT/Qdrant on this branch; see docs/superpowers/specs/2026-07-18-llm-only-pipeline-design.md
- **Storage:** PostgreSQL (structured), MinIO (raw files)
- **API/UI:** FastAPI backend, React 19 + Vite + TypeScript + Tailwind frontend in `frontend/`
- **Deployment:** Hybrid for the PoC — postgres/minio/pgadmin in Docker Compose, Ollama and the API/UI run natively

## Running it

```powershell
# First-time setup
cp .env.example .env        # edit LIGHT_MODEL / HEAVY_MODEL if needed

# Pull models (Ollama runs natively on the host)
ollama pull scb10x/typhoon2-8b-instruct
ollama pull qwen2.5:7b      # or :14b if VRAM >= 8GB

# Install dev dependencies
uv sync --all-extras

# Start everything: Docker DB services + Alembic migrations + uvicorn
.\scripts\start-dev.ps1

# React UI (separate terminal) — http://localhost:5173
cd frontend; npm run dev

# Stop services
.\scripts\stop-dev.ps1
```

```bash
# Run tests (asyncio_mode = "auto" — no @pytest.mark.asyncio needed)
uv run pytest                              # all tests
uv run pytest tests/unit/test_models.py    # validators only
uv run pytest -k "plo"                     # PLO-related tests

# Lint & format
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run mypy src/

# Frontend lint & build
cd frontend && npm run lint && npm run build

# Run API manually (against Docker services) if not using start-dev.ps1
uv run uvicorn curriculum_agent.api.main:app --reload
```

## Seed data

The `Data/` directory holds real-world inputs used during the stakeholder needs and skill extraction stages:

- `Data/Occupation Data.xlsx` — Thai job-market occupation taxonomy
- `Data/Skills.xlsx` — structured skill taxonomy aligned with the occupation data
- `Data/linkedin_offers2026-04-30.csv` — scraped LinkedIn job postings (April 2026 snapshot) for skill-frequency analysis

These files feed the extraction pipeline; do not reformat them without checking scraper/parser compatibility.

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

1. **The agent stops at PLO.** OBE chain is PLO → YLO → CLO, but YLO/CLO are faculty work. Never add YLO/CLO generation back.
2. **Every PLO must trace to evidence.** `source_need_ids` and `source_evidence_ids` are non-empty. Pydantic validators enforce this; do not weaken them.
3. **Forbidden words in PLO statements:** รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก. The Pydantic model rejects these (exception: a PLO with `smart_escalated=True` is kept for human repair) — do not bypass.
4. **One Bloom action verb per outcome.** Two verbs allowed only if at adjacent levels.
5. **SMART gate on every synthesized PLO.** Hard criteria (S verb-in-statement, M no-forbidden-word, R evidence-resolves) drive an automated retry loop (max 3, criterion named in the retry prompt) — an unfixed PLO is marked `smart_escalated` for human repair, never silently dropped. Soft criteria (S object quality, A level plausibility, R vision alignment) become `soft_flags` for human review and never block.
6. **At least 6 main PLOs per program, mapped one-to-one from main Needs — no upper cap.** `need_combination` no longer merges core groups down to a quota; every core group clustering finds within a KSEC bucket becomes its own Need, and PLO synthesis then drafts exactly one PLO per Need. A core count below 6 (`MIN_NEEDS` in `stages/need_grouping.py`) logs a policy warning for the designer to address at the checkpoint. Optional PLOs synthesized from want-based Needs (`is_optional=True`) are exempt from this count.
7. **Human-in-the-loop at every stage boundary — except one shared checkpoint.** Stages never auto-chain into the next without checkpoint approval; the one exception is skill_extraction → need_combination, which run back-to-back and share a single checkpoint after need_combination so the designer reviews raw skills and distilled Needs together.
8. **Open-source LLM by default.** Paid APIs (Claude, GPT-4o) are config-switchable for synthesis stages but never hardcoded.

## Project layout

```
src/curriculum_agent/
  models.py            ← Pydantic schemas (PLO, Need, ExtractedSkill, etc.)
  graph.py             ← LangGraph state machine, HITL interrupts
  llm.py               ← Ollama client, dual-model routing
  config.py            ← pydantic-settings, reads .env
  prompts/             ← one file per LLM prompt, typed builder fns
  stages/              ← intake, stakeholder_needs, skill_extraction,
                          need_combination, llm_clustering, plo_synthesis,
                          plo_report (+ smart_rules)
  data/                ← repositories, postgres, minio_store
  scrapers/            ← per-site job scrapers
  parsers/             ← document parsers (Tika, มคอ.1)
  exporters/           ← CHECO, มคอ.2, Excel matrix
  api/                 ← FastAPI routes
frontend/              ← React UI (one page per stage + Pipeline)
scripts/               ← start-dev.ps1 / stop-dev.ps1
tests/unit/            ← validators, schema, pure functions
tests/integration/     ← LLM mocked, full stages
```

## Where to find things

- **OBE rules / Bloom verbs / SMART criteria (hard/soft rubric)** → skill `references/obe-principles.md`
- **Prompt templates for any stage** → skill `references/prompts.md`, then mirrored in `src/curriculum_agent/prompts/`
- **Data schema decisions** → skill `references/data-schemas.md`, implemented in `src/curriculum_agent/models.py`
- **SMART hard checks (pure code)** → `src/curriculum_agent/stages/smart_rules.py`
- **Service config** → `docker-compose.yml`, `.env.example`
- **DB schema** → managed by Alembic in `migrations/`. Never edit DB by hand.

## Common pitfalls

- **Don't bypass the SMART retry loop after synthesis.** The synthesis LLM will produce plausible-looking PLOs that fail SMART. Hard checks are pure code (`smart_rules.py`); the soft judge is a separate light-model prompt. Escalated PLOs must stay visible in the UI.
- **Don't pass full evidence text into synthesis prompts.** Summarize each Need in ≤200 tokens. Full evidence stays in Postgres for drill-down, not in the synthesis prompt.
- **Never merge or cluster skills across a KSEC bucket.** `need_combination` buckets `ExtractedSkill`s by `ksec_category` before any clustering runs, and clustering stays inside one bucket. This is what makes "a Need has exactly one KSEC tag" a structural guarantee rather than a rule someone has to remember — don't add a grouping path that clusters across buckets, even to reduce the Need count.
- **Test Pydantic validators before integration tests.** They're the cheapest, most important guardrail. If a validator is wrong, every downstream test is suspect.
- **Don't `git push` model files.** Ollama models live on the host. `.env` files with API keys are gitignored — keep it that way.
- **Don't refactor the OBE flow to "save a stage."** Re-adding YLO/CLO generation, or collapsing plo_synthesis and plo_report, breaks the scope decision and CHECO compliance.

## When in doubt

Read the skill. Then check the relevant reference file. Then write code.
