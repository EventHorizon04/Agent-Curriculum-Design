# Background jobs: long runs survive navigation, refresh and the tunnel

Date: 2026-10-08. Status: design approved in chat (approach C), spec under review.

## Why

Every long stage run is one HTTP request that waits for the result
(`POST /plos/run` takes minutes). The "running" state lives in the page that
sent it, so:

- leaving the page and coming back shows the old data as if nothing was
  pressed — the backend is still working, the page no longer knows; only a
  manual refresh after it finishes shows the result;
- a refresh or a second tab never knows a run is in flight;
- through the Cloudflare tunnel a request waiting more than ~100 s is cut with
  a 524 (from Cloudflare's documented proxy timeout; not yet reproduced here),
  so a designer on the tunnel sees a failure for a run that actually succeeds.

The Pipeline page does not have this problem: the graph runs in a background
task, its state lives in the `sessions` row, and the page polls every 2 s.
This spec gives the per-stage runs the same shape.

**Success:** start any long run, navigate anywhere, refresh, or open another
tab — every page shows the run as running while it runs, shows its result (or
its Thai error) when it ends, without a manual refresh; no long request is held
open, so the tunnel cannot time it out.

## Scope

Long-running routes that become jobs (7):

| Route | `kind` | Page |
|---|---|---|
| `POST /programs/{id}/needs/run` | `needs_pipeline` | (skills + needs in one) |
| `POST /programs/{id}/needs/skills/run` | `skill_extraction` | SkillExtraction |
| `POST /programs/{id}/needs/combine/run` | `need_combination` | SkillExtraction |
| `POST /programs/{id}/plos/run` | `plo_synthesis` | PloSynthesis |
| `POST /programs/{id}/plos/review/run` | `plo_review` | PloReport |
| `POST /programs/{id}/plos/report/run` | `plo_report` | PloReport |
| `POST /programs/{id}/plos/{plo_id}/revalidate` | `plo_revalidate` | PloSynthesis |

Unchanged: every GET, `PUT`, `DELETE`, `POST /plos/from-needs` (one draft, but
see "Out of scope"), `POST /programs/` and `/copy`, the evidence SSE stream,
and the graph path (`/sessions`, already backgrounded).

## 1. Data — `jobs` table (new migration)

| Column | Type | Notes |
|---|---|---|
| `job_id` | String PK | uuid4 |
| `program_id` | String, FK `programs.program_id` | |
| `kind` | String(32) | one of the seven above; a String, not a PG enum (project convention) |
| `status` | String(16) | `running` / `succeeded` / `failed` |
| `params` | JSONB | the request body that matters: `note_th`, `run_validation`, `plo_id` |
| `result` | JSONB, nullable | exactly the JSON body the route used to return (`model_dump(mode="json")` of its old response model) |
| `error_th` | Text, nullable | what the designer reads when it failed |
| `created_at` | DateTime | |
| `finished_at` | DateTime, nullable | |

Pydantic `JobInfo` mirrors it (`result: Any | None`). `JobRepository`
(repository pattern): `insert`, `get`, `list_by_program(active_only)`,
`finish(job_id, status, result=None, error_th=None)`,
`fail_all_running(message) -> int`, `delete_by_program`.

- `ProgramRepository.delete_cascade` deletes the program's jobs.
- The program copy does **not** copy jobs (history of the source, not of the copy).

## 2. Runner — `src/curriculum_agent/api/jobs.py`

`async def start_job(program_id, kind, params, work: Callable[[], Awaitable[BaseModel]]) -> JobInfo`

1. **One active job per program.** If `JobRepository` has a `running` job for
   the program, raise `JobConflict(running_job)`; routes answer **409** with a
   Thai detail naming the running kind ("หลักสูตรนี้มีงาน <kind label> กำลังทำอยู่
   — รอให้เสร็จก่อน") and the running `JobInfo` in the body. Reason: every stage
   deletes then rewrites tables the next stage reads, so any two runs on one
   program can interleave. The check-then-insert race is closed in process by
   an `asyncio.Lock` per program around check+insert (single uvicorn process is
   the deployment); the existing `_SYNTHESIS_IN_FLIGHT` / `_REVIEW_IN_FLIGHT`
   guards stay as a second layer.
2. Insert the row as `running`, then `asyncio.create_task(_run(...))`, keeping
   a strong reference in a module-level set until the task ends (a bare
   `create_task` can be garbage-collected mid-run).
3. `_run` awaits `work()`. Success → `finish(succeeded, result=<model_dump json>)`.
   Exception → `finish(failed, error_th=...)` and `logger.error`. The error text:
   an `HTTPException` raised inside `work` uses its `detail`; `asyncio.TimeoutError`
   becomes "หมดเวลา (เกิน N วินาที)"; anything else `str(exc)` (the same choice
   `_run_graph` makes — stage refusals are already Thai). `finish` itself is
   wrapped so a DB error while recording the outcome is logged, never raised
   into the void.
4. **Restart sweep.** On API startup (lifespan, before `yield`),
   `fail_all_running("backend ถูกปิดระหว่างทำงาน — กดรันใหม่")`; a job left
   `running` by a dead process would otherwise block its program forever under
   rule 1. Logged with the count.

Existing timeouts (`asyncio.wait_for(..., 300)` in the needs routes, the
review's 180 s) move inside `work` unchanged.

`POST /programs/{id}/copy` replaces its `is_synthesis_running` check with "the
program has a running job" (409 with the same detail), which also closes the
copy-during-need_combination gap the run-comparison spec documented.
`is_synthesis_running` stays (used by nothing else → delete it if unused).

## 3. API

- Each of the seven routes keeps its path, body and **synchronous
  preconditions** (404 program/PLO not found, 422 no evidence/skills/Needs,
  422 unwritten Need, etc. — everything checked before the work today), then
  calls `start_job` and returns **202** with `JobInfo`. The work closure is the
  route's old body after its precondition checks.
- `plo_report`'s re-read of PLOs after the review (the lost-update fix) stays
  inside the work.
- New `GET /programs/{id}/jobs?active=true|false` → `list[JobInfo]`, newest
  first; `active=true` returns only `running`. Default `false`, capped at the
  latest 20.
- New `GET /programs/{id}/jobs/{job_id}` → `JobInfo`; 404 if the job is not
  that program's.
- `PLOReportResponse`, `NeedRunResult`, etc. remain the documented shape of
  `result` for their kind.
- API-key dependencies stay where they are today (`revalidate` keeps
  `require_api_key`).

This is a breaking change for any client of the seven routes; the only client
is `frontend/` (and its mock layer), changed in the same plan.

## 4. Frontend

Implemented in this plan by subagents (the frontend session is closed).

- `api/jobs.ts`: `JobInfo` type, `startJob(path, body)` (POST, expects 202),
  `getJob`, `listActiveJobs`.
- `hooks/useProgramJobs.ts`: fetch `GET /jobs?active=true` on mount and on
  `programId` change; while any job is running, poll every 2 s; when a job it
  saw running is no longer active, fetch it once by id and expose its final
  state (`succeeded` + `result`, or `failed` + `error_th`). Stops polling when
  nothing runs; resumes when a page starts a job. One instance per program,
  shared through a context provider mounted in `StageLayout`, so every stage
  page and the layout read the same state.
- Each stage page (SkillExtraction, PloSynthesis, PloReport):
  - start = `startJob(...)` then tell the hook; no awaiting the result;
  - "running" = the hook says a job of this page's kind is active (not a local
    flag), so it survives navigation and refresh; `RunProgress` renders from it;
  - on that job's `succeeded`: refetch the page data (or use `result`); on
    `failed`: show `error_th` in the page's existing error slot;
  - a 409 shows its Thai detail; start buttons are disabled while any job of
    the program runs.
- `StageLayout`: one line visible on every stage page while a job runs —
  "กำลังทำงาน: <Thai kind label> · เริ่ม <time>" with a link to the page that
  owns it.
- Mock layer (`frontend/src/mock/handlers.ts`, `db.ts`): the seven POSTs answer
  202 + a job that completes after a short delay; `GET /jobs` routes answer
  from the mock db. Mock mode must keep working.
- `npm run lint` and `npm run build` must pass. There is no frontend test
  runner; verification is lint, build, and a browser check by the controller.

## 5. Tests

Backend (pytest, mocked sessions — no real-DB fixture exists):
- runner: success records `succeeded` + `result`; an exception records
  `failed` + Thai `error_th` (HTTPException detail, timeout text, plain
  message); a running job makes a second `start_job` raise `JobConflict`; the
  task reference is released when it ends; restart sweep calls
  `fail_all_running`.
- routes: each of the seven returns 202 + `JobInfo`, still returns its old
  404/422 synchronously without creating a job, and 409 when a job runs;
  `GET /jobs` and `/jobs/{id}` (404 on another program's job); copy answers 409
  while a job runs.
- `delete_cascade` deletes jobs.

Live (controller): migrate, start the backend, run `POST /plos/report/run` on
`program-2-run-1`, poll `GET /jobs/{id}` to `succeeded`; navigate away and back
in the browser during a run and see the running state and the result.

## Docs

`CLAUDE.md`: one pitfall paragraph — long runs are jobs (202 + poll), one
active job per program and why, the restart sweep, where `result` comes from.
Skill `references/data-schemas.md`: `JobInfo` / `jobs`.

## Out of scope

- Cancelling a running job.
- Multiple API worker processes (the per-program lock is in-process).
- `POST /plos/from-needs` as a job (one draft + one validation loop; can exceed
  100 s on the tunnel — a follow-up if it does).
- Pruning old job rows (bounded by use; `delete_cascade` removes them with the
  program).
