# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Curriculum Design Agent

AI agent that helps Thai higher-education curriculum designers produce programs meeting MHESI (กระทรวงอุดมศึกษา) standards and Outcome-Based Education (OBE) principles. The agent runs a 6-stage pipeline (intake → stakeholder needs → skill extraction → need combination → PLO synthesis → PLO QA review loop → PLO report), whose middle is two chained agents (Agent 1: skill extraction + skill grouping; Agent 2: need combination), with human-in-the-loop review at every stage boundary — except Agent 1 → Agent 2, which are two chained jobs with no checkpoint between them (the checkpoints are evidence, Need on its own `need_analysis` stage, and PLO), and the PLO tail — synthesis and the QA review loop run as one tail, the designer approves the reviewed set at the PLO checkpoint (stage `plo_review`), and the report is built last from what they approved. **The agent's scope ends at PLO** — YLO and CLO derivation are faculty work and the code for them has been removed.

Stakeholder needs no longer calls an LLM: evidence classification (`requirement` vs `general`) is a pure code lookup from `StakeholderType`. `need`/`want`/`unclassified` classification moved to the skill level, decided in `skill_extraction` once the whole corpus is in hand — see `stages/stakeholder_needs.py` and `stages/skill_extraction.py`.

Intake collects **program metadata only** — the fields the designer types, validated and stored. The form is ordered largest-unit-first (มหาวิทยาลัย → คณะ → สาขาวิชา/ภาควิชา), then degree level and duration, and that is the whole form. A program is identified by its place in the institution rather than by a name, so `program_id` is slugged from `field` (`_generate_program_id`) — a Thai field slugs to `program`, and the `-2`, `-3` collision suffix carries the distinction. Program names, goals, objectives, ISCED code, and professional council all stay on the model with empty defaults rather than being dropped: older rows keep their content, CHECO 1.5 keeps its source, and a client that supplies them is still accepted. The institution's vision/mission/philosophy/identity is recorded at stakeholder needs as evidence (`stakeholder_type=institutional_direction`), not as program fields.

## Skill

The `curriculum-design-agent` skill (`.claude/skills/curriculum-design-agent/`) is the canonical source for OBE rules, prompt templates, data schemas, and architectural decisions. **When working on PLO/OBE content, prompts, or schemas, defer to that skill.** This CLAUDE.md is the project-local operating manual — paths, commands, conventions. The skill is the domain manual.

## Stack

- **Agent:** LangGraph (state machine with `interrupt` for HITL)
- **LLM:** seven slots, each **named after the stage that calls it** and each with its own provider — **extraction**, **clustering**, **need_combination**, **need_dedup**, **plo_synthesis**, **validation**, **plo_review**, in pipeline order. A slot is declared once, in `SLOTS` (`config.py`), and its default model comes from `SlotSpec.default_models` — a model choice is an engineering decision that lives in the repo, not in `.env`; a `*_MODEL` env var still wins for a probe or an outage. `LLM_PROVIDER` is only the fallback for an unset slot. **`PIPELINE_PROVIDER` / `PIPELINE_MODEL`** put every slot on one model for a research run: per slot the order is the slot's own `*_PROVIDER`/`*_MODEL` in the environment, then `PIPELINE_*`, then the slot default, then `LLM_PROVIDER`. Provider and model resolve as a pair — `PIPELINE_MODEL` only reaches a slot whose provider came from `PIPELINE_PROVIDER`, so a model name never lands on an endpoint it was not chosen for — and `PIPELINE_MODEL` without `PIPELINE_PROVIDER` is a startup error. An **empty** `*_PROVIDER` still disables a disableable slot; `PIPELINE_PROVIDER` never re-enables it. On this branch the pair **defaults to** `openrouter` / `z-ai/glm-5.3-flash` (`_BRANCH_PIPELINE_*`), so every slot runs on GLM unless it sets its own; `PIPELINE_PROVIDER=` (empty) turns the pair off and every slot resolves as on `main`. Phase 6 adds the vote and loop knobs: `validation_runs` (5, `1` = single-run SMART), `validation_max_repairs` (3), `validation_timeout_seconds` (600, one PLO's whole loop), `plo_review_runs` (5), `plo_review_loop_mode` (`apply`), `plo_review_max_rounds` (5, `0` = phase 4) and `plo_review_loop_timeout_seconds` (5400); measured cost of the voted SMART tail is in `.scratch/reports/2026-11-05-phase6b-smart.md` (synthesis 6.9 min against 2.7 baseline and 4.3× its prompt tokens; synthesis plus review job overall 4.6× the prompt tokens and 3.7× the wall time). Old slot env names (`HEAVY_MODEL` …) are **refused, not ignored**. need_dedup, validation and plo_review are `disableable`: an **empty** `*_PROVIDER` turns them off, while unset still follows `LLM_PROVIDER`. The per-slot rationale and the measurements behind each model pin are in `.claude/rules/llm-slots.md` (loads when you touch `llm.py`/`config.py`). See `src/curriculum_agent/llm.py`
- **Structured output:** Instructor + Pydantic v2 (no hand-parsing JSON). The `openai` package is a dependency because Instructor uses OpenAI-compatible API to talk to Ollama — not for the OpenAI cloud service.
- **Clustering:** LLM-based (the `clustering` slot) — no embeddings/KeyBERT/Qdrant on this branch; see docs/superpowers/specs/2026-07-18-llm-only-pipeline-design.md
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
5. **SMART gate on every synthesized PLO, and the last word is pure code.** Hard criteria (S statement-opens-with-the-declared-verb, S one-declared-verb, M no-forbidden-word-*used*, R evidence-resolves) are the **floor**: `validate_and_build` runs `hard_failures` on the final statement whatever else happened, and that call alone sets `smart_escalated`. An unfixed PLO is marked for human repair, never silently dropped. A **validation agent** (`stages/smart_agent.py`, its own `VALIDATION_*` slot) judges through tools — the code verdict, the cited Needs, an excerpt of their evidence, the sibling outcomes, the Thai Bloom table — and **since phase 6 (designer's decision of 2026-11-04) the judgement is a vote, not one run.** `validation_runs` (5) judge runs read the *same* statement concurrently; code counts them (`stages/smart_vote.py`) and a soft criterion fails only when a majority of the runs *asked for* (3 of 5, `n // 2 + 1`; failed runs do not lower the bar) failed it. Early stop: 3 runs go first, and when they already decide every criterion the other 2 are not run — same result as always running 5, cheaper when the model is consistent; the other 2 start as soon as the first 3 provably cannot decide, without waiting for the slowest of them (`eager_waves.run_eager_waves`; cost and run set unchanged). A PLO that fails the round (a hard failure, or a repairable soft criterion by majority) gets **one** repair call to the synthesis slot — `complete_plo_synthesis` writes it, never the judges — whose instruction code builds from the hard failures, the majority-failed soft criteria and the representative run's `repair_hint_th`; the repaired statement is judged by 5 fresh runs. At most 3 repairs (`validation_max_repairs`), so a PLO is judged at most 4 times; one still failing after that ships with its comments. `A_actor` and `A_scope` are **never repaired** — who the actor is and whose profession the work belongs to are properties of the Need, so a majority failure stays a comment (with the "send back to the Need stage" diagnosis) and never enters the repair instruction. **A repair that adds a hard failure the previous statement did not have is discarded**: the previous statement stays and the attempt still uses its round. The agent **cannot declare a hard failure passed**: `Finish` carries no field that clears one, the hard check is pure code and is not voted, and the code gate runs afterwards regardless, so its influence is monotone — it can shrink the failure list, never declare it empty. Seven soft verdicts (S object quality, M assessability, A level plausibility, A actor, A scope, R answers-its-Needs, T horizon) become `soft_flags` **and** set the matching `SMARTCheck` field, so `passed` means what it says; they now *drive repair* but still never block or escalate — a soft criterion failing by majority after the last repair is stored as a comment for the checkpoint, and `smart_escalated` stays hard-only. When fewer runs succeed than the majority needs, that round's soft verdicts are not used (no flag is manufactured; only hard failures drive repair) and a PLO no round ever voted on is `code_only`. A PLO the designer edited by hand (`designer_edited_at`) is judged and its verdicts stored but never repaired. `validation_runs=1` restores the single-run behaviour (threshold 1). The two A additions fold into `achievable` rather than adding `SMARTCheck` fields, so no stored row changes shape: **actor** asks whether the doer is the graduate rather than the institution, **scope** whether the work belongs to this program's profession, judged against `scope_th` when the designer wrote one and otherwise against the intake field line — `scope_th` is empty on most programs, and a verdict that needed it would have been a no-op wherever it ran. Using another profession's tool for this profession's work (AI-assisted translation) is in scope; doing that profession's work (building the model) is not. When either fails because the *Need itself* is institutional or out of scope, the rubric forbids a repair and asks for a "send back to the Need stage" diagnosis instead: rewording cannot change what a Need asks for, and a repair spent on it is budget taken from the hard failures. Every failure is recorded as a `SmartFinding` with a Thai reason, and `smart_validated_by` says which validator produced the verdict — an outage yields `code_only` with no manufactured findings, because a validator that could not run must not escalate anything.
6. **6-10 main PLOs per program, each drafted from one active Need.** *Relaxed on branch `feat/four-agent-pipeline` by the designer's decision of 2026-10-26: this rule used to read "or from up to three same-KSEC Needs the duplicate check found to ask for one capability", and that fold happened inside `plo_synthesis`. Merging now happens at Agent 2 (`need_combination` → `stages/need_merge.py`): the duplicate check — a majority vote over `need_dedup_runs` (5) parallel calls since 2026-11-03 — groups up to 5 Needs (`MAX_GROUP_SIZE=5`), across KSEC bucket, and each group becomes one new merged Need (top skills capped at 7, `TOP_SKILL_CAP`) while the originals stay stored with `merged_into` set and can be split back (`POST /needs/{id}/split`). `plo_synthesis` does no folding and drafts one PLO per active Need. The merge floor (`MIN_CORE_AFTER_MERGE=4`) applies at the Need stage. Since phase 3 (2026-11-03) the manual `POST /plos/from-needs` merge route takes 2-5 Needs (`MAX_GROUP_SIZE`), keeps every PLO it replaces read-only in `superseded_plos` (no restore), and is also how the UI attaches an unused Need to an existing PLO; read the paragraphs below with that in mind.* Both bounds live in `stages/need_grouping.py` — one policy, in the module whose clustering has to respect it. The floor (`MIN_NEEDS`) cannot be enforced by code — too few Needs simply means too few PLOs — so a core count below 6 logs a policy warning for the designer to address at the checkpoint. The ceiling (`MAX_CORE_PLOS`) is enforced **by choosing which Needs to use, not by merging them**: `need_combination` still writes every core group as its own Need (before Agent 2's duplicate merge), and synthesis takes the 10 highest active Needs by `demand_score`. Agent 1 (`skill_grouping`) aims at the ceiling rather than overshooting it blindly: `allocate_cluster_targets` splits `MAX_CORE_PLOS` across the K/S/EC buckets in proportion to their unique skill names, and each bucket's clustering call is asked for about that many groups. It is a target, not a cap — `validate_assignments` still accepts whatever partition comes back, since a skill dropped to hit a number is worse than a Need over budget. The Needs that lose the cut stay stored and visible, still tracing to their evidence — they are unused, not deleted, and both the synthesis log and the PLO report name them. The bounds are a property of the **stored set**, not of one stage's output, and `POST /plos/from-needs` is checked against both. **A Need is behind at most one PLO**: the merge route supersedes every outcome citing a selected Need (`plos_citing`) and writes the merged one in its place, in a single transaction (`PLORepository.replace`). It used to append, which left a Need behind both its own outcome and the merged one — two PLOs claiming the same evidence read as two independent market demands in the มคอ.2 matrix when they are one. Because a merge replaces, it moves the core count in both directions: folding several outcomes into one lowers it, merging Needs nothing cites yet raises it, so the route refuses above `MAX_CORE_PLOS` and below `MIN_CORE_AFTER_MERGE` — the floor only when *this* merge causes the shortfall, so a program that started with too few Needs is not frozen. The merged outcome is numbered from the surviving ids, so it reuses the lowest slot it frees. A Need cited only by a superseded outcome returns to the pool and is logged. Optional PLOs (`is_optional=True`) are outside both bounds, in synthesis and in the merge route alike; `is_optional_group` decides which Needs those are, and the pitfall below says why it counts evidence items rather than member classifications.

   Merging — the automatic merge at the Need stage (`need_merge.enforce_merge_floor`, no longer in `plo_synthesis`) and the merge route alike — may take the core count below 6 but not below `MIN_CORE_AFTER_MERGE` (4), unless the set was already below it; the 6-10 band and its warnings are unchanged. The fold is chosen before the ceiling, like the scope filter, so a slot freed by a fold goes to the next Need below the cut.

   Which Needs are still available to merge is **derived, never stored** — `cited_need_ids` over the stored PLOs, used by both `plo_report` and the merge route. Deleting a PLO returns its Needs on its own, and no flag can outlive the outcome that set it.
7. **Human-in-the-loop at every stage boundary — except Agent 1 → Agent 2 and the PLO tail.** *Relaxed on branch `feat/four-agent-pipeline` by the designer's decision of 2026-10-26: the checkpoints are evidence, Need and PLO. The Need checkpoint has its own designer stage, `need_analysis` (after `skill_extraction`, which is a view the run passes through, not a gate), where since phase 2 (2026-11-03) the designer can also merge 2-5 Needs and exclude/restore a Need; evidence is locked at the API once skills or Needs exist, and an "evidence only" program copy is the way to change it. Agent 1 (`skill_extraction` + `skill_grouping`) and Agent 2 (`need_combination`) are two chained jobs with no checkpoint between them: `POST /needs/run` starts Agent 2 when Agent 1 succeeds, and each job stores its output and has its own time budget.* Stages never auto-chain into the next without checkpoint approval; the exceptions are Agent 1 → Agent 2 (skill_extraction/skill_grouping → need_combination), chained with no checkpoint between so the designer reviews the distilled Needs at the `need_analysis` checkpoint, and the PLO tail. *Reordered on branch `feat/four-agent-pipeline` by the designer's decision of 2026-11-04 (built as phase 6): the PLO checkpoint moved to the end, on the output.* The tail is now `plo_synthesis → plo_review → [PLO checkpoint, stage plo_review] → plo_report → END` (graph node `review_plos_node`; `DESIGNER_STAGES` ends `… plo_synthesis, plo_review, plo_report`). Synthesis and the review loop run with no checkpoint between them (`POST /plos/run` chains the review job, as `/needs/run` chains Agent 2); the designer approves the set the loop left, after every agent has run; then `plo_report` runs last, **builds from the stored PLOs, and is stored** in `plo_reports` with the fingerprint of the set it describes, so the rail can say "approved and reported". The 2026-10-12 waiver (report and review after the checkpoint, nothing to approve) is gone with the old order: the report is now the designer's approved result. *Relaxed on branch `feat/four-agent-pipeline` by the designer's decision of 2026-10-26 (built as phase 4, 2026-11-03): the tail changes PLOs on its own.* After a fresh agent review is stored, **send-back** (`stages/plo_feedback.py`, Agent 4) acts on the findings a majority of runs agreed on — a redundancy merges the PLOs, an alignment or Bloom/verb finding redrafts the PLO, a KSEC category with no PLO gets one drafted from the best unused Need, an unused Need worth considering gets a PLO — through the same `plo_redraft` path as the designer's merge, so every bound and SMART check applies, and each redraft carries the reviewer's reason, suggestion and the old statement in its note. It is safe because each action leaves a row in `plo_feedback_actions` (the trail, with its round) and the replaced outcome in `superseded_plos` (`cause=review`), so nothing is lost and the designer can see what changed and why. A PLO gets at most one alignment redraft per review loop (decision 28), so alignment cannot cycle. *Looped by the designer's decision of 2026-11-04 (phase 6):* the review and send-back repeat as `stages/plo_review_loop.py` — review, send back, review again — until a review has nothing actionable (pass), a round applied nothing (every action skipped or failed), `plo_review_max_rounds` (5) send-backs have run, or `plo_review_loop_timeout_seconds` (5400) runs out. The last step is always a review, so the set the designer approves has a current one (at most 6 reviews, 5 send-backs); what the loop could not fix reaches the designer as comments on the review page, not silence. A timeout or an error ends the loop with a stop reason on the trail, never a failed session. Guards: a PLO written by a redundancy merge in an earlier round is not merged again (merge drift), the merge floors and `MAX_GROUP_SIZE` still hold, and **a PLO the designer edited by hand (`designer_edited_at`) is never rewritten automatically** — its findings stay as comments. `plo_review_loop_mode` is `off` | `shadow` | `apply`, default **`apply`** since the designer's decision of 2026-11-11 (after the guarded apply run, `.scratch/reports/2026-11-06-phase6c-loop.md` §5: 3 rounds, about 5.8× the baseline prompt tokens); `shadow` reviews once and records every action it would take as `planned` without writing a PLO; `off`, or `plo_review_max_rounds=0`, is the phase-4 single send-back (still behind `plo_review_send_back`). The graph's `review_plo_report` node is gone; a QA failure, and a send-back or loop failure, never fails the session.
8. **Open-source LLM by default.** Paid APIs (Claude, GPT-4o) are config-switchable for synthesis stages but never hardcoded.

## Where to find things

- **OBE rules / Bloom verbs / SMART criteria (hard/soft rubric)** → skill `references/obe-principles.md`
- **The text of any prompt** → `docs/prompt-inventory.md`, generated from the builders by `scripts/dump_prompts.py` (`--check` fails when it is stale). **Why a prompt says what it says** → skill `references/prompts.md`. The reference used to carry copies of the prompts too, and all three had drifted; don't reintroduce one.
- **Data schema decisions** → skill `references/data-schemas.md`, implemented in `src/curriculum_agent/models.py`
- **SMART hard checks (pure code)** → `src/curriculum_agent/stages/smart_rules.py`; the forbidden-word scan and the finding codes → `src/curriculum_agent/smart_vocabulary.py`
- **The SMART validation agent** → `src/curriculum_agent/stages/smart_agent.py` (loop), `smart_agent_tools.py` (what it may see), `prompts/smart_agent.py`
- **Service config** → `docker-compose.yml`, `.env.example`
- **DB schema** → managed by Alembic in `migrations/`. Never edit DB by hand.

## Common pitfalls

Subsystem pitfalls live in `.claude/rules/` and load when you work on the matching files: `llm-slots.md` (slots, cache, request shape), `smart-gate.md` (SMART checks, PLO statement edits), `need-pipeline.md` (evidence → skills → Needs, demand score), `plo-review.md` (stage 06 QA agent), `api-data.md` (jobs, repositories, checkpoints, program copy). Read the relevant one before planning a change in that area, even before opening a file.

- **Don't bypass the SMART gate after synthesis.** The synthesis LLM will produce plausible-looking PLOs that fail SMART. Hard checks are pure code (`smart_rules.py`) and the validation agent is a separate slot that instructs repairs rather than writing them. Escalated PLOs must stay visible in the UI.
- **Don't pass full evidence text into synthesis prompts.** Summarize each Need in ≤200 tokens. Full evidence stays in Postgres for drill-down, not in the synthesis prompt.
- **Never cluster skills across a KSEC bucket; only Agent 2's merge produces a multi-tag Need.** *Relaxed on branch `feat/four-agent-pipeline` by the designer's decision of 2026-10-26: the old rule also forbade merging Needs across a bucket. Now clustering (Agent 1, `skill_grouping`) stays inside one bucket, so an unmerged Need still has exactly one tag, and only the duplicate merge in Agent 2 may join Needs of different tags into one merged Need carrying `Need.ksec_categories` (the sorted union). Don't add a clustering path that crosses buckets, and don't let a merge happen anywhere else.* `skill_grouping` buckets `ExtractedSkill`s by `ksec_category` before any clustering runs, and clustering stays inside one bucket. The buckets are `K`, `S`, `EC` — `E` and `C` skills deliberately share the `EC` bucket, and `resolve_need_ksec` hands back a standalone `E` or `C` for a group whose members turn out to be purely one of them. This is what makes "an unmerged Need has exactly one KSEC tag" a structural guarantee rather than a rule someone has to remember — don't add a grouping path that clusters across buckets, even to reduce the Need count.
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
