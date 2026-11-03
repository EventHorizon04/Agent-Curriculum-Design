# Four-agent pipeline, phase 5: token accounting and extraction time

Date: 2026-11-03. Branch: `feat/four-agent-pipeline`.
Status: the designer asked to carry on ("ต่อ phase ถัดไป") without a question
round. Every decision below is the builder's call, marked so it can be reversed.

## Why

Phase 1 left three things for phase 5: batching `need_dedup` / `plo_review` for
very large sets, token accounting, and (from the phase-1 timing report) the
time Agent 1 takes.

What the code and the reports say today:

- **Nothing counts tokens.** `llm._complete` calls instructor's `create` and
  returns only the parsed model; the completion's `usage` is discarded. Every
  token figure in `.scratch/reports` came from ad-hoc probes. Jobs store only
  `created_at` / `finished_at`.
- **Agent 1 is the slow stage.** Runs 4-13 on the stored corpus (14 evidence
  items, ~89 skills): Agent 1 241-280 s of a 477-620 s pipeline; cold extraction
  alone 240-430 s. Extraction calls carry no `max_tokens` and no reasoning
  bound, and grouping runs its K, S and EC (and institutional) clustering calls
  one after another.
- **`need_dedup` and `plo_review` are bounded by design today.** Dedup reads the
  in-scope Needs (about 12 on the stored corpus; Agent 1 aims at 10 core groups)
  and the review reads at most 10 core PLOs plus the optional ones. Neither has
  been seen near a context limit, and there is no measurement to size a batch on.

## Decisions (builder's calls)

1. **Measure before batching.** No batching of `need_dedup` or `plo_review` in
   this phase. The token accounting below is what will show when either needs
   it. Instead each gets a logged warning when its input passes a size worth
   noticing (`need_dedup`: more than 30 eligible Needs; `plo_review`: more than
   15 PLOs in the dossier), so a large program is visible in the log and in the
   usage numbers before it fails. *Cost if wrong:* a very large program can still
   hit a context limit; that would show as a failed call with its token count.
2. **Every provider response is recorded, retries included.** One row per
   response in a new table `llm_usage`: `id`, `program_id` (nullable), `job_id`
   (nullable), `session_id` (nullable), `slot`, `provider`, `model`,
   `prompt_tokens`, `completion_tokens`, `reasoning_tokens` (nullable — not every
   endpoint reports it), `latency_ms`, `ok` (false when the response failed
   validation and instructor retried), `created_at`. Instructor's retries are
   real spend, so a count that saw only the final response would under-report
   exactly the calls that went wrong. Cache hits make no call and record nothing.
3. **Attribution by context, not by threading arguments.** A `contextvars`
   context (`program_id`, `job_id`, `session_id`) is set where work starts — the
   job runner, the graph session runner, the synchronous designer routes that
   call a model (`from-needs`, `/needs/merge`) — and read by the recorder. Calls
   made outside any context (scripts, warm-up) are recorded with nulls. `slot` is
   known at the call site already (each slot has its own wrapper).
4. **Recording never breaks a call.** The write is best-effort: a failed insert
   is logged and the completion is returned. The DB write is one small insert
   per response.
5. **Read side:** `GET /programs/{id}/usage` returns totals per slot and per job
   (calls, failed calls, prompt/completion/reasoning tokens, summed latency),
   newest job first, plus a program total. The Pipeline page shows a small
   "การใช้โมเดล" panel from it: per job kind the latest run's calls, tokens and
   time, and the program total. No cost in money — prices differ per provider
   and change; tokens are the stable unit.
6. **Usage rows live with the program.** Deleted by the program delete cascade;
   not copied by a program copy (a copy made no calls); not cleared by re-runs
   (history of spend is the point).
7. **Extraction time — two changes, one of them measured first.**
   - **Grouping runs its bucket calls concurrently**, bounded by
     `llm_max_concurrency`, instead of one after another. The calls are
     independent (one bucket each) and already cached per bucket; results are
     assembled in the same order as today so group ids do not change.
   - **Extraction gets a configurable output bound**: `extraction_max_tokens`
     and `extraction_reasoning_max_tokens` settings, sent on every extraction
     call. On this endpoint a reasoning bound turns GLM's reasoning off
     (`.claude/rules/llm-slots.md`), which can change what is extracted, so the
     **default is decided by a measured comparison** on a copy of the stored
     corpus, cold cache, bound vs unbound: wall time, skill count, grounded
     share, and overlap of skill names. If the bounded run loses more than 10% of
     the unbounded run's skills or grounding, the default stays unbounded (the
     knob remains for a research run). The measurement is written up in
     `.scratch/reports/`.
   - Concurrency (`llm_max_concurrency=5`) and chunk size are not changed: both
     trade against provider rate limits and extraction quality that this phase
     does not measure.

## Goals

- After any run, the designer (or a researcher) can read how many calls and
  tokens each stage spent, per job, including failed attempts.
- Agent 1 is measurably faster on the stored corpus without a measured loss in
  extraction quality.
- A program large enough to stress `need_dedup` or `plo_review` says so in the
  log before it fails.

## Non-goals

- Batching `need_dedup` / `plo_review` (decision 1).
- Money cost.
- Changing concurrency, chunk size, timeouts or the job step budget.
- Per-PLO or per-Need token attribution.

## Anti-goals

- A recorder failure that fails an LLM call or a job.
- Token numbers that silently omit retries.
- A speed change that loses extraction quality without anyone having measured it.
