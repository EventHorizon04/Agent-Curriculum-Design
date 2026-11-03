# Four-agent pipeline phase 5 (token accounting, extraction time) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every provider response's tokens and latency per program/job, show them, run grouping's bucket calls concurrently, and give extraction a measured output bound.

**Architecture:** A `contextvars` scope set where work starts; instructor hooks in `llm.py` write one `llm_usage` row per response (retries included) through a best-effort repository call. A read route aggregates per slot and per job; the Pipeline page shows it. Grouping gathers its bucket calls with the existing bounded-gather helper. Extraction gains two settings whose default the controller sets from a measurement.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, instructor, pytest; React + TS + Vite with mocks.

**Spec:** `docs/superpowers/specs/2026-11-03-four-agent-pipeline-phase5-design.md`

## Global Constraints

- Branch `feat/four-agent-pipeline`; `git branch --show-current` before every commit; explicit staging; never `git add -A`; never commit `.env`, `.env.demo`, `dist/`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never run `alembic` or connect to a database; never call a real LLM endpoint from tests; never print DSNs, keys or passwords. Tests run with every provider call mocked.
- Read `.claude/rules/llm-slots.md` before touching `llm.py`/`config.py`; keep `_complete`'s message-copy behaviour and the reasoning-field rules intact.
- `from __future__ import annotations`, type hints, `loguru`, repository pattern, English code/comments/logs, Thai UI strings.
- DB timestamps naive UTC (`datetime.now(UTC).replace(tzinfo=None)`); JSON output with `+00:00`.
- Frontend: index.css component classes and inks only; no Tailwind palette colours.
- Verify: `uv run pytest -q -W error::RuntimeWarning`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src`, `uv run python scripts/dump_prompts.py --check`; frontend `npm run build`, `npm run lint` (0 errors; 1 known warning).

## Review Focus

- An instructor retry (first response fails validation, second passes) yields two rows, the first `ok=False`, both with tokens.
- The usage insert raising (DB down) leaves the LLM call's result and the job unaffected; one warning logged.
- Concurrent calls from two programs in one process attribute to their own program (contextvars, not a module global).
- A provider response without `usage`, or without `completion_tokens_details.reasoning_tokens`, records nulls/zeros rather than raising.
- Grouping with buckets run concurrently produces exactly the groups (ids and order) the sequential version produced for the same cached inputs.

---

### Task 1: storage — `llm_usage`

**Files:** `src/curriculum_agent/models.py` (`LLMUsage`, `UsageSummary`), `src/curriculum_agent/data/orm.py`, migration `migrations/versions/e5a9c2f7b318_llm_usage.py` (down `d7b3e5c1a420`), `src/curriculum_agent/data/repositories.py` (`LLMUsageRepository.add(row) -> None`, `.summary(program_id) -> UsageSummary`; `ProgramRepository.delete_cascade` deletes the program's rows), tests `tests/unit/test_llm_usage_repository.py`, adjust the cascade-statement test.

`UsageSummary`: `total: UsageTotals`, `by_slot: list[SlotUsage]`, `by_job: list[JobUsage]` (newest job first; each with `job_id`, `kind` (from `jobs`), `started` (`created_at` of its first row), per-slot totals). `UsageTotals`: `calls`, `failed_calls`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `latency_ms`. Aggregation in SQL (`GROUP BY`), not in Python over every row. Not copied by program copy.

- [ ] Steps: failing tests (add/summary shape, grouping per slot and job, nulls summed as 0, cascade) → implement → verify → commit `feat(data): llm_usage table and summary`.

### Task 2: recorder and attribution

**Files:** new `src/curriculum_agent/llm_context.py` (`llm_scope(*, program_id: str | None = None, job_id: str | None = None, session_id: str | None = None)` context manager over a `ContextVar`; `current_scope()`), `src/curriculum_agent/llm.py`, `src/curriculum_agent/api/jobs.py` (job body runs inside `llm_scope(program_id=..., job_id=...)`), the graph session runner (`_run_graph`, `session_id`), `api/routes/plos.py` `from-needs` and `api/routes/needs.py` `/needs/merge` (`program_id`); tests `tests/unit/test_llm_usage_recording.py`.

- `_complete` gains a keyword `slot: str` passed by every `complete_*` wrapper. Recording uses instructor's hooks (`completion:kwargs` → start time, `completion:response` → one row with usage and latency, `parse:error` → mark that attempt `ok=False`), with the per-attempt state in a `ContextVar` so concurrent calls do not share it. If the hook API cannot express this cleanly, use `create_with_completion` plus the retry information instructor exposes, and say in the report why — the Review Focus retry case must hold either way.
- Any other direct provider call in `src/` (grep `_get_raw_client`) records through the same function.
- `reasoning_tokens` from `usage.completion_tokens_details.reasoning_tokens` when present.
- The insert is awaited but wrapped: any exception → `logger.warning` once per failure, call result returned.

- [ ] Steps: failing tests for every Review Focus line 1-4 (HTTP transport or instructor client mocked below `_complete`, as `tests/unit/test_llm_request_shape.py` does) and for scope set by a job body → implement → verify → commit `feat(llm): record every provider response's usage, attributed by scope`.

### Task 3: read route, Pipeline panel, mocks

**Files:** `src/curriculum_agent/api/routes/programs.py` (or the router that owns program-level reads) `GET /programs/{id}/usage` → `UsageSummary` (404 unknown program); `frontend/src/types/` (`UsageSummary`), new `frontend/src/pages/components/UsagePanel.tsx`, `frontend/src/pages/Pipeline.tsx`, `frontend/src/mock/handlers.ts` (a believable summary for the seeded programs, 404 unknown); tests in `tests/unit/` for the route.

Panel "การใช้โมเดล": program total line (เรียก n ครั้ง · ไม่ผ่าน n · token เข้า/ออก/คิด · เวลา), then per job (newest first, at most 5 shown, rest collapsed) its kind label (reuse the job kind labels the page already has), and per slot inside it. Hidden when there are no rows. Reloads when a job finishes (`useReloadOnJobs`).

- [ ] Steps: route test → implement route → UI + mock → `npm run build`/`lint` → commit `feat(ui): model usage panel on the pipeline page`.

### Task 4: grouping concurrency, extraction bound knobs, size warnings

**Files:** `src/curriculum_agent/stages/skill_grouping.py`, `src/curriculum_agent/config.py` (`extraction_max_tokens: int | None = None`, `extraction_reasoning_max_tokens: int | None = None`), `src/curriculum_agent/stages/skill_extraction.py` (send them when set; extraction cache key unchanged unless the bound is part of what decides the payload — if it is, include it and say so), `src/curriculum_agent/stages/need_dedup.py` (warn above 30 eligible Needs), `src/curriculum_agent/stages/plo_review.py` or `plo_review_facts.py` (warn above 15 dossier PLOs); tests.

- Grouping: the per-bucket `cluster_skill_names` calls run through the existing bounded gather (`concurrency.py`), results assembled in today's bucket order; a test feeds cached/mocked answers and asserts groups identical to the sequential order and that calls overlapped (e.g. both started before either finished).
- [ ] Steps: failing tests → implement → verify → commit `perf(agent1): concurrent bucket clustering; extraction bound knobs; size warnings`.

### Task 5 (controller): measurement

Controller only, on the copy DB through the API: a full-copy program of the stored corpus, extraction cache rows for it cleared on the copy DB, `POST /needs/skills/run` unbounded then bounded (`EXTRACTION_REASONING_MAX_TOKENS=1024`, `EXTRACTION_MAX_TOKENS=4096` via env on the backend), comparing wall time, skill count, grounded share, name overlap, and the new usage numbers. Write `.scratch/reports/2026-11-03-phase5-extraction.md`. Set the defaults per spec decision 7 in a commit `perf(extraction): default output bound from the 2026-11-03 measurement` (or leave `None` and record why).

### Task 6: docs

**Files:** `.claude/rules/llm-slots.md` (recording through hooks, `slot` on `_complete`, extraction bound and its measurement), `.claude/rules/api-data.md` (llm_usage life, scope set by jobs/sessions/sync routes, usage route), `.claude/skills/curriculum-design-agent/references/data-schemas.md` (`LLMUsage`, `UsageSummary`), `.claude/rules/need-pipeline.md` (grouping concurrency).

- [ ] Steps: edit → `dump_prompts.py --check` → commit `docs: phase 5 — usage accounting, grouping concurrency, extraction bound`.
