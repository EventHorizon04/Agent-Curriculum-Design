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
| `POST /programs/{id}/plos/review/run` | `plo_review` | none today (no page calls it yet) |
| `POST /programs/{id}/plos/report/run` | `plo_report` | PloReport |
| `POST /programs/{id}/plos/{plo_id}/revalidate` | `plo_revalidate` | PloSynthesis |

Still synchronous: every GET, `PUT`, `DELETE`, `POST /plos/from-needs` (one
draft, but see "Out of scope"), `POST /programs/` and `/copy`, the evidence SSE
stream, and the graph path (`/sessions`, already backgrounded). Four of these
gain a 409 while the program is busy (section 2).

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

Pydantic `JobInfo` mirrors it (`result: Any | None`) and adds `label_th`
(the Thai name of the kind, from one backend table `JOB_KIND_LABEL_TH`, so the
409 text and every page say the same thing). **Timestamps go out as UTC with
an explicit offset** (`+00:00`): the columns stay naive UTC like every other
table here, but a naive ISO string is read by the browser as *local* time —
the Pipeline page already shows session times 7 hours off this way — and
`RunProgress` will compute elapsed time from `created_at`. `JobRepository`
(repository pattern): `insert`, `get`, `list_by_program(active_only)`,
`finish(job_id, status, result=None, error_th=None)`,
`fail_all_running(message) -> int`, `delete_by_program`.

- `ProgramRepository.delete_cascade` deletes the program's jobs.
- The program copy does **not** copy jobs (history of the source, not of the copy).

## 2. Runner — `src/curriculum_agent/api/jobs.py`

`async def start_job(program_id, kind, params, work: Callable[[], Awaitable[BaseModel]]) -> JobInfo`

1. **One active writer per program.** `start_job` refuses with
   `JobConflict` when the program has a `running` job **or a `running` graph
   session** (`sessions.status == "running"`): the graph runs the same stages
   and writes the same tables, so a session and a job on one program interleave
   exactly like two jobs. Routes answer **409** with `detail` a plain Thai
   string ("หลักสูตรนี้มีงาน <label_th> กำลังทำอยู่ — รอให้เสร็จก่อน", or
   "…กำลังรัน pipeline อยู่…" for a session) — a string, because every page reads
   `response.data.detail` as text; the running job itself is found through
   `GET /jobs?active=true`. Reason for the rule: every stage deletes then
   rewrites tables the next stage reads. The check-then-insert race is closed
   in process by an `asyncio.Lock` per program around check+insert (single
   uvicorn process is the deployment); the existing `_SYNTHESIS_IN_FLIGHT` /
   `_REVIEW_IN_FLIGHT` guards stay as a second layer. One consequence,
   accepted: two `revalidate` jobs on one program run one after the other,
   not together.
   The same check (one helper, `program_busy(program_id) -> str | None`
   returning the Thai reason) guards the synchronous writers that would
   interleave with a job: `POST /sessions/` and `POST /sessions/{id}/approve`
   (they start or resume the graph), `POST /plos/from-needs` (writes PLOs),
   and `POST /programs/{id}/copy` (reads a half-written set) — each answers 409.
2. Insert the row as `running`, then hand `_run(...)` to `spawn(coro)`, a
   one-line module function that calls `asyncio.create_task` and keeps a strong
   reference in a module-level set until the task ends (a bare `create_task`
   can be garbage-collected mid-run). `spawn` is the seam tests patch: under
   `TestClient` each request runs on a short-lived portal loop, so a real task
   would be abandoned when the request returns — route tests replace `spawn`
   with a recorder, and runner tests (pytest-asyncio) await `_run` directly.
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

`POST /programs/{id}/copy` replaces its `is_synthesis_running` check with
`program_busy`, which also closes the copy-during-need_combination gap the
run-comparison spec documented. `is_synthesis_running` then has no caller and
is deleted with its test.

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
- `hooks/useProgramJobs.ts`: reads `GET /jobs` (latest 20) on mount and on
  `programId` change; while any job is running, polls every 2 s; stops when
  nothing runs; resumes when a page starts a job. It exposes the running job
  (if any) and **the latest job of each kind** — state derived from the
  server's list, never from transitions the page happened to witness, so a
  run that finished while the browser was closed or on another tab is
  reported the same as one watched to the end. One instance per program,
  shared through a context provider mounted in `StageLayout` (the layout route
  wraps every page, `Programs` and `Pipeline` included, and stays mounted
  across navigation; it already knows `programId` from `useProgram`).
- Each stage page (SkillExtraction, PloSynthesis):
  - start = `startJob(...)` then tell the hook; no awaiting the result;
  - "running" = the hook's running job is of this page's kind (not a local
    flag), so it survives navigation and refresh; `RunProgress` gets
    `since = Date.parse(job.created_at)` so elapsed time is real, not since mount;
  - when the latest job of this page's kind becomes `succeeded` with a
    `finished_at` newer than the page's last load, refetch the page data; its
    `result` supplies what the old response carried beyond the stored rows
    (e.g. `dropped_ungrounded_count`, warnings);
  - when the latest job of this page's kind is `failed`, show its `error_th`
    and finish time in the page's error slot, until a newer job of that kind
    succeeds;
  - a 409 shows its Thai detail; every start button (and the PLO merge
    button) is disabled while the program has a running job.
- PloReport: `report/run` becomes a job the same way. A button for
  `review/run` is not added here (no page has one today).
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
- routes (`spawn` patched): each of the seven returns 202 + `JobInfo`, still
  returns its old 404/422 synchronously without creating a job, and 409 when a
  job or a running session holds the program; `GET /jobs` and `/jobs/{id}`
  (404 on another program's job); `POST /sessions/`, `/approve`,
  `/plos/from-needs` and `/copy` answer 409 while a job runs.
- `JobInfo` timestamps serialize with `+00:00`.
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
- Other writers during a job — `PUT`/`DELETE` of a PLO, adding or deleting
  evidence, the evidence classify stream — behave as they do today.
- Fixing the Pipeline page's 7-hour session time (same naive-UTC cause; noted
  here because the jobs work found it).
- A "re-run the set review" button on PloReport.
