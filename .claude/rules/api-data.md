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

- **Every write route carries `require_api_key`, and a test walks the routes to prove it.** `tests/unit/test_api_auth_coverage.py` fails for any POST/PUT/PATCH/DELETE `APIRoute` without it (allowlist empty); add the `dependencies=[Depends(require_api_key)]` to a new write route. GETs stay open. Auth is off when `API_KEY` is unset or blank. The UI types the key once per tab (`sessionStorage['curriculum.apiKey']`, `frontend/src/api/apiKey.ts`), `client.ts` sends it and retries a 401 once after `ApiKeyDialog`; the classify-stream `fetch` goes through `fetchWithKey`. Mock mode never returns 401.
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
  registration for its whole stream. A graph session *suspended* at the
  evidence checkpoint is not busy, so evidence is editable while it waits —
  which is why `review_stakeholder_needs` reloads evidence from
  `EvidenceRepository` on resume and re-derives `classified_evidence` with
  `stakeholder_needs.classify_single`, exactly as `review_needs` reloads Needs:
  extraction reads state, and a checkpoint's copy would extract skills from text
  the rows no longer hold. A failed first extraction writes nothing,
  so it does not lock. Seed scripts and the copy write through repositories and
  are not designer edits. `POST /programs/{id}/copy` takes `{"mode":
  "evidence_only"}` to clone metadata and evidence only — no skills, groups,
  Needs, PLOs, review or report — which leaves the copy unlocked; no body is `full`.
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
  `/needs/{id}/split`, `/copy`, `DELETE /programs/{id}` — every model call writes a usage row pointing at the program, and a row landing between the cascade's deletes would fail it) with a Thai 409 — every stage deletes and rewrites what the next one
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
  bodies — and stubs the running-session check and the session sweep. It also
  replaces `api/routes/plos._start_review_job` with a recorder (fixture
  `review_chain_calls`): the `/plos/run` chain reached it through the
  module-level `_repo`, so every synthesis-route test made a real asyncpg connect
  and left an unawaited `Connection._cancel` warning. A test or module that drives
  the real review job (`/plos/review/run`, the chain) marks itself `review_chain`.
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
- **`POST /plos/from-needs` takes 2-5 Needs, and what it replaces is kept.** More than `MAX_GROUP_SIZE` (`stages/need_dedup.py`) answers 422 "เลือก Need 2-5 ข้อเพื่อรวมเป็น PLO" before any lock, DB read or LLM call. `PLORepository.replace` snapshots every removed PLO into `superseded_plos` (`superseded_by` = the new PLO id, naive-UTC `superseded_at`) in the same transaction as the delete; `delete_by_program` and `ProgramRepository.delete_cascade` clear it, a full copy clones it with remapped ids, `evidence_only` copies none. `GET /programs/{id}/plos/superseded` is a read (404 unknown program) and `SupersededPLORepository.list_by_program` skips a snapshot failing `PLO.model_validate`. There is no restore. "Attach a Need to a PLO" in the UI is this same call with the card's `source_need_ids` plus one unused Need, no note. The picker's replaced-PLO preview uses `plosCiting` (`frontend/src/pages/components/plosCiting.ts`), the client mirror of `plos_citing`; the cap is `MAX_MERGE_NEEDS` (`frontend/src/constants/needPolicy.ts`, mirrors `MAX_GROUP_SIZE`) — change each pair together.
- **`plo_redraft` is the one core behind the designer's merge and Agent 4's send-back, and it takes no lock.** `stages/plo_redraft.redraft_from_needs` (the old `_merge_needs` body) holds every bound and check of the merge and writes through `PLORepository.replace`. The checks before the draft are one pure function, `check_redraft(existing, all_needs, need_ids)`, which send-back's dry run calls too. **The write is optimistic, and so is `PUT /plos/{id}`:** the PUT is update-only and version-conditional (`PLORepository.update_if_version(plo, expected_version=...)` is `UPDATE ... WHERE program_id, plo_id, version`, never an insert), so a PUT racing a redraft or another PUT answers 409 "PLO นี้ถูกเปลี่ยนระหว่างแก้ไข — โหลดใหม่แล้วลองอีกครั้ง" instead of re-inserting a merged-away PLO. The revalidate job writes through the same `update_if_version` and fails with `error_th` "PLO นี้ถูกแก้ระหว่างตรวจ SMART — ตรวจใหม่อีกครั้ง". A redraft that reuses a PLO id (the lowest freed slot) stores the new outcome at the superseded row's version + 1, so a stale PUT or revalidate that read the old row never matches the new one (a synthesis re-run, delete then insert at v1, is accepted as designer-initiated). The draft takes minutes and nothing blocks `PUT /plos/{id}` meanwhile, so `replace(..., expect={plo_id: version})` re-reads the superseded rows `FOR UPDATE` in its own transaction and raises `PLOChangedDuringRedraft` with nothing written when one is gone, has a different `version` (any PUT bumps it, so a PUT that changed only the verb, Bloom level or rationale refuses too), or — on a `cause="review"` replace — carries `designer_edited_at`; `redraft_from_needs` turns that into `RedraftRefused(409, "PLO นี้ถูกแก้ระหว่างร่างใหม่ — ไม่เขียนทับ")`, a 409 on `from-needs` and a `skipped` row for send-back. `replace(..., trail_row=...)` inserts send-back's applied `plo_feedback_actions` row in the same transaction, so a change and its trail row land together. It registers no writer: `POST /plos/from-needs` wraps it in `sync_writer` with `cause="designer"`, while send-back runs inside the review job or graph session, which already hold the program busy, and passes `cause="review"` — a second registration there would 409 against itself. `superseded_plos.cause` is `designer` | `review` | null (null reads as designer, for older rows). `plo_feedback_actions` (`GET /programs/{id}/plos/feedback`, newest first) has the life of `superseded_plos`: cleared by `delete_by_program` and program delete, cloned with remapped ids by a full copy, not by `evidence_only`. The review job's result is `PLOReviewRunResponse` (`PLOReviewResponse` plus `feedback`); `GET /review` is unchanged. Since phase 6 `plo_feedback_actions` also has `round`, and the loop adds `kind="loop_end"` rows (`outcome="stopped"`) with the stop reason.
- **The PLO tail is `plo_synthesis -> plo_review -> [checkpoint] -> plo_report`, and the
  report is a stored artifact (phase 6, designer's decision of 2026-11-04).** Graph:
  `plo_synthesis -> plo_review -> review_plos_node -> plo_report -> END`;
  `REVIEW_NODE_STAGE` maps `review_plos_node` to `plo_review` and `DESIGNER_STAGES`
  ends `... plo_synthesis, plo_review, plo_report` (the frontend rail follows; change
  both together). `plo_report.run` reads the PLOs from the database, never from
  `state["plos"]`, writes no PLO, and stores its result in `plo_reports` (one row per
  program, `PLOReportRepository`): program, the PLO+Need fingerprint of the set it
  describes (`plo_review_facts.plo_fingerprint`, the review's own), `created_at`, and
  the report JSON in a JSONB column, so a new report field needs no migration.
  `stage_reached` answers `plo_report` for a *current* report, then `plo_review` for a
  current review, then `plo_synthesis`; both count only while their fingerprint
  matches, so the rail says "approved and reported" only for the set that was
  approved and goes back a stage the moment a PLO or a Need score moves. Life: cleared
  by `PLORepository.delete_by_program` and by program delete, copied by a full
  `POST /programs/{id}/copy` (id-remapped, and re-fingerprinted when it was current
  for the source, exactly like the review; a stale one stays stale), not by
  `evidence_only`. `GET /programs/{id}/plos/report` answers `PLOReportStored`:
  `report` (None when none was built), `stale` (the stored fingerprint against the
  live set) and `created_at`; 404 for an unknown program. The review's `GET /review`
  is unchanged.
- **`POST /plos/run` chains the review job, so synthesis -> review is one tail with no
  checkpoint between.** `start_job_or_409(..., on_success=chain)` starts the
  `plo_review` job through `_start_review_job(or_409=False)` when synthesis
  succeeds, the way `/needs/run` starts Agent 2: each job stores its output, shows
  in `GET /jobs` and has its own budget. A conflict or "no PLO stored" is logged and
  the synthesis job stays succeeded. `/plos/review/run` runs the **whole loop**
  (`plo_review_loop`, mode from `settings.plo_review_loop_mode`) and its result,
  `PLOReviewRunResponse`, carries every trail row the call wrote, rounds included;
  `GET /programs/{id}/plos/feedback` has the whole trail with each row's `round` (0
  for a single pass and for older rows) and the `loop_end` row that says why the loop
  stopped. `POST /plos/report/run` stays the designer's button: on the page path it
  is the equivalent of approving the set, and it runs only the report; a graph
  session approves on the Pipeline page instead, which resumes `review_plos_node`.
- **Resume at the PLO checkpoint reloads the PLOs from the database.** Like
  `review_needs` and `review_stakeholder_needs`, `graph.review_plos` re-reads
  `PLORepository` after the `interrupt` returns and rebuilds `state["plos"]` from it:
  the designer may have edited, merged or deleted PLOs while the session was
  suspended, and the review's send-back changed them before that, while the
  checkpoint holds the set as it was. Before phase 6 it did not, so `plo_report`
  upserted the checkpoint's stale copy over the edit; `plo_report` now also reads
  from the database, and both are needed (`test_review_plos_resume_reloads_edited_plos`
  pins it).
- **`designer_edited_at` is set by `PUT /plos/{id}` with a changed statement and
  cleared by nothing.** It is a nullable column on `plos` (migration
  `a6c1d2e3f405`), naive UTC in the DB and with `+00:00` in JSON. A `PUT` that
  leaves the statement unchanged does not set it. `revalidate` copies the stored
  value onto the rebuilt row; `PLORepository.replace` writes the replacing draft
  without it, so the marker goes with the row and a PLO the designer replaces through
  `from-needs` is a new draft. The marker, not `smart_validated_by="stale"`, is what
  send-back (`unavailable_reason`) and `allow_repair` read, because a revalidate
  overwrites `stale`. A program copy carries it (rows are cloned by column).
- **`llm_usage` has the life of the program's own rows, not of a run.** One row per
  provider response (`LLMUsage`, instructor retries included), attributed by
  `llm_context.llm_scope(program_id=..., job_id=... | session_id=...)`. The scope is set in
  `jobs._run` (every background job), in the graph session runner (`sessions.py`),
  and around the two synchronous LLM writers, `POST /plos/from-needs` and
  `POST /needs/merge`; a call made outside any of them is stored with null
  attribution and counts nowhere. `ProgramRepository.delete_cascade` deletes the
  program's rows; a program copy does **not** copy them (the copy has spent
  nothing); and a re-run does **not** clear them — usage is a ledger of what was
  spent, and a re-run is more spending. `GET /programs/{id}/usage` (404 unknown
  program) returns `UsageSummary`: overall, per slot, per job newest first, and per graph
  session (`by_session`: rows with a session and no job; rows with neither stay only in
  `total`/`by_slot`), with
  `JobUsage.label_th` filled by the route from `JOB_KIND_LABEL_TH` (empty for an
  unknown kind, so the page keeps no copy of the map). It is a read; nothing
  upstream reads usage.
