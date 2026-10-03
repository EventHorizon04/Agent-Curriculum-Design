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
- **LLM:** six slots, each **named after the stage that calls it** and each with its own provider — **extraction**, **clustering**, **need_combination**, **need_dedup**, **plo_synthesis**, **validation**, in pipeline order. A slot is declared once, in `SLOTS` (`config.py`), and the defaults, the resolved provider, the startup line and the warm-up list are all derived from that one entry — **including which model it runs on**, via `SlotSpec.default_models`, keyed by provider because a model name only means something at one endpoint. That is where a model choice belongs: it is an engineering decision about the stage (extraction is chosen on how faithfully a model quotes, since `is_grounded` drops an invented span), so it lives in the repository under review rather than in one machine's `.env`. A `*_MODEL` env var still wins, which is what a probe or an outage needs; it is not where a lasting choice goes. `.env` holds secrets and what differs between machines, and `APP_ENV=production` refuses the development credentials `config.py` ships (`_refuse_development_credentials_in_production`) rather than letting a deployment that forgot one start anyway and look healthy; `tests/unit/test_llm_slots.py` walks the list against `Settings.model_fields`, because a field named as a string is what mypy cannot check. The names used to be sizes — `light`, `heavy`, `synthesis` — and both had drifted from what they do: `heavy` was only ever clustering, and `light` had one caller left. Old env names are **refused, not ignored** (`_reject_renamed_slot_settings`): `extra="ignore"` would otherwise make a `.env` still carrying `HEAVY_MODEL` a line nobody reads, and the run would start on a provider default while the operator believed they had selected a model. `LLM_PROVIDER` is the fallback for any slot left unset and nothing else: `opentyphoon` (the default: Thai-first models, because every prompt and every stored statement here is Thai), `openrouter`, or `ollama` (running **natively on the host**, no container). Each hosted provider reads its own key (`OPENROUTER_API_KEY` / `OPENTYPHOON_API_KEY`); ollama needs none. **`EXTRACTION_PROVIDER`/`EXTRACTION_MODEL`** (default OpenRouter, `complete_extraction`) is the fan-out stage: one call per *window* of every evidence item, so it exhausts a token quota before any other stage has run — and it ran the Thai endpoint's out. It gives up little by moving, since extraction names skills rather than writing prose anyone reads. **`CLUSTERING_PROVIDER`/`CLUSTERING_MODEL`** (default OpenRouter, `complete_clustering`) is `llm_clustering` and nothing else — it holds a whole KSEC bucket in one context and returns a grouping rather than prose, so there is nothing Thai to lose by moving it off the 30B model. It is the one OpenRouter slot that pins `meta-llama/llama-3.3-70b-instruct` instead of the provider-wide default (`z-ai/glm-5.3-flash` since 2026-10-01): glm was tried here and its hidden reasoning took 473s for the clustering calls on the stored corpus — 375s on the 53-name S bucket alone — past `need_combination`'s 300s route timeout, and bounding the reasoning turns it off on this endpoint, leaving a grouping nobody has measured. llama is also what ticket 16 measured this slot on. **`NEED_COMBINATION_PROVIDER`/`NEED_COMBINATION_MODEL`** (`complete_need_combination`) writes the Thai sentence for each Need, the one sentence `plo_synthesis` is later handed. Its provider ships **unset**, so it follows `LLM_PROVIDER` — it is the slot that had no provider field at all until the rename, which left `LLM_PROVIDER` doing two jobs (the fallback for every unset slot, and this slot's actual endpoint) and meant it could not be moved without moving all of them. Pinning it to `opentyphoon` now would look like the same thing and quietly stop being it the moment `LLM_PROVIDER` moved. **`NEED_DEDUP_PROVIDER`/`NEED_DEDUP_MODEL`** (default OpenRouter `z-ai/glm-5.3-flash`, `complete_need_dedup`) is the duplicate check at the start of `plo_synthesis`: one call per run that reads every in-scope Need and groups the ones asking for one capability. The model is pinned there on the probe against the stored Needs: llama-3.3-70b (the clustering model) folded all nine in-scope Needs into four units every run — a trio joining the top-demand digital-marketing Need with two translation-tool Needs, and a pair joining a consumer-culture Need with an academic-translation Need, neither sharing a main task and object — while glm-5.3-flash folded only the two genuine pairs, stably over three runs. It returns labels, not Thai prose, and `accept_groups` judges the answer in code. Like validation it is `disableable` — `NEED_DEDUP_PROVIDER=` (empty) skips it and every Need gets its own slot. **`PLO_SYNTHESIS_PROVIDER`/`PLO_SYNTHESIS_MODEL`** (default OpenTyphoon, `complete_plo_synthesis`) is `plo_synthesis` — both the draft call and the SMART repair call, so a repair is never answered by a different model than wrote the draft. **It and clustering are separate knobs on purpose:** they were one `heavy` slot until they had to go different ways — clustering wants the larger model, while a PLO statement is Thai a designer submits to MHESI under their own name — and sharing one knob meant neither could move without the other. **`VALIDATION_PROVIDER`/`VALIDATION_MODEL`** (default OpenRouter, `complete_validation`) is the SMART validation agent — the only slot that runs a tool-using multi-turn loop, and deliberately not clustering's: a slot sharing that knob could not be moved without moving clustering. It reasons over a Thai sentence plus a set of tool results rather than writing Thai, and when it decides a statement needs repair it emits an *instruction* that `complete_plo_synthesis` executes — so a repair is still never answered by a different model than wrote the draft. Setting `VALIDATION_PROVIDER` to the **empty string** skips the agent and keeps the pure-code verdict; that is the kill switch, and it reuses the fallback an endpoint outage needs anyway rather than a feature flag. This and need_dedup are the two slots where empty and unset differ, and the distinction is load-bearing: every other provider field only picks an endpoint, so `None` (unset) means "follow `LLM_PROVIDER`" for all six — but these two also answer *whether to run*, so `""` is off and `None` still follows. `""` is a member of their `Literal` for exactly that reason, need_dedup and validation are the only slots with `disableable=True`, `_apply_provider_model_defaults` and `_slot_provider` both leave them alone, and `describe_target()` prints `validation: disabled` (or `need_dedup: disabled`). Say "empty" and mean the empty string: the version that only documented it resolved `"" or llm_provider` back to a live provider, so the switch could not be thrown at all. Each model defaults from *its own* slot's provider (`_PROVIDER_DEFAULT_MODEL` in `config.py`), never from `LLM_PROVIDER`'s. `llm.describe_target()` prints all six endpoints a process resolved to (from `llm._slots()`, the one list `warmup_models` reads too) — never the keys — and the API logs it once at startup. See `src/curriculum_agent/llm.py`
- **Structured output:** Instructor + Pydantic v2 (no hand-parsing JSON). The `openai` package is a dependency because Instructor uses OpenAI-compatible API to talk to Ollama — not for the OpenAI cloud service.
- **Clustering:** LLM-based (the `clustering` slot) — no embeddings/KeyBERT/Qdrant on this branch; see docs/superpowers/specs/2026-07-18-llm-only-pipeline-design.md
- **Storage:** PostgreSQL (structured), MinIO (raw files)
- **API/UI:** FastAPI backend, React 19 + Vite + TypeScript + Tailwind frontend in `frontend/`
- **Deployment:** Hybrid for the PoC — postgres/minio/pgadmin in Docker Compose, Ollama and the API/UI run natively

## Running it

```powershell
# First-time setup
cp .env.example .env        # edit LLM_PROVIDER / CLUSTERING_PROVIDER / models if needed

# Models (Ollama runs natively on the host). The defaults are ":cloud"-tagged,
# authenticated by the host's own session rather than by an API key:
ollama signin
# Running fully local instead? Pull the model and set it in .env:
# ollama pull qwen2.5:7b    # or :14b if VRAM >= 8GB

# Install dev dependencies
uv sync --all-extras

# Three layers, three scripts. Data services, backend and UI start separately
# because they stop and restart on different schedules: a code change restarts
# the backend, and waiting on Docker for that is what the split is for.
.\scripts\start-services.ps1    # postgres + minio + alembic upgrade head
.\scripts\start-backend.ps1     # FastAPI. Refuses to run if the DB is down or
                                # the schema is behind — it starts no container.
.\scripts\start-frontend.ps1    # Vite on :5173. Foreground; Ctrl+C stops it,
                                # which is why there is no stop-frontend.

# Stopping, innermost first — the API has to let go of the database before the
# database goes away.
.\scripts\stop-backend.ps1
.\scripts\stop-services.ps1     # containers only; named volumes and their data stay

# Convenience wrappers, nothing of their own:
.\scripts\start-dev.ps1                  # = start-services, then start-backend
.\scripts\stop-dev.ps1                   # = stop-backend, then stop-services
.\scripts\stop-dev.ps1 -KeepServices     # stop the API, leave the DB up
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

# Run API manually (against Docker services) if not using start-backend.ps1.
# Go through the package entrypoint, not the uvicorn CLI — on Windows the CLI
# creates its event loop before importing the app, and psycopg rejects the
# ProactorEventLoop that results. API_HOST / API_PORT / API_RELOAD configure it.
API_RELOAD=true uv run python -m curriculum_agent.api
```

## Seed data

The `references/` directory (called `Data/` until 2026-09-17) holds real-world inputs used during the stakeholder needs and skill extraction stages:

- `references/Occupation Data.xlsx` — Thai job-market occupation taxonomy
- `references/Skills.xlsx` — structured skill taxonomy aligned with the occupation data
- `references/linkedin_offers2026-04-30.csv` — scraped LinkedIn job postings (April 2026 snapshot) for skill-frequency analysis

These files feed the extraction pipeline; do not reformat them without checking scraper/parser compatibility.

Two more files sit beside them and are **gitignored**: the TCISM stakeholder document and its human-authored answer key, the test set the scope-guard work was measured against. They are ignored **by basename, with no directory part** — writing the rule as `Data/<name>` is what let this very rename un-ignore a corpus of one institution's internal documents. Don't reintroduce a directory prefix there. Note this directory is unrelated to `.claude/skills/curriculum-design-agent/references/`, which holds the domain manual.

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
4. **One Bloom action verb per outcome.** Two verbs allowed only if at adjacent levels. Enforced in pure code on **`action_verb_th`**, not on the statement (`smart_rules.declares_too_many_verbs`) — see the pitfall below for why that is the only place it can be enforced.
5. **SMART gate on every synthesized PLO, and the last word is pure code.** Hard criteria (S statement-opens-with-the-declared-verb, S one-declared-verb, M no-forbidden-word-*used*, R evidence-resolves) are the **floor**: `validate_and_build` runs `hard_failures` on the final statement whatever else happened, and that call alone sets `smart_escalated`. An unfixed PLO is marked for human repair, never silently dropped. A **validation agent** (`stages/smart_agent.py`, its own `VALIDATION_*` slot) investigates through tools — the code verdict, the cited Needs, an excerpt of their evidence, the sibling outcomes, the Thai Bloom table — and instructs repairs (max 3 per PLO) that `complete_plo_synthesis` writes, then re-checks. It **cannot declare a hard failure passed**: `Finish` carries no field that clears one, and the code gate runs afterwards regardless, so its influence is monotone — it can shrink the failure list, never declare it empty. Seven soft verdicts (S object quality, M assessability, A level plausibility, A actor, A scope, R answers-its-Needs, T horizon) become `soft_flags` **and** set the matching `SMARTCheck` field, so `passed` means what it says; they never block. The two A additions fold into `achievable` rather than adding `SMARTCheck` fields, so no stored row changes shape: **actor** asks whether the doer is the graduate rather than the institution, **scope** whether the work belongs to this program's profession, judged against `scope_th` when the designer wrote one and otherwise against the intake field line — `scope_th` is empty on most programs, and a verdict that needed it would have been a no-op wherever it ran. Using another profession's tool for this profession's work (AI-assisted translation) is in scope; doing that profession's work (building the model) is not. When either fails because the *Need itself* is institutional or out of scope, the rubric forbids a repair and asks for a "send back to the Need stage" diagnosis instead: rewording cannot change what a Need asks for, and a repair spent on it is budget taken from the hard failures. Every failure is recorded as a `SmartFinding` with a Thai reason, and `smart_validated_by` says which validator produced the verdict — an outage yields `code_only` with no manufactured findings, because a validator that could not run must not escalate anything.
6. **6-10 main PLOs per program, each drafted from one Need — or from up to three same-KSEC Needs the duplicate check found to ask for one capability.** Both bounds live in `stages/need_grouping.py` — one policy, in the module whose clustering has to respect it. The floor (`MIN_NEEDS`) cannot be enforced by code — too few Needs simply means too few PLOs — so a core count below 6 logs a policy warning for the designer to address at the checkpoint. The ceiling (`MAX_CORE_PLOS`) is enforced **by choosing which Needs to use, not by merging them**: `need_combination` still turns every core group into its own Need, and synthesis takes the 10 highest `demand_score` ones. `need_combination` aims at the ceiling rather than overshooting it blindly: `allocate_cluster_targets` splits `MAX_CORE_PLOS` across the K/S/EC buckets in proportion to their unique skill names, and each bucket's clustering call is asked for about that many groups. It is a target, not a cap — `validate_assignments` still accepts whatever partition comes back, since a skill dropped to hit a number is worse than a Need over budget. The Needs that lose the cut stay stored and visible, still tracing to their evidence — they are unused, not deleted, and both the synthesis log and the PLO report name them. The bounds are a property of the **stored set**, not of one stage's output, and `POST /plos/from-needs` is checked against both. **A Need is behind at most one PLO**: the merge route supersedes every outcome citing a selected Need (`plos_citing`) and writes the merged one in its place, in a single transaction (`PLORepository.replace`). It used to append, which left a Need behind both its own outcome and the merged one — two PLOs claiming the same evidence read as two independent market demands in the มคอ.2 matrix when they are one. Because a merge replaces, it moves the core count in both directions: folding several outcomes into one lowers it, merging Needs nothing cites yet raises it, so the route refuses above `MAX_CORE_PLOS` and below `MIN_CORE_AFTER_MERGE` — the floor only when *this* merge causes the shortfall, so a program that started with too few Needs is not frozen. The merged outcome is numbered from the surviving ids, so it reuses the lowest slot it frees. A Need cited only by a superseded outcome returns to the pool and is logged. Optional PLOs (`is_optional=True`) are outside both bounds, in synthesis and in the merge route alike; `is_optional_group` decides which Needs those are, and the pitfall below says why it counts evidence items rather than member classifications.

   Merging — the automatic fold in `plo_synthesis` (`enforce_merge_floor`) and the merge route alike — may take the core count below 6 but not below `MIN_CORE_AFTER_MERGE` (4), unless the set was already below it; the 6-10 band and its warnings are unchanged. The fold is chosen before the ceiling, like the scope filter, so a slot freed by a fold goes to the next Need below the cut.

   Which Needs are still available to merge is **derived, never stored** — `cited_need_ids` over the stored PLOs, used by both `plo_report` and the merge route. Deleting a PLO returns its Needs on its own, and no flag can outlive the outcome that set it.
7. **Human-in-the-loop at every stage boundary — except one shared checkpoint.** Stages never auto-chain into the next without checkpoint approval; the one exception is skill_extraction → need_combination, which run back-to-back and share a single checkpoint after need_combination so the designer reviews raw skills and distilled Needs together.
8. **Open-source LLM by default.** Paid APIs (Claude, GPT-4o) are config-switchable for synthesis stages but never hardcoded.

## Project layout

```
src/curriculum_agent/
  models.py            ← Pydantic schemas (PLO, Need, ExtractedSkill, etc.)
  graph.py             ← LangGraph state machine, HITL interrupts
  llm.py               ← provider clients, per-slot model routing (SLOTS)
  config.py            ← pydantic-settings, reads .env
  prompts/             ← one file per LLM prompt, typed builder fns
  stages/              ← intake, stakeholder_needs, skill_extraction,
                          need_combination, llm_clustering, need_dedup,
                          plo_synthesis, plo_report (+ smart_rules, smart_agent,
                          smart_agent_tools, bloom_verbs)
  data/                ← repositories, postgres, minio_store,
                          prune_threads / prune_cache (maintenance sweeps)
  scrapers/            ← per-site job scrapers
  parsers/             ← document parsers (มคอ.1; the Tika parser went with
                          the intake document upload)
  exporters/           ← CHECO, มคอ.2, Excel matrix
  api/                 ← FastAPI routes
frontend/              ← React UI (one page per stage + Pipeline)
scripts/               ← one layer per script: start-services / start-backend /
                         start-frontend and their stops; start-dev + stop-dev
                         are wrappers, start-demo.ps1 is the tunnelled build.
                         (_api-process.ps1 holds the shared port/pid logic)
tests/unit/            ← validators, schema, pure functions
tests/integration/     ← LLM mocked, full stages
```

## Where to find things

- **OBE rules / Bloom verbs / SMART criteria (hard/soft rubric)** → skill `references/obe-principles.md`
- **The text of any prompt** → `docs/prompt-inventory.md`, generated from the builders by `scripts/dump_prompts.py` (`--check` fails when it is stale). **Why a prompt says what it says** → skill `references/prompts.md`. The reference used to carry copies of the prompts too, and all three had drifted; don't reintroduce one.
- **Data schema decisions** → skill `references/data-schemas.md`, implemented in `src/curriculum_agent/models.py`
- **SMART hard checks (pure code)** → `src/curriculum_agent/stages/smart_rules.py`; the forbidden-word scan and the finding codes → `src/curriculum_agent/smart_vocabulary.py`
- **The SMART validation agent** → `src/curriculum_agent/stages/smart_agent.py` (loop), `smart_agent_tools.py` (what it may see), `prompts/smart_agent.py`
- **Service config** → `docker-compose.yml`, `.env.example`
- **DB schema** → managed by Alembic in `migrations/`. Never edit DB by hand.

## Common pitfalls

- **Don't bypass the SMART gate after synthesis.** The synthesis LLM will produce plausible-looking PLOs that fail SMART. Hard checks are pure code (`smart_rules.py`) and the validation agent is a separate slot that instructs repairs rather than writing them. Escalated PLOs must stay visible in the UI.
- **The agent cannot pass itself, and `hard_failures` after the loop is why.**
  `validate_and_build` re-runs the pure checks on the final statement on every
  exit path — finished, out of budget, endpoint down — and that call sets
  `smart_escalated`. Delete it and immutable rule 5 becomes a request the model
  can decline: `Finish` has no field that clears a hard failure precisely
  because nothing downstream would notice if it did. `RequestRepair` has no
  `statement_th` for the same reason — the Thai a designer submits to MHESI
  comes from the synthesis slot, always, and a helpful model handed that field
  would make "a repair is never answered by a different model than wrote the
  draft" one field away from false.
- **Immutable rule 4 is enforced on `action_verb_th`, and a statement scan is
  what does not work.** `hard_failures` tested `action_verb_th in statement_th`
  and nothing else about verbs, so the rule was prompt text with no code behind
  it — and it broke at the field that declares the verb rather than in the
  sentence. Six of the nine stored PLOs declared a *phrase*
  ("ออกแบบและดำเนินการ", "ออกแบบและดำเนินการตรวจสอบ", "ตีความและอธิบาย"), and every
  one passed S, because synthesis writes the whole phrase into the sentence it is
  checked against. Scanning the statement instead is the obvious fix and the
  wrong one: Thai packs means and purpose into the same sentence, so
  `scan_statement_verbs` reports "โดยใช้เทคโนโลยี", "เพื่อสร้างคอนเทนต์" and the
  noun "แนวปฏิบัติ" beside the outcome verb — it flags six of the nine, four of
  them sound. The declared phrase has no subordinate clauses to mistake, and on
  it the check flags three, all genuine. **A phrase the table does not recognise
  passes**: `bloom_verbs` is a judgement call with no specialist review, its
  header says so, and a gap in a vocabulary this repo wrote alone must not
  escalate an outcome (stored OPT4 declares "ประพฤติตน"). Two verbs pass when
  *some* pair of their levels is adjacent, not every pair, because
  `levels_for_verb` returns a list exactly where the rubric says the object
  settles the level. `declares_too_many_verbs` is the only caller allowed to gate
  on that table; everything else it feeds stays advisory, and adding a verb to it
  now widens what this check rejects.
- **S checks that the statement *opens* with the declared verb, not that the verb
  appears somewhere in it.** The presence test passed a PLO that declared
  "ประยุกต์ใช้" while its outcome was "แปลและตรวจสอบเอกสาร…": the declared verb
  sat in the means clause ("โดยประยุกต์ใช้เทคโนโลยี AI"), the same Thai clause
  structure that makes a statement scan useless above. The opening is the one
  position a subordinate clause cannot take, so it is read after
  `strip_outcome_prefix` removes a "บัณฑิตสามารถ…" subject — on the stored set
  that check failed exactly the one PLO it should. The prefix itself is wording
  removed in code, not a failure: `plo_synthesis._adopt` strips it from every
  draft and repair, because it is the one door every shippable statement comes
  through, and spending one of three agent repairs on deleting a subject would
  take budget from the hard failures.
- **instructor edits the caller's message list, and the validation agent reuses
  one.** JSON mode appends the response schema to the system message *in place*
  — its `kwargs.copy()` is shallow — so the SMART loop, which keeps a single list
  for every turn, sent one more ~1,650-token schema per call: the same opening
  turn measured 5,773, 7,423, then 9,073 prompt tokens. `llm._complete` hands
  instructor a copy of each message, at the one place every slot goes through.
  `tests/unit/test_llm_request_shape.py` observes this below instructor, with only
  the HTTP transport mocked, because the loop's own tests replace the model with
  a fake that never reaches instructor and could not have seen it.
- **The validation model's hidden reasoning is bounded only after it runs away.**
  It spends one `max_tokens` on reasoning and on the answer; on stored OPT1 it
  reasoned for all 4,096 and answered nothing, two runs of two, which made the
  step malformed and the verdict `code_only` — every soft criterion lost. Bounding
  reasoning on every step fixed that and loosened the judgement: this endpoint
  treats any `reasoning.max_tokens` as off, and OPT8's out-of-scope flag fell from
  4/4 to 2/4. So `smart_agent._ask_step` asks unbounded, and on a truncation
  re-asks the same step bounded — no turn spent, not counted malformed — and keeps
  the bound for the rest of that PLO, since the input that set it off is still in
  the conversation. `_step_retrying` stops instructor retrying a truncation
  (its default retries every exception, and a runaway spent the step cap twice
  before the loop heard of it). A truncation *with* the bound is the answer
  outgrowing the cap, and takes the malformed path. `reasoning` is OpenRouter's
  field and is sent nowhere else. **This is not free, and the cost is still
  open.** Runaways are common and random even at temperature 0 — one or two of
  nine PLOs on one run, five of nine on another — and a PLO that ran away is
  judged bounded, which is the looser judgement: on the final run OPT8 ran away
  and lost its flag again. It is still strictly better than before, where the
  same PLO got `code_only` and no soft verdict at all (`code_only` went 3/9 →
  1/9, escalations 2 → 0), but a fix that lets a runaway PLO keep reasoning —
  a larger step cap on the re-ask, or a different validation model — has not
  been tried.
- **The forbidden-word check is about words *used*, not substrings.** Thai has
  no word boundaries, so `word in statement` flagged `รักษา` (holds รัก),
  `จำแนก`/`จำลอง` (จำ) and `ความรู้`/`เรียนรู้` (รู้). Each hard-failed M, burned
  all three repairs against a hint about a word the sentence never used, and
  escalated a sound outcome. `smart_vocabulary.forbidden_words_in` masks a
  curated compound list first, and both callers — `hard_failures` and
  `PLO.check_no_forbidden_words` — share it, because two independent scans of
  one rule is how they came to disagree. Don't reintroduce either the substring
  test or the second copy.
- **A verdict field is the validator's output, never a client's input.** `PUT
  /plos/{id}` used to accept a whole `PLO`, so a caller with the API key could
  set `smart_escalated=False` with an all-true `smart_check` on a statement no
  validator had ever passed. It now takes `PLOStatementUpdate` — text only —
  and marks an edited statement `stale` rather than letting it inherit the old
  verdict; `POST /plos/{id}/revalidate` is the way back to a real one. The next
  person who wants a quick edit path will be tempted to widen this again.
- **`PUT` still has to run the pure-code gate, because `model_copy` skips
  validators.** Marking an edited statement `stale` is not enough on its own:
  the row is written with whatever `smart_escalated` it already had, and every
  later read goes through `PLO.model_validate`, where the forbidden-word check
  stands down only for an escalated row. So one `PUT` of a statement containing
  `เข้าใจ` wrote the row, failed FastAPI's own response validation, returned
  500, and made `GET /plos/` raise for the whole program — `revalidate`
  included, since the way back was behind the same read that was failing.
  `hard_failures` is pure code and free, so the route runs it and stores a
  verdict the model will accept on the way back in. The invariant is not "PUT
  does not judge" — it is that whatever any route stores must be readable.
- **`soft_flags` stays `list[str]`.** Narrowing it to `SmartFindingCode` makes
  any row carrying a code this build no longer knows raise on read — and
  `R_alignment` was emitted for months — so one stale string would take out a
  whole program's PLO list on `GET /plos/` rather than one field. The typed
  detail lives in `smart_check.findings`, which rides inside the existing JSONB
  column and needed no migration for exactly this reason.
- **`PLORepository.list_by_program` orders its rows, and that is load-bearing.**
  `plo_id` carries meaning — PLO1 is the outcome drafted from the most-demanded
  Need, which is why synthesis keeps demand order through `asyncio.gather` and
  why `as_completed` is banned there. The read used to have no `ORDER BY`, so
  Postgres handed back heap order and an `UPDATE` moved that row to the end of
  it: revalidating one outcome silently reshuffled the exported มคอ.2 matrix and
  the UI list. `is_optional` first (OPT sorts above PLO lexicographically), then
  length before value (or PLO10 lands between PLO1 and PLO2).
- **Don't pass full evidence text into synthesis prompts.** Summarize each Need in ≤200 tokens. Full evidence stays in Postgres for drill-down, not in the synthesis prompt.
- **The extraction cache is keyed on `settings.extraction_model`, and so is what
  it stores.** One name in three places — the key, the hit comparison, and the
  `set` call. It was keyed on what is now `need_combination_model` and stored as
  what is now `clustering_model` (`light_model` and `heavy_model` at the time)
  for as long as those resolved to the same string; the moment extraction moved
  to its own provider, every write became a permanent miss and the corpus was
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
- **A missing input key and an empty one mean different things to a stage.** There
  are two ways to run any stage — the graph (`POST /sessions`) and the per-stage
  REST route a stage page calls — and they used to disagree about where the input
  comes from. The REST routes load it from the repositories and answer 422 when
  there is nothing to load; the graph passed it forward in `AgentState` alone, so
  a session started after some stages had been run by hand began from nothing:
  three stages each returned an empty list with only a warning, and the run died
  at `plo_synthesis` blaming `need_combination` — the one stage that had just run
  and returned normally. Now `state.get(key) is None` means "entered directly"
  and the stage loads its own input (`EvidenceRepository` /`SkillRepository` /
  `NeedRepository`), which is exactly what the REST route feeding it would have
  handed over. An **empty** list is the previous stage's answer and is refused,
  never answered by loading older rows — that would report success over a failed
  run. Every refusal is raised **before** `delete_by_program`, so a run that
  produces nothing still cannot wipe the previous run's rows. `skill_extraction`
  splits the empty case further: every provider call failing (quota, dead
  endpoint) raises, while the model reading the evidence and naming nothing keeps
  returning empty. `_run_graph` stores the raised message on the session row, so
  the Pipeline page says what a stage page's 422 would have said —
  `tests/unit/test_stage_preconditions.py` pins all of it.

- **`Need.rationale_th` is an explanation, not a trail.** The summarize call writes
  it alongside the sentence — why *these* skills are one demand — because that is
  what the model is deciding while it writes, and asked in a second call it would
  be reconstructed from the sentence instead. Traceability is unaffected and must
  stay that way: `source_evidence_ids` is assembled in code and is what immutable
  rule 2 is about, while this is free text nothing can check against the evidence.
  So the prompt forbids citing anything outside the skill names it was handed,
  both Need cards label it "คำอธิบายของโมเดล" and keep it out of the trail panel,
  and the `[ต้องทบทวน]` fallback writes a rationale saying there is none rather
  than a plausible one. `_NeedStatement` bounds it at 20-240 characters and
  rejects an empty answer ("เป็นทักษะที่เกี่ยวข้องกัน") with the same
  `find_vague_phrase` the statement uses — one rule, one scan. The field defaults
  to `""` on the model because a Need also arrives as a plain dict from a
  checkpoint suspended across the deploy; migration `c7e2f81a4b93` backfills a
  self-identifying `[สร้างย้อนหลัง]` sentence built from the row's own member
  count and KSEC tag, and joins nothing — a reason composed out of the member
  skill names would be an explanation no model ever gave, sitting in the field a
  reader takes as the justification.
- **`need_combination` reads the extracted skills plus the program's own context — never evidence text.** The sentence for each Need is written from its member
  skill names, and `demand_score` is computed from the evidence ids and
  stakeholder types carried on those skills. `POST /needs/combine/run` therefore does not load the
  evidence table at all and has no evidence precondition. Don't reintroduce
  `classified_evidence` here — extraction already read that evidence, and the raw
  quotes only gave the `need_combination` model longer Thai to drift on. Traceability is
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
- **`demand_score` is three blocks, and the two frequency blocks have separate
  denominators.** `0.20 × (สภาวิชาชีพ named it? 1 : 0) + 0.55 × share of the
  *practitioner* voices that named it + 0.25 × share of everyone else` —
  `stages/demand.py`. Only `PROFESSIONAL_COUNCIL` buys the mandate block, which is
  deliberately narrower than `models.REQUIREMENT_TYPES`: that set still holds
  `INSTITUTIONAL_DIRECTION` and still governs evidence and skill classification,
  but letting the institution's own voice buy the same block would let a faculty
  lift any Need's rank by restating its vision.

  **The mandate block is dead for most Thai programs, which is why it cannot be
  the only thing separating voices.** มคอ.1 was repealed wholesale by กฎกระทรวง
  2565, and the "มาตรฐานคุณวุฒิในสาขาวิชา" series กมอ. issued in its place covers
  the same council-backed fields (แพทยศาสตร์ 2566, เทคนิคการแพทย์/กายภาพบำบัด/
  เภสัชศาสตร์ 2567). A translation or humanities program has no external document
  that can ever buy it. The score was then one pooled frequency block, and pooled
  frequency **inverts** the ranking: a generic capability is one everybody can
  name, a specialist one is named only by the people who employ the graduate. On
  the stored TCISM run the top Need was "การเรียนรู้ตลอดชีวิต" (applicant,
  community, faculty, the faculty's own vision) while every real translation
  competency sat at the bottom on one employer each and was cut.

  `_PRACTITIONER_TYPES` — council, employer, industry, alumni, expert — is the
  line, and **it is not `STAKEHOLDER_GROUP`.** Splitting by external/internal was
  tried first and moved nothing: `APPLICANT` and `COMMUNITY` are external too, so
  an employer naming something alone scored exactly what a community voice naming
  something alone scored. `STAKEHOLDER_GROUP` stays a display label; don't
  "simplify" the scorer onto it. Each block is a share of its own audience, so
  adding applicant interviews cannot dilute what the employers said, and a block
  whose audience is absent contributes zero rather than redistributing its weight
  (same ordering, no branch that varies with corpus composition — and those two
  guards are also what answers an empty corpus, so there is no early return for
  it). An unknown stakeholder type is not a practitioner, so stored-data noise
  falls to the smaller block.

  This is a table mapping types to classes, and the rule it replaced said not to
  add one. What that rule forbids is still forbidden: the old 1.0/0.8/0.6/0.4
  *gradation*, per-type multipliers whose individual values nobody could defend
  and which moved every stored score when one was retuned. Two categorical
  classes with one stated question between them ("has this voice done the work?")
  is a different object — a type's class follows from the question, not from a
  number someone picked. If a new `StakeholderType` seems to need a *third*
  weight, the answer is a better question, not a third tier.
- **`is_optional` counts evidence items, not member classifications.** A Need is
  optional when nothing mandates it and exactly one evidence item asked for it
  (`is_optional_group` in `stages/demand.py`). The rule it replaced read
  `want > requirement + need` over the members, and that proxy never fired: a
  member is `need` only when its own skill *name* was extracted from more than one
  evidence item, and on the stored run all 91 normalised names came from exactly
  one each, so `need` was zero. The only remaining way to be core was to carry a
  `requirement`, which for any programme without a professional council comes from
  `INSTITUTIONAL_DIRECTION` alone — and the scope guard then drops those for not
  being graduate capabilities. Core finished at 1 against a floor of 6, while the
  groups those members formed drew on 7, 9 and 10 evidence items: clustering knows
  two phrasings are one capability and matching normalised strings cannot, so the
  old rule counted phrasings to answer a question about stakeholders. This is the
  second half of the bug `POST /evidence/` fixed the first half of, and that
  route's docstring is the other end of the story. `requirement` still wins
  outright — one mandated member makes a group core however small, because a
  mandate is not a matter of how many people repeated it — and `need` is subsumed
  rather than dropped, since a name in several evidence items means a group in
  several. `classification` is unchanged everywhere else; this rule simply stopped
  reading the group's answer out of it. One clause does still read it: a group
  whose members are **all** `unclassified` is optional. That class counts toward
  neither side, and under any rule of the shape "optional unless X" a neutral
  position is a core slot by default — the old rule gave one because `0 > 0` is
  false, and this one would give one to any such group drawn from two evidence
  items. The scope guard drops every one of them before synthesis, which is what
  makes it look free; it is not, because the band is a property of the stored set
  and `POST /plos/from-needs` checks against it, so the padding lands in a number
  the designer is judged against and cannot reach.
- **`supporting_indices` is self-report, and only its low end means anything.**
  The summarize call numbers the member names and asks which ones the sentence
  speaks for; `need_grouping.supporting_coverage` weighs the answer by mentions
  and `need_combination` logs it. It exists because a Need's trail claims every
  member's evidence whatever its sentence says — ticket 18 found a fifteen-name
  group whose sentence spoke for three — and the names used to arrive as one
  comma-joined string, so the sentence could not say what it covered at all.
  Measured against the stored Needs by eye, the model does discriminate (that
  fifteen-name group reported the lowest figure, 27%) but it **over-claims**,
  often by 1.5–3×: a ten-name group reporting 50% had a sentence covering one or
  two. So a low figure is a real alarm and a high one proves nothing, and any
  flag built on it must fire on low values with the inflation in mind. It also
  does not see the other large-group failure: a sentence that crams three
  capabilities together covers much of its group and scores high. The field is a
  measurement and must never cost a Need — no validator raises on it, and a
  `mode="before"` validator reduces a malformed answer to its integers or to
  `None` because pydantic's own `list[int]` check would otherwise fail the call
  and push a well-written sentence into a `[ต้องทบทวน]` fallback. `None` (no list)
  stays distinct from `0.0` (covers nothing). No threshold, column, or checkpoint
  flag yet: ticket 18 asks for the distribution before a number.
- **A Need's Bloom level is what most of its group asks for, not its top
  member.** `need_grouping.group_bloom` is the lower mention-weighted median of
  the members' levels; it replaced `merge_bloom`, the maximum, at the one call
  that combines *different* skills. On the stored run 21% of extracted skills
  were Create and 69% of Needs were — OPT2 was Create from 2 Create members of
  18, 9 of them Apply — and the level travels: it reaches the summarize prompt
  as "สร้างและออกแบบสิ่งใหม่ได้" and `plo_synthesis` as the level to write to,
  so five Needs and the five PLOs drafted from them all opened with ออกแบบ, for
  a bachelor's programme whose evidence is mostly Apply. The lower median means
  a level wins only with more than half the group behind it, which is the
  ceiling on Create the pipeline review asked for without a constant of its own.
  `merge_bloom` stays where its reason holds — two rows of *one* skill name, at
  extraction and at dedupe, where the lower level is implied by the higher.
  Stored Needs are not migrated: the level is written into the Need's sentence
  as well as its field, so only re-running need_combination changes what a PLO
  is drafted from.
- **A Need has to be usable as a PLO on its own.** `plo_synthesis` drafts exactly
  one PLO per Need and is handed nothing but `statement_th`, so a placeholder
  ("ทักษะที่จำเป็น") or a joined skill list makes the synthesis model invent the
  capability with no evidence behind it. `need_combination._NeedStatement` enforces
  a length floor, the no-list rule, and `find_vague_phrase` on top of the
  code-token guard; Instructor retries with the offending phrase quoted. A group
  that still fails ships a `[ต้องทบทวน]`-marked fallback for the designer to rewrite —
  never a quietly-degraded Need. **Both guards are counted in two shapes, because
  Thai writes each one differently from English.** `looks_like_a_skill_list` counts
  commas *and* list boundaries that open a นาม phrase (`การ`/`ความ` after a space or
  a spaced `และ`) — a comma count alone saw nothing in "ต้องการการใช้ AI การแปล
  และการตรวจแก้คำแปล", which is a joined list by any reading; it was only ever
  catching the model writing the list the English way. `find_vague_phrase` likewise
  matches a generic head fused to a generic domain word ("ความสามารถทางวิชาชีพ",
  "ทักษะการทำงาน") as well as the head-plus-`ที่`-modifier pairs. That second pattern
  carries a right-boundary lookahead the first does not need: "ที่จำเป็น" says nothing
  wherever it sits, but "ทักษะการทำงานเป็นทีม" names a real capability, and
  over-rejecting costs a retry and then a hand-written Need. **The prompt also carries the
  only rule that pushes the other way.** Everything above bounds how *vague* a Need
  may be and nothing bounded how *narrow* it may be, so "แปลสัญญาซื้อขายสินค้า" — one
  task inside a profession's work — satisfied every one of them. A Need becomes
  exactly one PLO against ten core slots, so one worth less than a tenth of the
  program spends a slot anyway. The bound is written as a property of the
  sentence's **object** (a class of work the graduate repeats, not one instance)
  rather than of its wording, and says outright that it does not license writing
  vaguely — a model told "too narrow" otherwise reaches for "ทักษะการสื่อสาร",
  which is what the dilution rule exists to stop. The two are tested together;
  removing either leaves the other unopposed. **A Need states a requirement; it must not be a
  finished PLO.** The opening is free — "ต้องการ...", "ต้องการบัณฑิตที่...",
  "ต้องการหลักสูตรที่..." and "บัณฑิตต้องมี..." are all fine, and the mandatory
  "ตลาดแรงงานต้องการ..." prefix is gone: it carried nothing the rest of the sentence
  did not and spent characters against the 40-character floor. What is still
  forbidden is the finished outcome form ("บัณฑิตวิเคราะห์...ได้"), because
  `plo_synthesis` receives only this sentence — a Need already written as a PLO
  leaves that stage nothing to do but copy, and the report can no longer show the
  step from what was asked for to what a graduate must therefore be able to do.
  The rule lives in `build_summarize_need_prompt` and is pinned by
  `test_summarize_need.py`; `_CIRCULAR_PHRASES_TH` is unaffected, since a trailing
  "ตามที่ตลาดต้องการ" says nothing whatever the sentence opened with.
- **Two Needs sharing evidence are not two Needs asking for one thing.** The
  duplicate check before synthesis (`stages/need_dedup.py`) reads the Need
  *sentences* through a model, because the free signal measured useless: on
  the stored run a marketing Need and an ethics Need shared 55% of their
  evidence while a true duplicate pair shared under 20% — a small corpus
  puts every Need on the same few documents. The model's answer is judged in
  `accept_groups`, not by pydantic validators (a validator failure fails the
  whole call and loses every good group with the bad one), and a group that
  breaks a rule — mixed KSEC, more than three members, a Need already taken —
  is dropped whole, never trimmed, since which member to cut is the judgement
  the model was asked for. The step can only fold: switched off, failing, or
  given one Need, it returns nothing and synthesis behaves as it did before it
  existed.
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
