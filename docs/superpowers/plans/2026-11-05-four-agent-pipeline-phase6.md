# Four-agent pipeline phase 6 (voted SMART loop, review repair loop, report last) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the designer's PLO approval and the report to the end of the tail. Vote the SMART agent and the review over 5 runs (3 must agree). Loop repair → re-judge (SMART ≤3 repairs, review ≤5 send-backs). Every change gets a trail row, and whatever stays unfixed is a comment.

**Architecture:** The work comes in three gated parts, matching spec decision 26.
- **6a (no LLM change):** reorder the graph tail; store the report as a `plo_reports` row; reload PLOs on resume; add a `designer_edited_at` marker.
- **6b:** split the SMART agent into judge-only runs, voted in pure code (`stages/smart_vote.py`), with one repair call per failed round.
- **6c:** extend the review with alignment, verb and voices, and add the KSEC-gap action. Put a loop module (`stages/plo_review_loop.py`) around review → send-back, behind `plo_review_loop_mode` (default `shadow`).
- **Gates:** the controller measures on the copy DB after 6b and after 6c.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, LangGraph, Instructor + Pydantic v2, pytest; React + TypeScript + Vite with mock handlers.

**Spec:** `docs/superpowers/specs/2026-11-04-four-agent-pipeline-phase6-design.md` (decision numbers below are the spec's). Baseline: `.scratch/reports/2026-11-04-phase6-baseline.md`.

## Global Constraints

- **Branch and git:**
  - Work on `feat/four-agent-pipeline`. Run `git branch --show-current` before every commit.
  - Stage by explicit path. Never `git add -A`. Never commit `.env`, `.env.demo` or `dist/`.
  - Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Database:**
  - Implementers never run `alembic`, never connect to a database and never start the backend. The controller applies migrations to the copy DB `curriculum_phase1` only, always with `-x url=`.
  - Never print DSNs, passwords or API keys.
  - Alembic head today is `e5a9c2f7b318`.
- **Code conventions:**
  - `from __future__ import annotations`, type hints everywhere, `loguru`, repository pattern.
  - Prompts live only in `src/curriculum_agent/prompts/`, as typed builders.
  - Thai for user-facing strings; English for code, comments and logs.
  - Match the comment density of the surrounding file.
- **Timestamps:** DB timestamps are naive UTC (`datetime.now(UTC).replace(tzinfo=None)`). JSON output carries `+00:00` (`field_serializer(..., when_used="json")`). A python-mode dump keeps the `datetime`, because ORM `DateTime` columns reject ISO strings.
- **Immutable rules stay intact:**
  - `hard_failures` on the final statement alone sets `smart_escalated`. No agent can clear a hard failure. Soft criteria never escalate.
  - The reviewer never sees evidence text, member skill names, `rationale_th` or SMART diagnoses.
- **Frontend:** no Tailwind palette colours; use component classes and inks from `index.css`; use `animate-run-sweep`, no spinner.
- **Verify, backend:**
  - `uv run pytest -q`
  - `uv run ruff check src tests`
  - `uv run ruff format --check src tests`
  - `uv run mypy src`
  - `uv run python scripts/dump_prompts.py --check`. When it fails because a builder changed, regenerate `docs/prompt-inventory.md` with the script and commit it.
- **Verify, frontend:** `npm run build` and `npm run lint` (0 errors, 1 known warning), from `frontend/`.

## Review Focus

1. **The validation endpoint fails some runs of a round.** When fewer runs succeed than `validation_runs // 2 + 1`, that round's soft verdicts are not used: no soft flag is manufactured and only hard failures drive repair. When no round ever voted, the PLO is `smart_validated_by="code_only"`. Owner: Task 5, test `test_too_few_runs_use_no_soft_verdicts`.
2. **The designer edits a PLO while a session is suspended at the plo_review checkpoint, then approves.** The report shows the edited statement, and the stored PLO is not overwritten by the checkpoint's copy. Owner: Task 2, test `test_review_plos_resume_reloads_edited_plos`.
3. **Every action in a loop round is skipped** (designer-edited, floors, already merged). The loop stops after that round with reason "no change": no further review, and the session still succeeds. Owner: Task 9, test `test_loop_stops_when_round_applies_nothing`.
4. **A repair that introduces a hard failure the previous statement did not have** is discarded. The previous statement stays and the round is used up. Owner: Task 5, test `test_repair_adding_hard_failure_is_discarded`.
5. **A redraft note quoting an escalated statement that contains a forbidden word** carries no forbidden word. The word is masked, and every note builder is tested over a statement with `เข้าใจ`. Owner: Task 8, test `test_notes_never_carry_forbidden_words`.

---

## Part 6a — order, report artifact, resume reload, hand-edit marker (no LLM change)

### Task 1: storage — `designer_edited_at`, `plo_reports`, send-back skip for hand-edited PLOs

**Files:**
- `src/curriculum_agent/models.py`
- `src/curriculum_agent/data/orm.py`
- new migration `migrations/versions/a6c1d2e3f405_plo_reports_and_designer_edit.py` (down `e5a9c2f7b318`)
- `src/curriculum_agent/data/repositories.py`
- `src/curriculum_agent/data/program_copy.py`
- `src/curriculum_agent/api/routes/plos.py` (PUT only)
- `src/curriculum_agent/stages/plo_feedback.py`
- tests: new `tests/unit/test_plo_report_storage.py`; extend `tests/unit/test_api_plos.py`, `tests/unit/test_plo_feedback.py` and `tests/unit/test_program_copy_build.py`

**Interfaces — produces:**
- **`PLO.designer_edited_at: datetime | None = None`.**
  - JSON-serialised with `+00:00`.
  - ORM column `plos.designer_edited_at`, DateTime, nullable.
  - Every `PLORepository` write (`bulk_insert`, `replace`, update) must hand the ORM a `datetime`, not the JSON string. Convert at the repository, the single place rows are built.
- **`PLOReport` model:** `program_id: str`, `plo_fingerprint: str`, `created_at: datetime` (JSON `+00:00`), `report: dict[str, Any]`. ORM `plo_reports`: `program_id` is both PK and FK to programs, `plo_fingerprint String(64)`, `created_at DateTime`, `report JSONB`.
- **`PLOReportRepository`:** `upsert(report: PLOReport) -> None`, `get(program_id) -> PLOReport | None`, `delete_by_program(program_id) -> None`.
- **Lifecycle:**
  - `PLORepository.delete_by_program` clears `plo_reports` too.
  - `ProgramRepository.delete_cascade` deletes `plo_reports` before `programs`.
  - A full copy clones the row and re-fingerprints it exactly the way the copy re-fingerprints a current review: a current report stays current and a stale one stays stale.
  - `evidence_only` copies none.
- **`PUT /plos/{id}`:** sets `designer_edited_at = now` (naive UTC) when `statement_th` changes, next to the existing `stale` marking. An unchanged statement leaves the field as it was. `revalidate` keeps it. Nothing else clears it.
- **`plo_feedback.REASON_DESIGNER_EDITED = "PLO นี้ผู้ออกแบบแก้เอง — ไม่เขียนทับ"`.**
  - Any send-back action that would replace a PLO with `designer_edited_at` set is recorded `skipped` with this reason before `redraft_from_needs` is called:
    - a redundancy naming it;
    - a Bloom finding on it;
    - an unused-Need draft whose `plos_citing` includes it.
  - Check order inside `unavailable_reason`: replaced this round → edited since review → designer-edited → missing.

**Steps:**
- [ ] **Step 1: write the failing tests.**
  - `test_put_changed_statement_sets_designer_edited_at`
  - `test_put_same_statement_keeps_designer_edited_at_none`
  - `test_revalidate_keeps_designer_edited_at`
  - `test_bulk_insert_round_trips_designer_edited_at`
  - `test_plo_report_upsert_get_replace`
  - `test_delete_by_program_clears_plo_reports`
  - `test_delete_cascade_clears_plo_reports`
  - copy cases: `full_copies_report_refingerprinted`, `evidence_only_copies_no_report`
  - `test_send_back_skips_designer_edited_plo` (redundancy, bloom and unused cases; `redraft_from_needs` not called; exact reason text)

  Follow the mocking style of `tests/unit/test_superseded_plos.py` and `tests/unit/test_plo_feedback.py`.
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.** The migration adds the column and creates the table with `program_id` as PK; downgrade reverses both.
- [ ] **Step 4: run the full backend verify and confirm PASS.**
- [ ] **Step 5: commit** `feat(data): plo_reports artifact and designer_edited_at marker`.

### Task 2: graph tail, stage order, report from the DB, chained review

**Files:**
- `src/curriculum_agent/graph.py`
- `src/curriculum_agent/stages/plo_report.py`
- `src/curriculum_agent/stages/plo_review.py` (`run` only)
- `src/curriculum_agent/data/repositories.py` (`list_summaries` stage)
- `src/curriculum_agent/api/routes/plos.py`
- tests: `tests/unit/test_session_stage_mapping.py`, `tests/unit/test_graph*.py` (whichever pin the edges and `stage_reached`), `tests/unit/test_api_plos.py`, new `tests/unit/test_plo_report_stage.py`

**Interfaces:**
- **Consumes** from Task 1: `PLOReportRepository`, `PLOReport`.
- **Graph edges:** `plo_synthesis → plo_review → review_plos_node → plo_report → END`.
- **Stage lists:**
  - `DESIGNER_STAGES = (..., "plo_synthesis", "plo_review", "plo_report")`.
  - `REVIEW_NODE_STAGE["review_plos_node"] = "plo_review"`.
- **`review_plos`:**
  - Becomes `async`.
  - After `interrupt`, reloads `PLORepository().list_by_program(program_id)` into `state["plos"]`, as `review_needs` does.
  - Interrupt text: `"PLO review complete — approve the PLO set before the report"`.
- **`plo_review.run`:** after the review, reloads the stored PLOs into `state["plos"]`, because send-back may have changed them.
- **`stage_reached(..., has_current_review: bool = False, has_current_report: bool = False) -> str`:**
  - Returns, in this order: `plo_report` when the report is current; `plo_review` when the review is current; `plo_synthesis` when PLOs exist; then the old chain.
  - Update the docstring paragraph about the report leaving no artifact.
  - `list_summaries` computes `has_current_report` with the same fingerprint (`plo_fingerprint(plos, need_demands(needs))`) the review uses.
- **`plo_report.run`:**
  - Reads PLOs from `PLORepository` and ignores `state["plos"]` for persistence.
  - No longer calls `bulk_insert`.
  - Raises the existing `ValueError` text when none are stored.
  - Builds the same `report` dict, then upserts a `PLOReport` whose fingerprint is computed from the stored PLOs and the active Needs' demands.
  - Sets `state["plos"]`, `state["report"]` and `current_stage="plo_report"` as before.
- **`GET /programs/{id}/plos/report`:**
  - Returns `PLOReportStored {report: PLOReportResponse | None, stale: bool, created_at: datetime | None}`.
  - `report=None` when no row exists. 404 for an unknown program.
  - Declared before `/{plo_id}` routes.
- **`POST /plos/run`:**
  - On success, chains the review job through `start_job_or_409(..., on_success=chain)`, the way `/needs/run` chains Agent 2.
  - The review-job start moves into `_start_review_job(program_id, *, or_409: bool) -> JobInfo`, shared with `POST /plos/review/run`.
  - The chained start uses `or_409=False`; a `JobConflict` there is logged, and the synthesis job stays succeeded.

**Steps:**
- [ ] **Step 1: write the failing tests.**
  - The mapping test against the compiled graph.
  - Edge order.
  - `stage_reached` precedence: report > review > plos.
  - `test_review_plos_resume_reloads_edited_plos`: the stored PLO statement differs from the state's; after the node, the state holds the stored one.
  - `test_plo_report_stores_row_and_does_not_bulk_insert`.
  - `test_plo_report_reads_stored_not_state`.
  - `GET /plos/report`: 200 with a report, 200 with `report=None`, 404.
  - `test_plos_run_chains_review_job` (use `spawned.drain()`).
  - `test_plos_run_chain_conflict_keeps_synthesis_succeeded`.
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: run the full backend verify and confirm PASS.**
- [ ] **Step 5: commit** `feat(graph): review before the PLO checkpoint, report last and stored`.

### Task 3: UI for the new order

**Files:**
- `frontend/src/constants/stages.ts`
- `frontend/src/pages/PloReview.tsx`
- `frontend/src/pages/PloReport.tsx`
- `frontend/src/pages/PloSynthesis.tsx`
- `frontend/src/api/*` (a client for `GET /plos/report`)
- `frontend/src/mock/handlers.ts`
- any type file holding the stage union

**Interfaces — consumes:** Task 2 routes.

- [ ] **Step 1: rail order and copy.**
  - Stage 6 is `plo_review`: "ตรวจคุณภาพชุด PLO", with summary "ตรวจทั้งชุด ส่งกลับไปแก้ แล้วผู้ออกแบบอนุมัติ" and `gateNote: 'ตรวจและอนุมัติที่ขั้นนี้'`.
  - Stage 7 is `plo_report`: "รายงาน PLO", with summary "ชุด PLO สุดท้ายหลังอนุมัติ ย้อนรอยหลักฐาน และส่งออก".
  - Fix every hard-coded stage list and order array the pages use: `PloReview.tsx:28`, `PloReport.tsx:66` and similar.
- [ ] **Step 2: approve on the review page.**
  - The review page gets a primary action "อนุมัติชุด PLO และออกรายงาน", which starts `POST /plos/report/run` and navigates to the report page when that job succeeds.
  - It is disabled while any job runs or the review is stale. A stale review shows "ชุด PLO เปลี่ยนหลังการตรวจ — ตรวจใหม่ก่อนอนุมัติ" and the existing re-run button.
  - Graph-session approval stays on the Pipeline page.
- [ ] **Step 3: the report page reads the stored report.**
  - It loads `GET /plos/report` and shows the stored report, labelled stale when `stale`.
  - With no report, it shows "ยังไม่ได้อนุมัติชุด PLO" and a link to the review page.
  - It no longer offers a run button of its own.
- [ ] **Step 4: the PLO page.** Reload on `plo_review` jobs too, because the chained review changes PLOs, and show that a review runs after synthesis.
- [ ] **Step 5: mocks.**
  - Add `GET /plos/report`.
  - The mock `/plos/run` appends a chained review job.
  - The mock report run stores the report.
- [ ] **Step 6: run `npm run build` and `npm run lint`.**
- [ ] **Step 7: commit** `feat(ui): review before approval, report last`.

## Part 6b — voted SMART loop

### Task 4: pure vote module

**Files:** new `src/curriculum_agent/stages/smart_vote.py`; test `tests/unit/test_smart_vote.py`.

**Interfaces — produces:**

```python
@dataclass(frozen=True)
class JudgeRun:
    failed: frozenset[SmartFindingCode]          # soft codes this run failed
    notes_th: Mapping[SmartFindingCode, str]     # per failed code
    diagnosis_th: str
    repair_hint_th: str
    turns: int

@dataclass(frozen=True)
class SoftVote:
    threshold: int
    runs_requested: int
    runs_used: int
    failed: tuple[SmartFindingCode, ...]          # majority-failed, in _SOFT_VERDICTS order
    representative: JudgeRun

REPAIR_EXCLUDED: frozenset[SmartFindingCode]  # {A_ACTOR, A_SCOPE} — decision 19
def vote_threshold(requested: int) -> int           # requested // 2 + 1
def first_batch_size(requested: int) -> int         # == vote_threshold(requested)
def is_decided(runs: Sequence[JudgeRun | None], requested: int) -> bool
def vote(runs: Sequence[JudgeRun | None], requested: int) -> SoftVote | None
def repairable(failed: Sequence[SmartFindingCode]) -> list[SmartFindingCode]
```

- **Definitions** (`None` is a run that failed; t = threshold; p = requested − len(runs); s = successful runs):
  - **`is_decided`** is true when (s ≥ t or s + p < t) **and**, for every soft code with f = the number of successful runs failing it, (f ≥ t or f + p < t).
  - **`vote`** returns None when s < t. Otherwise a code is failed when f ≥ t.
  - **Representative:** the successful run with the most majority-failed codes. Ties go to the fewest non-majority codes, then to the earliest run.
- **Soft-code order:** move `_SOFT_VERDICTS` (field → code) out of `smart_agent.py` into this module. `smart_agent` imports it, which avoids a cycle.

**Steps:**
- [ ] **Step 1: write the failing tests.**
  - Threshold 3 of 5; threshold 1 of 1.
  - Three unanimous passes are decided with 2 pending.
  - A 2–1 split is not decided.
  - Three runs that all fail `S_object` are decided, with `S_object` failed.
  - One failed run plus two successes, with 2 pending, is not decided.
  - `test_too_few_successes_vote_none` (2 of 5 succeeded, nothing pending → None).
  - The representative tie-break.
  - `repairable` drops `A_actor` and `A_scope` and keeps order.
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: run the tests and confirm PASS, plus mypy and ruff.**
- [ ] **Step 5: commit** `feat(smart): pure vote over SMART judge runs`.

### Task 5: the SMART agent becomes judge runs + voted repair loop

**Files:**
- `src/curriculum_agent/stages/smart_agent.py`
- `src/curriculum_agent/prompts/smart_agent.py`
- `src/curriculum_agent/config.py`
- `src/curriculum_agent/stages/plo_synthesis.py` (`validate_and_build` gains `allow_repair`)
- `src/curriculum_agent/api/routes/plos.py` (revalidate)
- `docs/prompt-inventory.md`
- tests: `tests/unit/test_smart_agent.py`, `tests/unit/test_smart_agent_prompt.py`, new `tests/unit/test_smart_voted_loop.py`

**Interfaces:**
- **Consumes** Task 4.
- **Settings:** `validation_runs: int = Field(default=5, ge=1)`. `validation_timeout_seconds` default becomes **600** and covers the whole per-PLO loop.
- **`Finish`** gains `repair_hint_th: str = Field(default="", max_length=400)`.
- **`JudgeStep`** (`reasoning_th` plus `CallTool | Finish`) replaces `ValidationStep` for judging. `RequestRepair` is removed from the model-facing schema; the class may stay as an internal carrier or be deleted.
- **Judge prompt:**
  - `build_smart_agent_prompt` no longer offers `request_repair`.
  - The "need-level actor/scope → send back to the Need stage, do not repair" rubric text stays, reworded as a diagnosis.
  - The rubric asks for `repair_hint_th`: what to change, never a full sentence.
- **`async def run_smart_agent(draft, ctx, metadata, *, enabled: bool = True, allow_repair: bool = True) -> SmartAgentResult`.** The DISABLED/SKIPPED exits are unchanged. Otherwise:
  1. **Judge a round.**
     - `_judge_once(draft, ctx, metadata) -> JudgeRun | None` is today's loop body minus repair, on a per-run context: `dataclasses.replace(ctx, draft=draft, budget=ToolBudget())`. It keeps the malformed handling and the closing-call salvage. A provider error or an unsalvaged run returns None.
     - Each round runs `first_batch_size` runs concurrently. When `is_decided` is false, it runs the rest of `validation_runs`, then calls `vote`.
     - Every judge run acquires a per-event-loop semaphore of `settings.llm_max_concurrency`, shared by all PLOs. Key it by the running loop (`asyncio.get_running_loop()`); a module-global Semaphore breaks across test event loops.
  2. **Decide whether to stop.** After each round, compute `hard_failures` on the judged statement and `to_fix = repairable(vote.failed)`, or `[]` when the vote is None. Stop when:
     - `hard` and `to_fix` are both empty;
     - `allow_repair` is false;
     - `settings.validation_max_repairs` repairs are spent.
  3. **Repair.**
     - One `_repair(draft, instruction_th, criteria, ctx, metadata) -> draft | None`, through `complete_plo_synthesis`.
     - The instruction comes from `build_vote_repair_instruction_th(hard_hints_th, soft_findings, hint_th)`, a new builder in `prompts/smart_agent.py`, capped at 800 chars:
       - the hard hints come from `CRITERION_FIX_HINTS_TH`;
       - the soft findings are the `to_fix` codes with the representative's notes;
       - the hint is the representative's `repair_hint_th`.
     - **Decision 20:** when the repaired draft has a hard failure the previous one did not, the repair is discarded and the previous draft stays.
     - A failed or discarded repair still counts as a repair. The next round does not re-judge an unchanged statement; it goes straight to the next repair attempt.
  4. **Result.**
     - The statement is the last statement fully judged by a usable vote; when none was usable, the current draft.
     - `soft_findings` are that vote's `failed` codes, each with the representative's note (falling back to its diagnosis).
     - `diagnosis_th` is the representative's diagnosis. `repair_count` is the repairs spent and `turns` is the summed turns.
     - `ran=True` when any round voted. When none did, `code_only_result(...)` with PROVIDER_ERROR / MALFORMED, as today (decision 10).
  5. **Timeout (decision 22).**
     - `asyncio.timeout(validation_timeout_seconds)` wraps the whole loop.
     - On timeout, return the last fully judged statement with its vote, and add the Thai note `"(หมดเวลา — ใช้ผลตรวจรอบล่าสุด)"` to the diagnosis.
     - With no vote at all, return `code_only` DEADLINE as today.
  6. **Logging:** one INFO line per round: `round`, `runs_used`, `failed`, `hard`, `repair`.
- **`validate_and_build(..., allow_repair: bool = True)`** passes the flag through and is otherwise unchanged. The code gate still decides `escalated`.
- **Revalidate route:** passes `allow_repair=plo.designer_edited_at is None`.
- **Kill switch:** `validation_runs=1` gives threshold 1 and a batch of 1, i.e. the single-run agent.

**Steps:**
- [ ] **Step 1: write the failing tests** in `test_smart_voted_loop.py`. Use a fake `complete_validation` that returns scripted Finish steps per run, and a fake `complete_plo_synthesis`.
  - `test_unanimous_pass_stops_after_three_runs` (exactly 3 judge calls)
  - `test_split_runs_all_five`
  - `test_majority_soft_failure_triggers_one_repair_then_rejudge`
  - `test_actor_scope_majority_is_not_repaired_but_flagged`
  - `test_too_few_runs_use_no_soft_verdicts`
  - `test_no_round_voted_is_code_only`
  - `test_repair_adding_hard_failure_is_discarded`
  - `test_max_three_repairs_four_judgings`
  - `test_allow_repair_false_judges_only`
  - `test_timeout_keeps_last_judged_statement`
  - `test_validation_runs_one_single_run`
  - `test_hard_failure_still_escalates_via_validate_and_build`
  - `test_judge_schema_has_no_request_repair`
  - `test_repair_instruction_builder_caps_and_excludes`

  Rewrite the existing `test_smart_agent.py` tests that drive `RequestRepair` to the new structure. Keep every test of tools, malformed handling, closing calls and reasoning bounds. List each rewritten or deleted test, with the reason, in the report.
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: run the full backend verify and confirm PASS.** This includes `dump_prompts.py --check`; regenerate `docs/prompt-inventory.md`.
- [ ] **Step 5: commit** `feat(smart): five voted judge runs per round, one repair per failed round`.

### Task 6 (controller): 6b measurement gate

- [ ] **Step 1: migrate.** Apply the Task 1 migration on `curriculum_phase1` (`alembic -x url=… upgrade head`).
- [ ] **Step 2: run.**
  - Start the copy backend (scratchpad `run_copy_backend.py`, :8011).
  - Run a fresh full copy of `program` through `/plos/run`; the chained review runs. Use phase 4's send-back once, with loop mode irrelevant before 6c.
  - Record usage per slot, wall time, escalations, soft flags and judge runs per PLO from the log.
  - Re-run the stability probe on the result: today's judgments, 5 runs, repairs off.
- [ ] **Step 3: report.**
  - Write `.scratch/reports/2026-11-05-phase6b-smart.md` against the baseline. Was PLO5's out-of-scope or object finding now caught? Cost ×, time ×.
  - If synthesis exceeds 15 min or tokens exceed 6× baseline, rule on `validation_runs` / concurrency and ledger it before 6c.
- [ ] **Step 4: commit the report.**

## Part 6c — review checks, send-back notes, loop

### Task 7: review checks — alignment, verb, voices

**Files:**
- `src/curriculum_agent/models.py`
- `src/curriculum_agent/stages/plo_review_facts.py`
- `src/curriculum_agent/prompts/plo_review.py`
- `src/curriculum_agent/stages/plo_review_agent.py`
- `src/curriculum_agent/stages/plo_review.py` (`accept_review`, `_review` loads evidence, `has_agent_findings`)
- `src/curriculum_agent/stages/plo_review_consensus.py`
- `docs/prompt-inventory.md`
- tests: `tests/unit/test_plo_review*.py` (extend), the prompt-absence test

**Interfaces — produces:**
- **`AlignmentFinding(plo_id: str, reason_th: str, suggestion_th: str = "", agreed_runs: int = 1)`.**
  - `PLOSetReview.alignment: list[AlignmentFinding] = []`. Stored reviews without the field stay readable.
  - `BloomFinding` gains `suggested_verb_th: str | None = None` and `suggestion_th: str = ""`.
- **`need_voices(need: Need, stakeholder_by_evidence: Mapping[str, str]) -> dict[str, int]`** in `plo_review_facts.py`: distinct `source_evidence_ids` per stakeholder type (decision 21). Unknown evidence ids are ignored.
- **Dossier and tools:**
  - `build_dossier(..., stakeholder_by_evidence: Mapping[str, str] = {})`.
  - `ReviewItem.need_statements_th` becomes `cited_needs: tuple[CitedNeed, ...]`, with `CitedNeed(statement_th: str, voices: tuple[tuple[str, int], ...])` sorted by count desc, then by type.
  - The `need_detail` tool returns voices from `need_voices`, not `stakeholder_coverage`.
  - `_review` loads `EvidenceRepository().list_by_program` once to build the map.
- **Prompt:**
  - Each cited Need prints as `- {statement} (ผู้ขอ: ผู้ประกอบการ 3, ศิษย์เก่า 2)`. Thai labels come from a new `STAKEHOLDER_LABEL_TH` dict in `prompts/plo_review.py`, one entry per `StakeholderType`; an unknown type prints raw.
  - The rubric becomes 7 checks:
    - alignment is added: does the PLO answer what its cited Needs ask, given their sentences and voices; return `plo_id`, `reason_th`, `suggestion_th`, entries only for misaligned PLOs;
    - the Bloom check also judges the verb against the work and the degree level, with an optional `suggested_verb_th` and a `suggestion_th`.
  - The prompt still says the reviewer writes no PLO sentence.
- **Agent schema:** `ReviewFinish.alignment: list[AlignmentVerdict]` (loose, like the others). `BloomVerdict` gains `suggested_verb_th: str | None = None` and `suggestion_th: str = ""`.
- **`accept_review`:**
  - Keeps an alignment entry when its PLO is known, its reason is non-empty and it is the first for that PLO.
  - Bloom keeps a verb entry even when the level is unchanged, provided a verb or level is proposed. An empty verb becomes None.
  - Count drops under `alignment`.
- **Consensus:**
  - `_alignment`: count per `plo_id`; text from the representative run, else the first run naming it.
  - `_bloom`: an entry votes when it proposes a level change **or** a verb different from the declared one. `agreed_runs` counts those entries. The level is a plurality (tie → nearest, as now, with None meaning "declared"). `suggested_verb_th` is a plurality among the entries naming a verb (tie → first).
  - `_representative` also scores alignment keys.
- **Prompt-absence test:** extended so the rendered prompt (with voices) still has no skill names, evidence ids, evidence text, `rationale_th` or SMART markers.

**Steps:**
- [ ] **Step 1: write the failing tests.**
  - `test_need_voices_counts_distinct_evidence_per_type` (one employer doc with 3 skills → employer 1)
  - prompt renders voices in Thai
  - alignment accept/drop
  - bloom verb-only accepted
  - consensus alignment threshold
  - bloom verb plurality
  - an old stored review JSON without `alignment` validates
  - `need_detail` returns voices
  - prompt-absence still holds
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: run the full backend verify and confirm PASS** (regenerate the inventory).
- [ ] **Step 5: commit** `feat(review): alignment with Needs and voices, verb fit, voted`.

### Task 8: send-back — full advice notes, alignment, KSEC gap, verb, rounds, dry run

**Files:**
- `src/curriculum_agent/prompts/plo_feedback.py`
- `src/curriculum_agent/stages/plo_feedback.py`
- `src/curriculum_agent/models.py` (`FeedbackAction.round`)
- `src/curriculum_agent/data/orm.py`
- new migration `migrations/versions/b7d2e3f4a516_feedback_round.py` (down `a6c1d2e3f405`)
- `src/curriculum_agent/data/repositories.py`
- `docs/prompt-inventory.md`
- tests: `tests/unit/test_plo_feedback.py`, new `tests/unit/test_plo_feedback_notes.py`

**Interfaces:**
- **Consumes** Task 7's models.
- **`FeedbackAction`** gains `round: int = 0`; ORM column `round` Integer, not null, server default 0.
  - New `kind` values: `alignment`, `ksec_gap`, `loop_end`.
  - New `outcome` values: `planned`, `stopped`. All are plain strings.
- **Note builders** (decision 25), each ≤ 900 chars:
  - `build_redundancy_redraft_note_th(reason_th, suggestion_th, old_statements_th: Sequence[str])`
  - `build_alignment_redraft_note_th(reason_th, suggestion_th, old_statement_th)`
  - `build_bloom_redraft_note_th(suggested: BloomLevel | None, reason_th, *, suggested_verb_th: str | None = None, suggestion_th: str = "", old_statement_th: str = "")`
  - `build_unused_redraft_note_th(reason_th)`
  - `build_ksec_gap_note_th(category: str)`
- **What the notes say:**
  - Old statements appear under the label `ร่างเดิมที่ผู้ตรวจติ:`.
  - Every quoted statement passes through a new `mask_forbidden_words(text) -> str` in `smart_vocabulary.py`, which replaces each forbidden word found by `forbidden_words_in` with `"…"`.
  - Reason and suggestion are each capped at 280 chars.
  - The Bloom level is named in English, as now.
- **`send_back(program_id, review, reviewed_plos, *, round_no: int = 0, dry_run: bool = False, memory: LoopMemory | None = None) -> list[FeedbackAction]`.**
  - **Order:** redundancy → alignment → Bloom/verb → KSEC gap → unused `consider`.
  - **Alignment:** an agreed finding redrafts the PLO from its own Needs with the alignment note. Accept with `_keep_original_unless_better(..., level=None)`.
  - **Bloom:** actionable when agreed and (level differs or verb given). The note names the level and/or verb. Accept requires the suggested level only when it differs from the declared one.
  - **KSEC gap**, for each category in `review.ksec_coverage.missing` (code fact, no vote):
    - Candidate: the highest `demand_score` active Need that no live PLO cites, that is not unwritten (`is_unwritten_need`), whose `exclusion_reason` is not `out_of_scope`, and whose `ksec_categories` contains the category.
    - With no candidate, record `skipped` with `REASON_KSEC_NO_NEED = "ไม่มี Need หมวดนี้ — ต้องเพิ่มที่ขั้น Need"`; this is a comment.
    - Otherwise redraft with `build_ksec_gap_note_th`. The ceiling is enforced by `redraft_from_needs`, and a refusal becomes `skipped` with its reason.
  - **Unused `consider`:** now passes `build_unused_redraft_note_th`.
  - **Merge drift guard (decision 13):** `LoopMemory` holds `merged: set[tuple[str, str]]`, the `(plo_id, statement_th)` of PLOs an applied redundancy wrote in an earlier round. A redundancy naming a live PLO whose pair is in it is `skipped` with `REASON_MERGED_EARLIER = "PLO นี้เพิ่งรวมมาในรอบก่อน"`. `send_back` adds its own applied redundancy results to `memory.merged`.
  - **Dry run:** every check runs as usual, and instead of calling `redraft_from_needs` the action is recorded with `outcome="planned"`, `need_ids` and `instruction_th` (the note). Nothing is written to PLOs, and `memory` is not updated.
  - Every row carries `round=round_no`.
  - **`actionable_count(actions) -> int`:** rows whose outcome is `applied`, `failed` or `planned`, or `skipped` for any reason except `REASON_KSEC_NO_NEED`. Used by the loop.
- **Phase 4 caller:** `fresh_review_with_feedback` keeps calling `send_back(program_id, review, plos)`; the defaults give phase 4 behaviour plus the new kinds.

**Steps:**
- [ ] **Step 1: write the failing tests.**
  - One render test per note builder.
  - `test_notes_never_carry_forbidden_words`: every builder, quoting `"อธิบายและเข้าใจ..."`.
  - Order of kinds.
  - Alignment redraft passes its note.
  - KSEC gap: picks the top eligible Need; skips with the exact text when none; skips the unwritten and out-of-scope ones.
  - Bloom verb-only action.
  - Merge drift skip.
  - Dry run: no `redraft_from_needs` call, rows `planned`.
  - `round` stored.
  - Redundancy note includes both old statements.
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.** The migration adds the column; downgrade drops it.
- [ ] **Step 4: run the full backend verify and confirm PASS** (regenerate the inventory).
- [ ] **Step 5: commit** `feat(feedback): full review advice in every redraft; alignment and KSEC-gap actions`.

### Task 9: the review loop

**Files:**
- new `src/curriculum_agent/stages/plo_review_loop.py`
- `src/curriculum_agent/config.py`
- `src/curriculum_agent/stages/plo_review.py` (`fresh_review_with_feedback` dispatches on mode)
- `src/curriculum_agent/api/routes/plos.py` (`PLOReviewRunResponse.feedback` = all rows of this job)
- test: new `tests/unit/test_plo_review_loop.py`

**Interfaces:**
- **Settings:**
  - `plo_review_loop_mode: Literal["off", "shadow", "apply"] = "shadow"`
  - `plo_review_max_rounds: int = Field(default=5, ge=0)`
  - `plo_review_loop_timeout_seconds: int = 5400`
- **`async def run_review_loop(program_id: str, plos: Sequence[PLO]) -> tuple[PLOSetReview, list[FeedbackAction]]`**, run under the existing `_REVIEW_IN_FLIGHT` guard by its caller:
  - **`off`, or `plo_review_max_rounds == 0`:** exactly today's `fresh_review_with_feedback` path, one review plus phase-4 send-back behind `plo_review_send_back`.
  - **`shadow`:** one review (stored), then `send_back(..., round_no=1, dry_run=True)`, then a `loop_end` row with reason `"โหมดทดลอง — ยังไม่แก้ PLO"`.
  - **`apply`**, for `i` in `1..max_rounds+1`:
    1. Review the live set and store it.
    2. If `i == max_rounds + 1`, stop with "cap".
    3. Run `send_back(round_no=i, memory=mem)`. Skip send-back when the review is `code_only` or `plo_review_send_back` is false, then stop with "no agent review".
    4. If `actionable_count == 0`, stop with "pass".
    5. If no row is `applied`, stop with "no change".
    6. Otherwise continue.
  - **Loop budget:** the rounds run under `asyncio.timeout(plo_review_loop_timeout_seconds)`. On timeout, the round in progress is abandoned (its rows are already written); one final review of the stored set runs and is stored, with no send-back; stop with "timeout".
  - **`loop_end` row:** each stop writes one row (`kind="loop_end"`, `outcome="stopped"`, `round=i`) with a reason from a fixed map:

    | stop | `outcome_reason_th` |
    |---|---|
    | pass | "ผ่านการตรวจ — ไม่มีข้อที่ต้องแก้" |
    | no change | "รอบนี้แก้อะไรไม่ได้ — หยุด" |
    | cap | "ส่งกลับครบ {max} รอบแล้ว" |
    | timeout | "หมดเวลา {s} วินาที — ตรวจชุดสุดท้ายแล้ว" |
    | no agent review | "ไม่มีผลตรวจจาก agent — ไม่ส่งกลับ" |

  - **Never raises past the caller:** an exception inside a round ends the loop with a final stored review where possible, plus `loop_end` "เกิดข้อผิดพลาด — หยุด".
  - **Returns:** the last stored review and every row written in this call.
- **Wiring:**
  - `fresh_review_with_feedback` calls `run_review_loop` (all modes), so both the graph node and `POST /plos/review/run` run the loop.
  - `review_plo_set`'s reuse of a current stored review is unchanged.

**Steps:**
- [ ] **Step 1: write the failing tests.** Fake `_review` returns scripted reviews; fake `send_back` returns scripted rows.
  - `test_off_mode_is_phase4`
  - `test_max_rounds_zero_is_phase4`
  - `test_shadow_one_review_planned_rows_no_write`
  - `test_apply_pass_on_first_review`
  - `test_loop_stops_when_round_applies_nothing`
  - `test_cap_ends_with_review` (5 send-backs, 6 reviews)
  - `test_timeout_runs_final_review`
  - `test_exception_in_round_does_not_raise`
  - `test_code_only_review_stops`
  - every stop writes exactly one `loop_end` row with its round
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: run the full backend verify and confirm PASS.**
- [ ] **Step 5: commit** `feat(review): review → send-back loop with shadow mode and stop reasons`.

### Task 10: UI — rounds, alignment, verb, planned rows, comments

**Files:**
- `frontend/src/types/ploReview.ts`
- `frontend/src/pages/components/FeedbackTrail.tsx`
- `frontend/src/pages/PloReview.tsx`
- `frontend/src/mock/handlers.ts`

- [ ] **Step 1: types.** `AlignmentFinding`; `BloomFinding.suggested_verb_th` / `suggestion_th`; `FeedbackAction.round`; the new kinds and outcomes.
- [ ] **Step 2: review page findings.**
  - New section "ความสอดคล้องกับ Need": agreed and unagreed, styled like redundancy.
  - Bloom rows show "แนะนำกริยา: X" when present.
- [ ] **Step 3: trail.**
  - Group the newest job's rows by `round` ("รอบที่ n"). `planned` shows "จะส่งกลับ (โหมดทดลอง)".
  - The `loop_end` row shows as the stop line ("หยุดเพราะ: …").
  - Kind labels: ความสอดคล้อง, หมวด KSEC ที่ขาด.
- [ ] **Step 4: open comments.** A box "ข้อสังเกตที่ยังค้าง" lists the last review's agreed findings that have no `applied` row in the same job. `skipped` rows with their reasons count as comments. This is what the designer reads before approving.
- [ ] **Step 5: mocks.** The mock review run produces a 2-round apply loop (one applied alignment, then a pass) and a `loop_end` row.
- [ ] **Step 6: run `npm run build` and `npm run lint`.**
- [ ] **Step 7: commit** `feat(ui): review loop rounds, alignment and open comments`.

### Task 11: docs

**Files:**
- `CLAUDE.md`
- `.claude/rules/plo-review.md`
- `.claude/rules/smart-gate.md`
- `.claude/rules/api-data.md`
- `.claude/skills/curriculum-design-agent/references/data-schemas.md`

- [ ] **Step 1: edit, matching each file's tone.**
  - **CLAUDE.md, immutable rule 5:** 5 voted judge runs, early stop, 3/5 majority, at most 3 repairs (4 judgings). Soft criteria drive repair but never escalate. A_actor and A_scope are never repaired. A repair that adds a hard failure is discarded. The designer's decision is dated 2026-11-04.
  - **CLAUDE.md, rule 7:** checkpoint after the review loop; the report last and stored; the loop bounds and modes.
  - **CLAUDE.md, stack line:** the new settings.
  - **`plo-review.md`:** alignment and voices (the information-bias rule stands), the verb vote, KSEC gap, the loop, stop reasons, shadow mode, the merge drift guard, `designer_edited_at` skip, notes carrying the old statement masked.
  - **`smart-gate.md`:** judge/vote/repair split; `repair_hint_th`; `allow_repair`.
  - **`api-data.md`:**
    - `plo_reports` life;
    - `GET /plos/report`;
    - `/plos/run` chains the review;
    - the resume reload in `review_plos`;
    - `designer_edited_at` set by PUT and cleared by nothing;
    - stage order.
  - **`data-schemas.md`:** `PLOReport`, `AlignmentFinding`, the new fields.
- [ ] **Step 2: run `dump_prompts.py --check`.**
- [ ] **Step 3: commit** `docs: phase 6 — voted SMART loop, review loop, report last`.

### Task 12 (controller): 6c gate — shadow run, apply run, comparison

- [ ] **Step 1: migrate.** Apply the Task 8 migration on `curriculum_phase1`.
- [ ] **Step 2: shadow run.** Copy backend, fresh full copy of `program`, `/plos/run` (default shadow): record the planned rows.
- [ ] **Step 3: apply run.** Restart the copy backend with `PLO_REVIEW_LOOP_MODE=apply` (process env for that run only, not `.env`), on a fresh full copy.
  - Record the rounds, the stop reason, PLO count before and after, applied/skipped per kind, usage per slot and wall time.
- [ ] **Step 4: report.**
  - Write `.scratch/reports/2026-11-05-phase6c-loop.md`: the before/after set (statements), the trail, cost and time against the baseline and 6b.
  - Recommend whether to flip the default to `apply`. **Do not flip it; that is the designer's call.**
- [ ] **Step 5: commit the report.**
