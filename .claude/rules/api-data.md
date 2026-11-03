---
paths:
  - "src/curriculum_agent/api/**"
  - "src/curriculum_agent/data/**"
  - "src/curriculum_agent/graph.py"
  - "frontend/src/**"
  - "migrations/**"
---

# API, jobs, persistence, and graph pitfalls

Moved out of the root CLAUDE.md so it loads only when working on the files above.
These are standing project rules, not suggestions — same weight as CLAUDE.md.

- **`PLORepository.list_by_program` orders its rows, and that is load-bearing.**
  `plo_id` carries meaning — PLO1 is the outcome drafted from the most-demanded
  Need, which is why synthesis keeps demand order through `asyncio.gather` and
  why `as_completed` is banned there. The read used to have no `ORDER BY`, so
  Postgres handed back heap order and an `UPDATE` moved that row to the end of
  it: revalidating one outcome silently reshuffled the exported มคอ.2 matrix and
  the UI list. `is_optional` first (OPT sorts above PLO lexicographically), then
  length before value (or PLO10 lands between PLO1 and PLO2).
- **A PLO's identity is (program, plo_id); `plo_id` alone is a per-program
  label.** `plo_id` (PLO1..PLOn, OPT1..OPTn) repeats across every program — it
  was only ever unique within one program's own synthesis run. `PLOTable` used
  to carry it as the sole primary key, so `PLORepository.bulk_insert` and
  `.replace` resolving an upsert with `session.get(PLOTable, plo.plo_id)`
  looked at plo_id only: a second program's PLO1 synthesis run found the
  *first* program's PLO1 row and overwrote it in place, including relabelling
  it onto the second program's `program_id`. The first program lost seven
  outcomes with no error raised anywhere. The PK is now a composite
  `(program_id, plo_id)` (migration `e4b6d19a3f72`), and every `session.get`
  on `PLOTable` passes both.
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
- **Evidence is locked once extraction has run, at the API, and the copy is the
  way out** (phase 2, designer's decision of 2026-11-03). `evidence_lock_reason`
  (`api/routes/evidence.py`) answers the busy reason while the program has a
  running job, session or writer — the first extraction stores no skill until
  it finishes, so "skills exist" alone would let an edit land mid-run — and the
  lock text once any skill or Need is stored. POST (an upsert, so an existing
  id is an edit too), PUT, DELETE and `classify-stream` all refuse with 409;
  POST/PUT/DELETE take `program_lock` around check and write so `start_job`
  cannot slip between them, and `classify-stream` holds a `sync_writer`
  registration for its whole stream. A failed first extraction writes nothing,
  so it does not lock. Seed scripts and the copy write through repositories and
  are not designer edits. `POST /programs/{id}/copy` takes `{"mode":
  "evidence_only"}` to clone metadata and evidence only — no skills, groups,
  Needs, PLOs or review — which leaves the copy unlocked; no body is `full`.
- **A program copy re-keys every evidence, skill and Need id; the validator
  switch skips only the agent.** `POST /programs/{id}/copy` (`data/program_copy.py`)
  exists so one synthesis run survives the next. `evidence_id`, `skill_id` and
  `need_id` are global single-column keys, so the copy mints fresh uuids and
  `remap_ids` rewrites every value equal to an old id — reference columns and
  JSONB alike, `Need.merged_into`/`merged_from` and the `skill_groups` rows (their
  `group_id`, `skill_ids`, `evidence_ids`) included; `plo_id` is kept, since a PLO is `(program_id, plo_id)`. Rows are
  cloned from the table's columns, so a new column is copied by default. A
  review current for the source is re-fingerprinted to stay current; a stale
  one stays stale. `copied_from` is on `ProgramMetadata`, not the create request,
  and `PUT` carries it over. `POST /plos/run` with `run_validation=false` gives
  `ValidationReason.SKIPPED` — distinct from `.env`'s `DISABLED`, which wins —
  and `hard_failures` still runs: immutable rule 5 is untouched.
- **Long stage runs are jobs, and a program takes one writer at a time.** The
  seven run routes (`/needs/run`, `/needs/skills/run`, `/needs/combine/run`,
  `/plos/run`, `/plos/report/run`, `/plos/review/run`, `/plos/{id}/revalidate`)
  check their preconditions synchronously (404/422, before any row exists, and
  409 when the program is busy),
  then `api/jobs.start_job` records a `jobs` row and runs the old body in a
  background task; they answer 202 with a `JobInfo`, and the page reads
  `GET /programs/{id}/jobs`. Holding the request open lost the running state on
  navigation, never reached a refreshed page, and was cut by the tunnel at
  ~100 s. A running job **or a running graph session** blocks another job and
  the synchronous writers (`POST /sessions/`, `/approve`, `/plos/from-needs`,
  `/needs/{id}/split`, `/copy`) with a Thai 409 — every stage deletes and rewrites what the next one
  reads. The check-then-write is serialised per program by `program_lock`
  (in-process; the deployment is one uvicorn process): `start_job` holds it
  around its busy-check and insert, `/sessions/`, `/approve` and `/copy` around
  their busy-check and short write. `/plos/from-needs` cannot hold it across its
  LLM call — that would stall every `start_job` for minutes — so it registers as
  an in-process writer instead (`/needs/{id}/split`, `/needs/{id}/exclude|restore`, `/needs/merge` and the evidence `classify-stream` register the same way; `sync_writer`: busy-check and registration under
  the lock, the lock released before the call, the registration removed in a
  `finally`); `program_busy` reports a registered writer first, so a job, a
  session, a copy or a second merge started mid-merge answers 409 rather than
  overlapping the replace. Anything left `running` by a dead process is failed at startup
  (`sweep_orphaned_jobs`: jobs, and graph sessions via
  `SessionRepository.fail_all_running`, same restart message), or the program
  would stay blocked. `result` is the body the route used to return. `JobInfo`
  timestamps carry `+00:00` only in JSON output (`field_serializer(...,
  when_used="json")`; the DB stays naive UTC, and a python-mode dump keeps the
  datetime because the ORM column rejects an ISO string) — a browser reads a
  naive ISO string as local time. The UI side is `JobsProvider` / `useJobs`
  (`hooks/useProgramJobs.tsx`; `StageLayout` mounts the provider once). It polls
  while a job runs and re-reads on every route change and whenever the tab
  becomes visible, so a job another tab or client started is not unknown until
  this page starts one of its own. A stage page reloads its data through one
  shared hook, `useReloadOnJobs` (`hooks/useReloadOnJobs.ts`), when a job it
  watched running — from its own `started(job)` or from the shared list —
  reaches **any terminal status**, `succeeded` or `failed` (`/needs/run`
  commits the new skills before need_combination can fail, so a failed run has
  still changed the page's rows), for any kind that changes that page's data,
  and never by comparing a server timestamp with the browser clock. Tests reach
  none of this for real: conftest swaps `JobRepository` for memory
  (`tests/support/jobs.py`), `spawn` for a recorder — `spawned.drain()` runs the
  bodies — and stubs the running-session check and the session sweep.
- **`/needs/run` is two chained jobs, not one long one.** It starts a
  `skill_extraction` job (Agent 1: `skill_extraction`, then `skill_grouping`, each
  under its own `asyncio.wait_for` of `need_job_step_timeout_seconds` — 900 s
  since 2026-10-28, raised from 300 s while run time is not a concern on this branch), and `api/jobs.start_job_or_409`'s
  `on_success` hook starts the `need_combination` job (Agent 2) when that
  succeeds. Each job stores its output before the next starts, both appear in
  `GET /jobs`, and a failure names the agent that failed while Agent 1's rows
  survive. The chain start is `or_409=False`: if another writer slipped in
  between, it is logged and the skill job stays succeeded. `/needs/skills/run`
  reruns Agent 1 only and does **not** chain — the designer reads re-extracted
  skills before the Needs are redrawn, which would also undo their splits, and
  the stale-Needs banner stays; `/needs/combine/run` reruns Agent 2 alone from
  the stored `skill_groups`. `skill_groups` is a table keyed to the program:
  `SkillGroupRepository` replaces a program's groups with its skills, and the
  delete cascade drops groups before skills because their ids point at skill
  rows. `useReloadOnJobs` on the skill page reloads on either job kind.
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
