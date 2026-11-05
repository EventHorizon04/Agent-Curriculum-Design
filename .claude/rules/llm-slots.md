---
paths:
  - "src/curriculum_agent/llm.py"
  - "src/curriculum_agent/config.py"
  - ".env.example"
  - "src/curriculum_agent/data/prune_cache.py"
  - "src/curriculum_agent/stages/skill_extraction.py"
  - "src/curriculum_agent/stages/llm_clustering.py"
  - "src/curriculum_agent/stages/smart_agent.py"
  - "src/curriculum_agent/stages/plo_review_agent.py"
  - "tests/unit/test_llm_*.py"
---

# LLM slots, caching, and request shape

Moved out of the root CLAUDE.md so it loads only when working on the files above.
These are standing project rules, not suggestions — same weight as CLAUDE.md.

- **LLM:** seven slots, each **named after the stage that calls it** and each with its own provider — **extraction**, **clustering**, **need_combination**, **need_dedup**, **plo_synthesis**, **validation**, **plo_review**, in pipeline order. A slot is declared once, in `SLOTS` (`config.py`), and the defaults, the resolved provider, the startup line and the warm-up list are all derived from that one entry — **including which model it runs on**, via `SlotSpec.default_models`, keyed by provider because a model name only means something at one endpoint. That is where a model choice belongs: it is an engineering decision about the stage (extraction is chosen on how faithfully a model quotes, since `is_grounded` drops an invented span), so it lives in the repository under review rather than in one machine's `.env`. A `*_MODEL` env var still wins, which is what a probe or an outage needs; it is not where a lasting choice goes. `.env` holds secrets and what differs between machines, and `APP_ENV=production` refuses the development credentials `config.py` ships (`_refuse_development_credentials_in_production`) rather than letting a deployment that forgot one start anyway and look healthy; `tests/unit/test_llm_slots.py` walks the list against `Settings.model_fields`, because a field named as a string is what mypy cannot check. The names used to be sizes — `light`, `heavy`, `synthesis` — and both had drifted from what they do: `heavy` was only ever clustering, and `light` had one caller left. Old env names are **refused, not ignored** (`_reject_renamed_slot_settings`): `extra="ignore"` would otherwise make a `.env` still carrying `HEAVY_MODEL` a line nobody reads, and the run would start on a provider default while the operator believed they had selected a model. **`PIPELINE_PROVIDER` / `PIPELINE_MODEL` (branch `feat/four-agent-pipeline`)** exist so a research run can put every slot on one model and be compared with another run. Per slot, highest first: the slot's own `*_PROVIDER`/`*_MODEL` **set in the environment**, then `PIPELINE_PROVIDER`/`PIPELINE_MODEL`, then the slot's current default (class default, then `default_models`, then the provider default), then `LLM_PROVIDER`. Provider and model resolve **as a pair** (`_apply_provider_model_defaults`): `PIPELINE_MODEL` applies only to a slot whose provider came from `PIPELINE_PROVIDER` and that named no model of its own; a slot that sets its own provider gets its own model or that provider's default, never `PIPELINE_MODEL`; a slot that sets only `*_MODEL` runs it on whatever provider it resolves to. So a model name never reaches an endpoint it was not chosen for, and `PIPELINE_MODEL` without `PIPELINE_PROVIDER` is a startup error. Explicit environment is told from a class default with `model_fields_set`, so extraction's declared `"openrouter"` does not count as set. An explicit empty `*_PROVIDER` still disables `need_dedup`/`validation`/`plo_review` and `PIPELINE_PROVIDER` never re-enables them. The pair **defaults to** `openrouter` / `z-ai/glm-5.3-flash` on this branch (`_BRANCH_PIPELINE_PROVIDER`/`_BRANCH_PIPELINE_MODEL`, the designer's single-model decision of 2026-10-28), so the per-slot pins below apply only with `PIPELINE_PROVIDER=` (empty), which turns the pair off and resolves every slot as on `main` (pinned per slot in the tests); `PIPELINE_PROVIDER` set alone drops the default model, so GLM's name never reaches another endpoint; per-call-site reasoning bounds, such as `plo_review`'s, stay where they are. `LLM_PROVIDER` is the fallback for any slot left unset and nothing else: `opentyphoon` (the default: Thai-first models, because every prompt and every stored statement here is Thai), `openrouter`, or `ollama` (running **natively on the host**, no container). Each hosted provider reads its own key (`OPENROUTER_API_KEY` / `OPENTYPHOON_API_KEY`); ollama needs none. **`EXTRACTION_PROVIDER`/`EXTRACTION_MODEL`** (default OpenRouter, `complete_extraction`) is the fan-out stage: one call per *window* of every evidence item, so it exhausts a token quota before any other stage has run — and it ran the Thai endpoint's out. It gives up little by moving, since extraction names skills rather than writing prose anyone reads. **`CLUSTERING_PROVIDER`/`CLUSTERING_MODEL`** (default OpenRouter, `complete_clustering`) is `llm_clustering` and nothing else — it holds a whole KSEC bucket in one context and returns a grouping rather than prose, so there is nothing Thai to lose by moving it off the 30B model. It is the one OpenRouter slot that pins `meta-llama/llama-3.3-70b-instruct` instead of the provider-wide default (`z-ai/glm-5.3-flash` since 2026-10-01): glm was tried here and its hidden reasoning took 473s for the clustering calls on the stored corpus — 375s on the 53-name S bucket alone — past the 300s timeout the `need_combination` run route puts on its job, and bounding the reasoning turns it off on this endpoint, leaving a grouping nobody has measured. llama is also what ticket 16 measured this slot on. **`NEED_COMBINATION_PROVIDER`/`NEED_COMBINATION_MODEL`** (`complete_need_combination`) writes the Thai sentence for each Need, the one sentence `plo_synthesis` is later handed. Its provider ships **unset**, so it follows `LLM_PROVIDER` — it is the slot that had no provider field at all until the rename, which left `LLM_PROVIDER` doing two jobs (the fallback for every unset slot, and this slot's actual endpoint) and meant it could not be moved without moving all of them. Pinning it to `opentyphoon` now would look like the same thing and quietly stop being it the moment `LLM_PROVIDER` moved. **`NEED_DEDUP_PROVIDER`/`NEED_DEDUP_MODEL`** (default OpenRouter `z-ai/glm-5.3-flash`, `complete_need_dedup`) is the duplicate check at Agent 2 (`need_combination` → `need_merge` → `need_dedup`), no longer in `plo_synthesis`: one call per run that reads every in-scope Need and groups the ones asking for one capability. The model is pinned there on the probe against the stored Needs: llama-3.3-70b (the clustering model) folded all nine in-scope Needs into four units every run — a trio joining the top-demand digital-marketing Need with two translation-tool Needs, and a pair joining a consumer-culture Need with an academic-translation Need, neither sharing a main task and object — while glm-5.3-flash folded only the two genuine pairs, stably over three runs. It returns labels, not Thai prose, and `accept_groups` judges the answer in code. Like validation it is `disableable` — `NEED_DEDUP_PROVIDER=` (empty) skips it and every Need gets its own slot. **`PLO_SYNTHESIS_PROVIDER`/`PLO_SYNTHESIS_MODEL`** (default OpenTyphoon, `complete_plo_synthesis`) is `plo_synthesis` — both the draft call and the SMART repair call, so a repair is never answered by a different model than wrote the draft. **It and clustering are separate knobs on purpose:** they were one `heavy` slot until they had to go different ways — clustering wants the larger model, while a PLO statement is Thai a designer submits to MHESI under their own name — and sharing one knob meant neither could move without the other. **`VALIDATION_PROVIDER`/`VALIDATION_MODEL`** (default OpenRouter, `complete_validation`) is the SMART validation agent — the only slot that runs a tool-using multi-turn loop, and deliberately not clustering's: a slot sharing that knob could not be moved without moving clustering. It reasons over a Thai sentence plus a set of tool results rather than writing Thai, and it no longer decides a repair itself: since phase 6 it runs `validation_runs` (5) judge runs per round, code votes on them (`stages/smart_vote.py`) and checks the hard criteria, and code builds the repair *instruction* from the hard failures, the soft criteria that failed by majority and the representative run's `repair_hint_th`, which `complete_plo_synthesis` executes — so a repair is still never answered by a different model than wrote the draft. The five judge runs of a PLO share `llm_max_concurrency` with every other PLO's runs (`validation_max_concurrent_plos` still bounds PLOs) and `validation_timeout_seconds` (600) covers a PLO's whole loop, every round and repair. Setting `VALIDATION_PROVIDER` to the **empty string** skips the agent and keeps the pure-code verdict; that is the kill switch, and it reuses the fallback an endpoint outage needs anyway rather than a feature flag. This, need_dedup, and plo_review are the three slots where empty and unset differ, and the distinction is load-bearing: every other provider field only picks an endpoint, so `None` (unset) means "follow `LLM_PROVIDER`" for all seven — but these three also answer *whether to run*, so `""` is off and `None` still follows. `""` is a member of their `Literal` for exactly that reason, need_dedup, validation, and plo_review are the only slots with `disableable=True`, `_apply_provider_model_defaults` and `_slot_provider` both leave them alone, and `describe_target()` prints `validation: disabled` (or `need_dedup: disabled`, or `plo_review: disabled`). Say "empty" and mean the empty string: the version that only documented it resolved `"" or llm_provider` back to a live provider, so the switch could not be thrown at all. **`PLO_REVIEW_PROVIDER`/`PLO_REVIEW_MODEL`** (default OpenRouter `z-ai/glm-5.3-flash`, `complete_plo_review`) is stage 06, the QA agent: it runs before the PLO checkpoint and the report (the report is built last, from the set the designer approved), reads the finished PLO set as a whole, and stores advice per program; it writes nothing a designer submits. It is a tool-using agent (`stages/plo_review_agent.py`, the structured action loop `smart_agent` uses) given a code-built dossier and a small budget: tools `bloom_lookup`, `check_verbs` and `need_detail`, at most 4 tool calls (a refused call still counts) and 6 steps, the whole run bounded by `plo_review_timeout_seconds` (300). It runs **`plo_review_runs` times (default 5) in parallel on the same dossier** and stores what a majority agrees on (`stages/plo_review_consensus.py`, pure code): the model answers differently from run to run even at temperature 0 — two runs on one program grouped the same PLOs into different redundancy findings — so a finding one run produced alone is kept with its `agreed_runs` but shown apart. One usable run is stored as-is and labelled unconfirmed; `plo_review_runs=1` is the single-run review. Three runs left findings the model gives about half the time flipping across the 2-of-3 line press to press; five (threshold 3) gave the same main findings on three presses (spec "Measured"). Disableable like need_dedup and validation (`PLO_REVIEW_PROVIDER=` off) — but off no longer means no review: the job still runs and stores the code-computed facts as a `code_only` review, and `POST /plos/review/run` no longer answers 503. Its hidden reasoning is bounded at 1024 tokens on every step (`stages/plo_review_agent._MAX_REASONING_TOKENS`). The case for the bound was measured on the agent's single-call predecessor: unbounded on the tourism program that slot produced nothing in 3/3 runs (one truncation at 8192 tokens after 175s, two 180s timeouts), while bounded it answered 3/3 in 45-57s. The agent itself was measured on 2026-10-13 (spec's "Measured" section): both stored programs finished on step 1 with no tool call in about 20s, `reviewed_by="agent"`, nothing dropped — so a run sits far inside the 300s budget, and the tools have unit tests but no live exercise yet. Each model defaults from *its own* slot's provider (`_PROVIDER_DEFAULT_MODEL` in `config.py`), never from `LLM_PROVIDER`'s. `llm.describe_target()` prints all seven endpoints a process resolved to (from `llm._slots()`, the one list `warmup_models` reads too) — never the keys — and the API logs it once at startup. See `src/curriculum_agent/llm.py`

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
- **The extraction cache is keyed on `settings.extraction_model`, and so is what
  it stores.** One name in three places — the key, the hit comparison, and the
  `set` call. It was keyed on what is now `need_combination_model` and stored as
  what is now `clustering_model` (`light_model` and `heavy_model` at the time)
  for as long as those resolved to the same string; the moment extraction moved
  to its own provider, every write became a permanent miss and the corpus was
  re-extracted at full cost on every run. `test_skill_extraction_cache.py`
  replays a stored entry rather than asserting each call site, because asserting
  them separately is exactly what let the mismatch through.
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
- **Every provider response is recorded, through instructor's hooks, and the recorder
  never fails a call** (phase 5). `_ensure_usage_hooks` registers `completion:kwargs`,
  `completion:response`, `completion:error` and `parse:error` once per cached client;
  they append each attempt (tokens, latency, `ok`) to a list held in a `ContextVar`,
  and `_complete` writes the list in its `finally` through `_record_usage` — so a
  retried call, a truncation and a call that finally raised all leave rows. A
  `completion:error` or `parse:error` marks the attempt failed (`ok=False`); a
  truncated response takes the first path, not the second, and instructor retries it.
  `_record_usage` catches everything and logs a warning: accounting must never change
  what `_complete` returns or raises. The **warm-up keep-alive is not recorded** — it
  is a one-token ping to pin an Ollama model, not work done for a program. `_complete`
  takes a `slot` keyword, passed by every `complete_*` wrapper (`validation` included),
  so a row says which stage's slot made the call whatever model it resolved to. The
  scope (program, job, session) comes from `llm_context.llm_scope`; see `api-data.md`
  for who sets it.
- **The extraction output bound is on by default, measured, and part of the cache
  key.** `EXTRACTION_REASONING_MAX_TOKENS=1024` and `EXTRACTION_MAX_TOKENS=4096`.
  Measured 2026-11-03 on GLM (`.scratch/reports/2026-11-03-phase5-extraction.md`):
  about 89% of unbounded extraction output was hidden reasoning, and bounding it took
  Agent 1 from ~255 s to ~47 s for -9.1% skills (82 vs 90, the loss in the long tail
  of S) and -1.6% grounding (invented spans, which `is_grounded` drops before they
  reach a Need). `0` means "no bound": the field is not sent and not added to the key,
  so the key is byte-for-byte the pre-bound one — that is the research setting.
  A positive bound is appended to the key (`max_tokens=`, `reasoning_max_tokens=`) because
  it can change the answer: a cached unbounded extraction must not be replayed for a
  bounded run. **The default changing therefore re-extracts each program once**; the
  old rows become unreachable, and `prune_cache --older-than DAYS` is the sweep for
  them (no column marks them stale). Not measured: whether the ~8 fewer S skills
  change the Needs and PLOs downstream. The defaults were measured on GLM via
  OpenRouter only: `reasoning_max_tokens` is sent only to OpenRouter (the `llm.py`
  rule) while `max_tokens` is sent to any provider, so re-measure before moving
  extraction to another provider (elsewhere the reasoning bound is a no-op that
  still enters the cache key, and 4096 is unmeasured).
