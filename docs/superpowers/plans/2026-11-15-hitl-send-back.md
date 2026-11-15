# HITL Send-Back Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A real "ส่งกลับ" button at both HITL checkpoints in both modes: per-PLO send-back with a reason, and whole-set Need send-back with a note.

**Architecture:** The PLO send-back is one job that calls the existing `stages/plo_redraft.redraft_from_needs` once per sent-back PLO, with the mode's own drafter, and stamps two new PLO columns (when it was sent back, and why). The review loop treats a sent-back PLO like a hand-edited one. The Need send-back is the existing re-run, with the note now reaching single mode.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy + Alembic, pytest; React 19 + Vite 8 + Tailwind v4 (no frontend test runner: verify with `npm run build`, `npm run lint`, mock mode).

**Spec:** `docs/superpowers/specs/2026-11-15-hitl-send-back-design.md`

## Global Constraints

- Branch `feat/four-agent-pipeline`. Run `git branch --show-current` before every commit; stage by explicit path.
- Commit trailer: `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
- **Never run alembic without `-x url=<copy DB>`.** The shared DB `curriculum_agent` is not touched by any task; the controller asks the user before migrating it.
- Never print or commit a secret, `.env`, `.env.demo` or `dist/`.
- CLAUDE.md conventions: type hints, `from __future__ import annotations`, loguru, async-first, repository pattern, prompts only in `prompts/`, Thai for user-facing strings.
- **No prompt text changes** except the single needs-task note (Task 4). With no note, that opening message must be byte-identical to today's.
- **The review loop must behave exactly as before when no PLO was sent back** (it is part of the locked pipeline).
- A single-mode program must never reach a multi prompt.
- Frontend: component classes and tokens from `frontend/src/index.css` only, no Tailwind palette colours; technical labels in English, Thai elsewhere.
- Every write route requires `X-API-Key` (`dependencies=[Depends(require_api_key)]`); the route-coverage test must stay green.

## Review Focus

1. A sent-back PLO whose Need was excluded or merged away since: that item reports the refusal in Thai, the others still run.
2. A send-back request naming a `plo_id` that no longer exists (set changed while the page was open): 404-style per-item refusal, nothing written for it.
3. Two items in one request citing the same PLO: refused with 422 before any job starts.
4. A reason that is empty or whitespace: 422, no job.
5. A review run after a send-back whose finding names both a sent-back PLO and a normal one (a redundancy pair): the action is skipped, as for a hand-edited PLO.

---

### Task 1: PLO columns for a designer send-back

**Files:**
- Modify: `src/curriculum_agent/models.py` (class `PLO`, near `designer_edited_at` at line ~583)
- Modify: `src/curriculum_agent/data/orm.py` (near line 182)
- Modify: `src/curriculum_agent/data/repositories.py` (PLO row mapping near line 126; `PLORepository.replace` near lines 709-770)
- Create: `migrations/versions/<rev>_plo_designer_send_back.py` (down_revision `c8e3f4a5b627`)
- Test: `tests/unit/test_plo_send_back_fields.py`

**Interfaces:**
- Produces: `PLO.designer_sent_back_at: datetime | None = None` (naive UTC, serialised with offset like `designer_edited_at`) and `PLO.designer_send_back_reason_th: str | None = None`. `PLORepository.replace(..., cause="send_back")` is accepted. A `cause="review"` replace that would supersede a PLO with `designer_sent_back_at` set raises the same error it raises for `designer_edited_at`.

- [ ] **Step 1: Failing tests**: a PLO round-trips both fields through the repository mapping helpers; JSON carries the offset; a `review` replace over a sent-back row raises like the hand-edited case (copy that existing test's setup); a `send_back` replace over a hand-edited row is allowed.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_plo_send_back_fields.py -q` → FAIL.
- [ ] **Step 3: Implement** the fields, ORM columns (`DateTime` nullable, `Text` nullable), mapping, the guard in `replace`, and the migration (add/drop two columns on `plos`). Follow `a6c1d2e3f405_plo_reports_and_designer_edit.py`.
- [ ] **Step 4: Run** the test file and `uv run pytest -q` → PASS. Do not run alembic.
- [ ] **Step 5: Commit** `feat(plo): columns recording a designer send-back`.

### Task 2: Send-back stage, job and route

**Files:**
- Create: `src/curriculum_agent/stages/plo_send_back.py`
- Modify: `src/curriculum_agent/models.py` (`JobKind` literal at ~1013; new request/result models)
- Modify: `src/curriculum_agent/api/jobs.py` (kind label map at ~64: `"plo_send_back": "ส่งกลับ PLO ให้ AI แก้"`)
- Modify: `src/curriculum_agent/api/routes/plos.py` (new route; reuse `_single_drafter`)
- Test: `tests/unit/test_plo_send_back.py`, `tests/unit/test_plo_send_back_route.py`

**Interfaces:**
- Consumes: Task 1 fields; `redraft_from_needs(program, program_id, need_ids, *, note_th, cause, drafter)`; `RedraftRefused(.status, .detail_th)`, `RedraftFailed`.
- Produces:
  - `class PloSendBackItem(BaseModel)`: `plo_id: str`, `reason_th: str` (stripped, 1..`NOTE_MAX_CHARS`).
  - `class PloSendBackRequest(BaseModel)`: `items: list[PloSendBackItem]` (1..`MAX_CORE_PLOS` + optional count is not bounded; require ≥1, unique `plo_id`s).
  - `class PloSendBackOutcome(BaseModel)`: `plo_id: str`, `status: Literal["rewritten", "refused", "failed"]`, `detail_th: str = ""`, `result_plo_id: str | None = None`, `result_statement_th: str | None = None`.
  - `class PloSendBackResult(BaseModel)`: `outcomes: list[PloSendBackOutcome]`.
  - `async def send_back_plos(program: ProgramMetadata, program_id: str, items: Sequence[PloSendBackItem], *, drafter: Callable[..., Awaitable[PLO | None]]) -> PloSendBackResult`.
  - `POST /programs/{program_id}/plos/send-back` → 202 `JobInfo`, job kind `plo_send_back`, params `{"plo_ids": [...]}` (reasons are not put in job params).

**Behaviour the tests pin:**
- Items run in request order. For each: load the live PLO by id (missing → `refused`, "ไม่พบ PLO นี้แล้ว — ชุด PLO เปลี่ยนไป"); call `redraft_from_needs` with `need_ids=list(plo.source_need_ids)`, `note_th=reason_th`, `cause="send_back"`.
- The drafter handed to `redraft_from_needs` wraps the mode's drafter and returns the draft with `designer_sent_back_at=<now, naive UTC>` and `designer_send_back_reason_th=reason_th` set. Multi wraps `synthesize_from_needs` (whatever `redraft_from_needs` uses by default — read it and pass that same callable); single wraps `_single_drafter(program_id)`.
- `RedraftRefused` → `refused` with its `detail_th`; `RedraftFailed` → `failed`, "AI เขียนข้อนี้ใหม่ไม่สำเร็จ"; later items still run.
- Route: 404 unknown program; 422 on empty items, blank reason, duplicate `plo_id`; `start_job_or_409` for single-flight; work runs inside `llm_scope(program_id=program_id)`.
- A test asserts a single-mode program's send-back never calls `synthesize_from_needs` (patch it to raise).

- [ ] **Step 1: Failing tests** for the behaviours above (stage with fake drafter and patched `redraft_from_needs`; route with the existing route-test fixtures, see `tests/unit/test_single_run_routes.py`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both files and `uv run pytest -q` → PASS (the write-route API-key coverage test included).
- [ ] **Step 5: Commit** `feat(plo): designer send-back of single PLOs as a job`.

### Task 3: Review loop leaves sent-back PLOs alone

**Files:**
- Modify: `src/curriculum_agent/stages/plo_feedback.py` (guards at ~309 and ~550)
- Test: `tests/unit/test_plo_feedback.py` (extend, next to the hand-edited tests)

**Interfaces:**
- Consumes: `PLO.designer_sent_back_at`.

- [ ] **Step 1: Failing tests**: each existing "hand-edited PLO is skipped" test gets a twin with `designer_sent_back_at` set and `designer_edited_at` None, asserting the same skip outcome and reason path; one test asserts a redundancy finding naming a sent-back PLO and a normal PLO is skipped.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** with one private helper `_designer_owned(plo: PLO) -> bool` (`designer_edited_at` or `designer_sent_back_at` set) used at both guards. No other change to the file. The existing tests with neither field set must pass unmodified: that is the proof the locked loop is unchanged.
- [ ] **Step 4: Run** `uv run pytest tests/unit/test_plo_feedback.py -q` and the full suite → PASS.
- [ ] **Step 5: Commit** `feat(review): never rewrite a PLO the designer sent back`.

### Task 4: Single-mode Need run accepts a note

**Files:**
- Modify: `src/curriculum_agent/prompts/single_agent.py` (`build_needs_task` at ~424)
- Modify: `src/curriculum_agent/stages/single_needs.py` (`run_single_needs` at ~280)
- Modify: `src/curriculum_agent/api/routes/needs.py` (`_start_single_needs` at ~418 and its caller)
- Modify: `docs/prompt-inventory.md` (regenerate), `scripts/dump_prompts.py` only if it needs a new sample
- Test: `tests/unit/test_single_agent_prompt.py`, `tests/unit/test_single_needs.py`, `tests/unit/test_single_run_routes.py`

**Interfaces:**
- Produces: `build_needs_task(..., note_th: str | None = None)` ending with `append_note(text, note_th)` exactly as `build_plos_task` does; `run_single_needs(program_id: str, note_th: str | None = None)`; `POST /needs/run` on a single program passes `body.note_th`; job params `{"note_th": note_th}`.

- [ ] **Step 1: Failing tests**: `build_needs_task(..., note_th=None)` equals the output of the current function for the same inputs (capture the current output first by calling without the argument: assert `build_needs_task(**kw) == build_needs_task(**kw, note_th=None)` and that neither contains the note policy text); with a note, the text ends with what `append_note` produces; the route test asserts the note reaches `run_single_needs`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the three files; `uv run python scripts/dump_prompts.py` then `--check` → current; full suite → PASS.
- [ ] **Step 5: Commit** `feat(single): designer note on the Need run`.

### Task 5: Frontend and mock

**Files:**
- Modify: `frontend/src/pages/PloReview.tsx` (send-back list near the approve panel; both the review branch and the no-review branch a single program sees)
- Create: `frontend/src/pages/components/SendBackList.tsx`
- Modify: `frontend/src/pages/PloSynthesis.tsx` (PLO card chip)
- Modify: `frontend/src/pages/NeedAnalysis.tsx` (lines ~117-135 and ~324-365)
- Modify: the PLO type file used by these pages (add the two fields), `frontend/src/pages/components/feedbackJobs.ts` or the job-kind constants where `single_plos` is listed (add `plo_send_back`)
- Modify: `frontend/src/mock/handlers.ts`, `frontend/src/mock/db.ts`, `frontend/src/mock/scenarios.ts`

**Interfaces:**
- Consumes: `POST /programs/{id}/plos/send-back` body `{items: [{plo_id, reason_th}]}` → job; job result `{outcomes: [{plo_id, status, detail_th, result_plo_id, result_statement_th}]}`; PLO fields `designer_sent_back_at`, `designer_send_back_reason_th`; `POST /needs/run` body `{note_th}` for single.

**What the designer sees:**
- PLO checkpoint page: a section "ส่งกลับ PLO ให้ AI แก้" listing every current PLO (id, statement in `record` text). Each row has a "ส่งกลับ" toggle; ticking opens a required reason textarea ("เหตุผลที่ส่งกลับ"). One button "ส่งกลับให้ AI แก้ (N ข้อ)", disabled when N=0, when any ticked reason is blank, or while a job runs. While the job runs: `RunProgress`. After it: per-item result lines (rewritten / refused / failed with `detail_th`), and the PLO list reloads.
- In multi, after a send-back the existing stale notice shows; add one sentence under it: "ข้อที่ส่งกลับจะไม่ถูกระบบตรวจเขียนทับ".
- PLO card (PloSynthesis) and the send-back list: a PLO with `designer_sent_back_at` shows chip `chip chip-marker` "ส่งกลับโดยผู้ออกแบบ" with the reason as `title` tooltip and visible text under the statement.
- Need page: the re-run button reads "ส่งกลับให้ AI ทำใหม่" in both modes; `DesignerNote` shows in both modes (remove the `!single` condition); single sends `{note_th}`. Before sending, `window.confirm` is not used: use the page's existing confirm pattern if one exists, else an inline two-step button ("ยืนยันส่งกลับ" / "ยกเลิก") with the text "ชุด Need ปัจจุบันจะถูกแทนที่ด้วยชุดใหม่".
- Mock: handlers for `plos/send-back` (rewrites the statement with a visible marker, sets both fields, supports one refused item when the reason contains "ทดสอบปฏิเสธ"), and single `needs/run` accepting a note.

- [ ] **Step 1: Implement** the above.
- [ ] **Step 2: Verify** `npm run build` and `npm run lint` in `frontend/` → both pass.
- [ ] **Step 3: Verify in mock mode** (`npm run dev:mock`, port 5174; if it is already running, reuse it): send back two PLOs with reasons, see results and chips; trigger the refused path; send back Needs with a note in a single program and a multi program. Report what was seen, and say plainly if a path could not be exercised.
- [ ] **Step 4: Commit** `feat(ui): send-back controls at the Need and PLO checkpoints`.

### Task 6: Docs and the lock record

**Files:**
- Modify: `CLAUDE.md` (rule 7 paragraph and the single-mode paragraph: one sentence each), `.claude/rules/plo-review.md`, `.claude/rules/api-data.md`, skill `references/data-schemas.md` (two PLO fields, job kind)
- Modify: `scripts/lock_manifest.py` (add `curriculum_agent.stages.need_dedup` to the constants modules so `MAX_GROUP_SIZE` appears), `tests/unit/test_lock_manifest.py` (assert `MAX_GROUP_SIZE` is listed)
- Add: `.scratch/reports/2026-11-14-cache-off-lock-runs.md` (already written, untracked; commit as is)
- Create: `docs/research/locks/2026-11-15-phase1-lock.md`

- [ ] **Step 1: Docs** updated; `uv run python scripts/dump_prompts.py --check` → current.
- [ ] **Step 2: Manifest fix** with its test; `uv run pytest tests/unit/test_lock_manifest.py -q` → PASS. Commit docs + fix + the lock-run report: `docs: send-back in the manuals; lock manifest lists MAX_GROUP_SIZE`.
- [ ] **Step 3: Generate the record** on the clean tree: PowerShell `$env:LLM_CACHE_ENABLED='false'; uv run python scripts/lock_manifest.py | Out-File -Encoding utf8 $env:TEMP\phase1-lock.md`, then copy that file to `docs/research/locks/2026-11-15-phase1-lock.md` (writing straight into the repo would make the tree dirty while the script reads it). It must not say DIRTY and must not contain a secret (grep for `sk-`, `://`, `api_key`, `secret`, `dsn`). Prepend a short header: what the lock is for (Research Plan ระยะ 1), the lock-run evidence (multi 3/3 cache-off round 1; single 3/3 round 3; report path), that temperature is 0 in the six listed calls and provider default elsewhere by the designer's decision, and that the single needs-task note text is used only when a designer attaches a note.
- [ ] **Step 4: Commit** `docs(research): phase-1 lock record`. Do not tag and do not push: the controller does both after the final review, with the user's go-ahead for the push.
