# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Curriculum Design Agent

AI agent that helps Thai higher-education curriculum designers produce programs meeting MHESI (กระทรวงอุดมศึกษา) standards and Outcome-Based Education (OBE) principles. The agent runs a 6-stage pipeline (intake → stakeholder needs → skill extraction → need combination → PLO synthesis → PLO report) with human-in-the-loop review at every stage boundary — except skill extraction and need combination, which share one checkpoint placed after need combination. **The agent's scope ends at PLO** — YLO and CLO derivation are faculty work and the code for them has been removed.

Stakeholder needs no longer calls an LLM: evidence classification (`requirement` vs `general`) is a pure code lookup from `StakeholderType`. `need`/`want`/`unclassified` classification moved to the skill level, decided in `skill_extraction` once the whole corpus is in hand — see `stages/stakeholder_needs.py` and `stages/skill_extraction.py`.

Intake collects **program metadata only** — the fields the designer types, validated and stored. The form is ordered largest-unit-first (มหาวิทยาลัย → คณะ → สาขาวิชา/ภาควิชา), then degree level and duration, and that is the whole form. A program is identified by its place in the institution rather than by a name, so `program_id` is slugged from `field` (`_generate_program_id`) — a Thai field slugs to `program`, and the `-2`, `-3` collision suffix carries the distinction. Program names, goals, objectives, ISCED code, and professional council all stay on the model with empty defaults rather than being dropped: older rows keep their content, CHECO 1.5 keeps its source, and a client that supplies them is still accepted. The institution's vision/mission/philosophy/identity is recorded at stakeholder needs as evidence (`stakeholder_type=institutional_direction`), not as program fields.

**Current state:** Proof-of-concept implemented. All modules under `src/`, Docker DB services, React UI, FastAPI backend, test suite, migrations, and exporters are in place. The codebase matches the design below — read existing code before adding new files.

## Skill

The `curriculum-design-agent` skill (`.claude/skills/curriculum-design-agent/`) is the canonical source for OBE rules, prompt templates, data schemas, and architectural decisions. **When working on PLO/OBE content, prompts, or schemas, defer to that skill.** This CLAUDE.md is the project-local operating manual — paths, commands, conventions. The skill is the domain manual.

## Stack

- **Language:** Python 3.11+, dependency management via `uv`
- **Agent:** LangGraph (state machine with `interrupt` for HITL)
- **LLM:** three slots, each with its own provider — **light**, **heavy**, **extraction**. `LLM_PROVIDER` picks the endpoint for light and, unless moved, for extraction: `opentyphoon` (the default: Thai-first models, because every prompt and every stored statement here is Thai), `openrouter`, or `ollama` (running **natively on the host**, no container). Each hosted provider reads its own key (`OPENROUTER_API_KEY` / `OPENTYPHOON_API_KEY`); ollama needs none. **The heavy slot runs on its own endpoint** — `HEAVY_PROVIDER`/`HEAVY_MODEL`, defaulting to OpenRouter, called through `complete_heavy` — because `llm_clustering` and `plo_synthesis` are the two calls that reason over a whole KSEC bucket, or a Need plus a Bloom rubric, in one context, which is what a 30B Thai-first model is weakest at. `EXTRACTION_PROVIDER`/`EXTRACTION_MODEL` is the third knob and ships unset (so extraction follows `LLM_PROVIDER`); it exists on its own because extraction is the only stage that fans out one call per evidence item, so it is what exhausts a token quota first — move it when the Thai endpoint's quota is what runs out. Every provider field takes `None` to mean "follow `LLM_PROVIDER`", so one endpoint for everything is one line. Each model defaults from *its own* slot's provider (`_PROVIDER_DEFAULT_MODEL` in `config.py`), never from `LLM_PROVIDER`'s. `llm.describe_target()` prints all three endpoints a process resolved to — never the keys — and the API logs it once at startup. See `src/curriculum_agent/llm.py`
- **Structured output:** Instructor + Pydantic v2 (no hand-parsing JSON). The `openai` package is a dependency because Instructor uses OpenAI-compatible API to talk to Ollama — not for the OpenAI cloud service.
- **Clustering:** LLM-based (heavy model) — no embeddings/KeyBERT/Qdrant on this branch; see docs/superpowers/specs/2026-07-18-llm-only-pipeline-design.md
- **Storage:** PostgreSQL (structured), MinIO (raw files)
- **API/UI:** FastAPI backend, React 19 + Vite + TypeScript + Tailwind frontend in `frontend/`
- **Deployment:** Hybrid for the PoC — postgres/minio/pgadmin in Docker Compose, Ollama and the API/UI run natively

## Running it

```powershell
# First-time setup
cp .env.example .env        # edit LLM_PROVIDER / HEAVY_PROVIDER / models if needed

# Models (Ollama runs natively on the host). The defaults are ":cloud"-tagged,
# authenticated by the host's own session rather than by an API key:
ollama signin
# Running fully local instead? Pull the model and set it in .env:
# ollama pull qwen2.5:7b    # or :14b if VRAM >= 8GB

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

# Run API manually (against Docker services) if not using start-dev.ps1.
# Go through the package entrypoint, not the uvicorn CLI — on Windows the CLI
# creates its event loop before importing the app, and psycopg rejects the
# ProactorEventLoop that results. API_HOST / API_PORT / API_RELOAD configure it.
API_RELOAD=true uv run python -m curriculum_agent.api
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
2. **Every PLO must trace to evidence.** `source_need_ids` and `source_evidence_ids` are non-empty. Evidence itself only carries `requirement`/`general`; `need`/`want`/`unclassified` is decided per skill (`ExtractedSkill.classification`) once every evidence item is extracted, since frequency is a cross-evidence property. Pydantic validators enforce the non-empty trail; do not weaken them.
3. **Forbidden words in PLO statements:** รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก. The Pydantic model rejects these (exception: a PLO with `smart_escalated=True` is kept for human repair) — do not bypass.
4. **One Bloom action verb per outcome.** Two verbs allowed only if at adjacent levels.
5. **SMART gate on every synthesized PLO.** Hard criteria (S verb-in-statement, M no-forbidden-word, R evidence-resolves) drive an automated retry loop (max 3, criterion named in the retry prompt) — an unfixed PLO is marked `smart_escalated` for human repair, never silently dropped. Five soft verdicts (S object quality, M assessability, A level plausibility, R answers-its-Needs, T horizon) become `soft_flags` **and** set the matching `SMARTCheck` field, so `passed` means what it says; they never block.
6. **6-10 main PLOs per program, each drafted from one Need.** Both bounds live in `stages/need_grouping.py` — one policy, in the module whose clustering has to respect it. The floor (`MIN_NEEDS`) cannot be enforced by code — too few Needs simply means too few PLOs — so a core count below 6 logs a policy warning for the designer to address at the checkpoint. The ceiling (`MAX_CORE_PLOS`) is enforced **by choosing which Needs to use, not by merging them**: `need_combination` still turns every core group into its own Need, and synthesis takes the 10 highest `demand_score` ones. `need_combination` aims at the ceiling rather than overshooting it blindly: `allocate_cluster_targets` splits `MAX_CORE_PLOS` across the K/S/EC buckets in proportion to their unique skill names, and each bucket's clustering call is asked for about that many groups. It is a target, not a cap — `validate_assignments` still accepts whatever partition comes back, since a skill dropped to hit a number is worse than a Need over budget. The Needs that lose the cut stay stored and visible, still tracing to their evidence — they are unused, not deleted, and both the synthesis log and the PLO report name them. The bounds are a property of the **stored set**, not of one stage's output, and `POST /plos/from-needs` is checked against both. **A Need is behind at most one PLO**: the merge route supersedes every outcome citing a selected Need (`plos_citing`) and writes the merged one in its place, in a single transaction (`PLORepository.replace`). It used to append, which left a Need behind both its own outcome and the merged one — two PLOs claiming the same evidence read as two independent market demands in the มคอ.2 matrix when they are one. Because a merge replaces, it moves the core count in both directions: folding several outcomes into one lowers it, merging Needs nothing cites yet raises it, so the route refuses above `MAX_CORE_PLOS` and below `MIN_NEEDS` — the floor only when *this* merge causes the shortfall, so a program that started with too few Needs is not frozen. The merged outcome is numbered from the surviving ids, so it reuses the lowest slot it frees. A Need cited only by a superseded outcome returns to the pool and is logged. Optional PLOs from want-based Needs (`is_optional=True`) are outside both bounds, in synthesis and in the merge route alike.

   Which Needs are still available to merge is **derived, never stored** — `cited_need_ids` over the stored PLOs, used by both `plo_report` and the merge route. Deleting a PLO returns its Needs on its own, and no flag can outlive the outcome that set it.
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
  data/                ← repositories, postgres, minio_store,
                          prune_threads / prune_cache (maintenance sweeps)
  scrapers/            ← per-site job scrapers
  parsers/             ← document parsers (มคอ.1; the Tika parser went with
                          the intake document upload)
  exporters/           ← CHECO, มคอ.2, Excel matrix
  api/                 ← FastAPI routes
frontend/              ← React UI (one page per stage + Pipeline)
scripts/               ← start-dev.ps1 / start-demo.ps1 / stop-dev.ps1
                         (_api-process.ps1 holds the shared port/pid logic)
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
- **The extraction cache is keyed on `settings.extraction_model`, and so is what
  it stores.** One name in three places — the key, the hit comparison, and the
  `set` call. It was keyed on `light_model` and stored as `heavy_model` for as
  long as those resolved to the same string; the moment extraction moved to its
  own provider, every write became a permanent miss and the corpus was
  re-extracted at full cost on every run. `test_skill_extraction_cache.py`
  replays a stored entry rather than asserting each call site, because asserting
  them separately is exactly what let the mismatch through.
- **Evidence is read in windows, not as a prefix.** `skill_extraction` used to
  pass `raw_text_th[:1200]` to the model and log nothing about the rest, so a
  long สภาวิชาชีพ standard was read down to its first paragraph and could yield
  fewer skills than a short job posting. `chunk_evidence_text` splits an item
  into overlapping windows cut at word boundaries — `evidence_span_th` has to be
  quoted verbatim, and a half-word at a window edge is a span the model cannot
  quote — and every window is extracted under the existing concurrency ceiling.
  The cache is keyed on the window, so lengthening a document still hits on every
  window whose text did not move. `_MAX_CHUNKS` bounds what one pathological
  document costs, and whatever it leaves unread is logged against the evidence
  id; don't reintroduce a cap that says nothing.
- **`need_combination` reads the extracted skills plus the program's own context — never evidence text.** The sentence for each Need is written from its member
  skill names, and `demand_score` is computed from the evidence ids and
  stakeholder types carried on those skills. `POST /needs/combine/run` therefore does not load the
  evidence table at all and has no evidence precondition. Don't reintroduce
  `classified_evidence` here — extraction already read that evidence, and the raw
  quotes only gave the light model longer Thai to drift on. Traceability is
  unaffected: `Need.source_evidence_ids` still comes from the member skills.

  The one thing besides the skills that reaches both LLM calls is
  `build_program_context_th(state["metadata"])` — the field and degree level the
  designer typed at intake, as one Thai line ("หลักสูตรระดับปริญญาตรี สาขาพยาบาลศาสตร์").
  A bare skill name is ambiguous on its own: "การดูแล" groups with clinical work
  in a nursing program and with facility operations in an engineering one, and
  nothing else in either prompt says which program it is. It is metadata, not
  evidence, so it frames the reading and nothing more — the clustering prompt
  states outright that an off-field skill is still market demand and still
  belongs to exactly one group, and the summarize prompt forbids adding a
  capability the skill group never named, since the PLO drafted from that
  sentence has to trace to the evidence behind those skills. A program with no
  `field` gets `None` and the pre-context prompts byte-for-byte. The context is
  in the clustering **cache key** for the same reason `target_clusters` is: it
  reaches the prompt, so two programs whose skill names coincide must not share
  an entry.
- **`demand_score` is two blocks, not a table of per-type weights.**
  `0.30 × (สภาวิชาชีพ named it? 1 : 0) + 0.70 × share of the corpus that named it`
  — `stages/demand.py`. Only `PROFESSIONAL_COUNCIL` buys the mandate block, which
  is deliberately narrower than `models.REQUIREMENT_TYPES`: that set still holds
  `INSTITUTIONAL_DIRECTION` and still governs evidence and skill classification,
  but letting the institution's own voice buy the same 30% would let a faculty
  lift any Need's rank by restating its vision. Everyone else shares one class and
  is separated by frequency alone. Don't re-add per-type multipliers — the old
  1.0/0.8/0.6/0.4 table made every stored score depend on numbers nobody could
  defend, and the score now decides which Needs become PLOs.
- **A Need has to be usable as a PLO on its own.** `plo_synthesis` drafts exactly
  one PLO per Need and is handed nothing but `statement_th`, so a placeholder
  ("ทักษะที่จำเป็น") or a comma-joined skill list makes the synthesis model invent the
  capability with no evidence behind it. `need_combination._NeedStatement` enforces
  a length floor, the no-list rule, and `find_vague_phrase` on top of the
  code-token guard; Instructor retries with the offending phrase quoted. A group
  that still fails ships a `[ต้องทบทวน]`-marked fallback for the designer to rewrite —
  never a quietly-degraded Need. Keep the Need in the market's voice
  ("ตลาดแรงงานต้องการ..."); restating it from the graduate's side is `plo_synthesis`'s job.
- **A checkpoint thread has to be dropped explicitly.** LangGraph's rows live in
  their own `langgraph` schema with no foreign key back to `programs`, so
  `delete_cascade` cannot reach them — and a suspended checkpoint holds a full
  copy of the `AgentState`: evidence text, skills, Needs, PLOs. `graph.discard_thread`
  is the only thing that removes it, and both callers that end a thread's life
  use it: `DELETE /programs/{id}` (the `{program_id}` thread `create_program`
  starts, plus every session thread — read **before** the cascade deletes the
  rows those ids live on) and `POST /sessions/{id}/reject` (terminal by design,
  so nothing will ever resume it). It never raises: it runs after the deletion
  has committed, where a 500 would claim nothing was deleted — which is also why
  a failed drop leaks a thread. `uv run python -m curriculum_agent.data.prune_threads`
  reports what is unreachable (add `--delete` to drop it) and is the sweep for
  those, and for rows written before any of this existed.
- **A stale LLM cache row is invisible, not harmless.** `llm_cache` (formerly
  `llm_extraction_cache` — `llm_clustering` shares it with `skill_extraction`) is
  keyed on a hash of the input, the model, and a fingerprint of the prompt and
  response schema. That makes a stale entry impossible to hit and impossible to
  find: switch a slot's provider or edit a prompt and every row written before
  the change stays forever, unread. `kind` and `contract` are stored as columns
  for exactly that reason — both are already inside the key, so they change
  nothing about what gets hit; they exist so a sweep can say *why* a row is
  unreachable. `uv run python -m curriculum_agent.data.prune_cache` reports
  `stale-model` / `stale-contract` / `orphaned-kind` (add `--delete` to drop
  them), judging each row against the slot **its own kind** resolves to —
  extraction and clustering sit on different models, so one global "is this the
  current model" check would call half the table stale. `--older-than DAYS` is a
  separate flag because it reaches live rows too: it is the only sweep for the
  garbage no column can detect — evidence text edited in place, a program renamed
  or moved to another field (both are in the extraction key), a program deleted.
  `created_at` is never touched on overwrite, and that is deliberate: everything
  deciding the payload is in the key, so a second write stores the value already
  there and the first computation is the row's real age.
- **Never merge or cluster skills across a KSEC bucket.** `need_combination` buckets `ExtractedSkill`s by `ksec_category` before any clustering runs, and clustering stays inside one bucket. The buckets are `K`, `S`, `EC` — `E` and `C` skills deliberately share the `EC` bucket, and `resolve_need_ksec` hands back a standalone `E` or `C` for a group whose members turn out to be purely one of them. This is what makes "a Need has exactly one KSEC tag" a structural guarantee rather than a rule someone has to remember — don't add a grouping path that clusters across buckets, even to reduce the Need count.
- **Don't classify evidence with an LLM.** `requirement` is derived in code from
  `StakeholderType` (`classify_evidence_type`); `need`/`want`/`unclassified` are
  decided per skill in `skill_extraction.classify_skills` after every evidence item
  has been extracted, because frequency is a cross-evidence property. Re-adding a
  per-item classification call reintroduces both the cost and the wrong question.
- **Requirement wins.** A skill named by สภาวิชาชีพ or by the program's own
  vision stays `requirement` even when the extraction model marked it off-field.
  Do not reorder those precedence rules.
- **The institution's direction is evidence, not metadata.** Vision, mission,
  philosophy, and both identity statements are recorded at stakeholder needs
  under `stakeholder_type=institutional_direction` — they are not
  `ProgramMetadata` fields, and intake does not convert them into evidence
  anymore. It follows that R's institutional component is a program-level
  check on `Need.source_stakeholder_types`, not a per-PLO text comparison
  against a vision string: the old similarity flag fired on every PLO in a set
  and told the designer nothing. Don't re-add `vision_th` to a prompt.
- **Test Pydantic validators before integration tests.** They're the cheapest, most important guardrail. If a validator is wrong, every downstream test is suspect.
- **Don't `git push` model files.** Ollama models live on the host. `.env` files with API keys are gitignored — keep it that way.
- **Don't refactor the OBE flow to "save a stage."** Re-adding YLO/CLO generation, or collapsing plo_synthesis and plo_report, breaks the scope decision and CHECO compliance.

## When in doubt

Read the skill. Then check the relevant reference file. Then write code.
