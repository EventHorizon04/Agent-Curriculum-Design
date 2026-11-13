# Four-agent pipeline phase 4 (Agent 4 send-back) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a fresh agent review, apply its agreed redundancy, Bloom and "consider" findings through the same redraft path the designer's merge uses, record every considered finding in a trail table, and show the trail on the review and PLO pages.

**Architecture:** The body of `_merge_needs` (api/routes/plos.py) moves to `stages/plo_redraft.py` as one function used by the route and by a new `stages/plo_feedback.py`. `fresh_review` calls `plo_feedback.send_back` after storing the review. Trail rows live in `plo_feedback_actions`; `superseded_plos` gains `cause`.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, pytest; React + TypeScript + Vite with mock handlers.

**Spec:** `docs/superpowers/specs/2026-11-03-four-agent-pipeline-phase4-design.md`

## Global Constraints

- Branch `feat/four-agent-pipeline`. `git branch --show-current` before every commit; stage by explicit path; never `git add -A`; never commit `.env`, `.env.demo`, `dist/`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never run `alembic` against any DB and never connect to a database; the controller applies migrations. Never print DSNs, passwords or API keys.
- `from __future__ import annotations`, type hints, `loguru`, repository pattern, prompts only in `src/curriculum_agent/prompts/` (one file per prompt, typed builder), Thai for user-facing strings, English for code/comments/logs.
- DB timestamps naive UTC via `datetime.now(UTC).replace(tzinfo=None)`; JSON output carries `+00:00` (`field_serializer(..., when_used="json")`, as `JobInfo`/`SupersededPLO`).
- Frontend: no Tailwind palette colours; component classes and inks from `index.css`; `animate-run-sweep`, no spinner.
- Verify: `uv run pytest -q`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src`, `uv run python scripts/dump_prompts.py --check`; frontend `npm run build`, `npm run lint` (0 errors; 1 known warning).

## Review Focus

- A send-back action that would exceed `MAX_CORE_PLOS`, drop below `MIN_CORE_AFTER_MERGE`, exceed `MAX_GROUP_SIZE` Needs, or use a merged-away/excluded/unwritten Need is recorded `skipped` with the same Thai reason the route gives, and changes nothing.
- A draft that fails (synthesis returns None or raises) is recorded `failed`; the review job still succeeds and the stored review is unchanged.
- A finding below the agreement threshold, a `code_only` review, a reused stored review, and `plo_review_send_back=False` all produce zero actions and zero trail rows.
- Two findings naming the same PLO in one round: the second is `skipped` ("ถูกแทนที่ไปแล้วในรอบนี้"), never applied to a PLO that no longer exists.
- `POST /plos/from-needs` behaves byte-for-byte as before (status codes, Thai details, 502 with nothing changed); its existing tests pass unmodified.

---

### Task 1: storage — `plo_feedback_actions`, `superseded_plos.cause`

**Files:** `src/curriculum_agent/models.py` (`FeedbackAction`), `src/curriculum_agent/data/orm.py`, new migration `migrations/versions/d7b3e5c1a420_plo_feedback_actions.py` (down `c4e2a7f9d813`), `src/curriculum_agent/data/repositories.py`, `src/curriculum_agent/data/program_copy.py`; tests `tests/unit/test_plo_feedback_storage.py`, extend `tests/unit/test_superseded_plos.py`, `tests/unit/test_program_copy_build.py`.

**Interfaces — produces:**
- `FeedbackAction` fields exactly as spec decision 3 (`kind`/`outcome` plain `str`, lists default empty, `result_*` nullable); `created_at` and `review_created_at` serialise with `+00:00` in JSON.
- `SupersededPLO.cause: str | None = None`; ORM column `cause` String nullable.
- `PLORepository.replace(program_id, remove_plo_ids, add, *, cause: str = "designer") -> int` writes `cause` on each history row.
- `PLOFeedbackRepository().add(actions: list[FeedbackAction]) -> None`; `.list_by_program(program_id) -> list[FeedbackAction]` ordered `created_at` desc then `id`.
- `delete_by_program` and `delete_cascade` clear `plo_feedback_actions`; full copy clones them (fresh `id`, new `program_id`, ids remapped by `remap_ids` — `plo_ids`, `need_ids`); `evidence_only` none.

- [ ] Step 1: failing tests — `test_replace_records_cause_review`, `test_replace_default_cause_designer`, `test_feedback_add_and_list_newest_first`, `test_delete_by_program_clears_feedback`, `test_delete_cascade_clears_feedback`, copy full/evidence_only cases; follow the mocking approach of `tests/unit/test_superseded_plos.py`.
- [ ] Step 2: run → FAIL. Step 3: implement (migration adds the column and creates the table with an index on `program_id`; downgrade reverses). Step 4: full verify → PASS. Step 5: commit `feat(data): plo_feedback_actions trail and superseded cause`.

### Task 2: move the merge core out of the route

**Files:** new `src/curriculum_agent/stages/plo_redraft.py`; `src/curriculum_agent/api/routes/plos.py`; test `tests/unit/test_plo_redraft.py`.

**Interfaces — produces:**
```python
class RedraftRefused(Exception):  # .status: int (404 or 422), .detail_th: str
class RedraftFailed(Exception):   # the draft came back empty; nothing was written
async def redraft_from_needs(
    program: ProgramMetadata, program_id: str, need_ids: list[str],
    *, note_th: str | None, cause: str,
) -> tuple[PLO, list[str]]:  # (new PLO, plo_ids it replaced)
```
Everything `_merge_needs` does today moves here unchanged — the same checks in the same order with the same Thai texts, `plos_citing`, bounds, `next_plo_id`, siblings, `synthesize_from_needs`, `PLORepository.replace(..., cause=cause)`, the logs. It accepts 1+ Needs (no lower bound of its own); the 2-5 bound stays in the route. It takes no lock. The route keeps its size check, 404, `sync_writer`, and maps `RedraftRefused` → `HTTPException(e.status, e.detail_th)`, `RedraftFailed` → 502 "สร้าง PLO ไม่สำเร็จ กรุณาลองใหม่", passing `cause="designer"`.

- [ ] Step 1: tests in `test_plo_redraft.py` for: one-Need redraft replaces exactly the PLO citing it and returns its id; refusal raises `RedraftRefused` with status 422 and nothing replaced; empty draft raises `RedraftFailed` and `replace` is not called; `cause` reaches `replace`. All existing `from-needs` tests must pass **unmodified** (only patch targets may move if a test patches `plos._merge_needs` internals — if any must change, say which and why in the report).
- [ ] Step 2-4: run → FAIL → implement → full verify PASS. Step 5: commit `refactor(plos): move the from-needs core into stages/plo_redraft`.

### Task 3: send-back stage, switch, route

**Files:** new `src/curriculum_agent/stages/plo_feedback.py`, new `src/curriculum_agent/prompts/plo_feedback.py` (`build_bloom_redraft_note_th(suggested: BloomLevel, reason_th: str) -> str`), `src/curriculum_agent/config.py` (`plo_review_send_back: bool = True`), `src/curriculum_agent/stages/plo_review.py` (`fresh_review` calls `send_back` after `upsert`, never raising out of it), `src/curriculum_agent/api/routes/plos.py` (`PLOReviewResponse.feedback`, `GET /feedback`), `scripts/dump_prompts.py` if it enumerates builders; tests `tests/unit/test_plo_feedback.py`, `tests/unit/test_api_plos.py`.

**Interfaces:**
- Consumes `redraft_from_needs`, `RedraftRefused`, `RedraftFailed` (Task 2); `PLOFeedbackRepository`, `FeedbackAction` (Task 1).
- Produces `async def send_back(program_id: str, review: PLOSetReview) -> list[FeedbackAction]` — returns `[]` without any read when the switch is off or `review.reviewed_by != "agent"`; otherwise considers agreed findings in the spec's order, runs actions sequentially, writes all trail rows with one `PLOFeedbackRepository.add`, returns them. Any unexpected exception inside one action → that action `failed` with a Thai reason; an exception outside the actions is logged and returns what was recorded. `fresh_review` returns the review as before; the job's `PLOReviewResponse` gains `feedback` (the list for this round).
- Outcome reasons (Thai, exact): refused → the `RedraftRefused.detail_th`; failed draft → "ร่าง PLO ไม่สำเร็จ"; PLO already replaced this round → "PLO นี้ถูกแทนที่ไปแล้วในรอบนี้"; PLO no longer exists → "ไม่พบ PLO นี้ในชุดปัจจุบัน"; unused Need unwritten or out of scope → "Need นี้ยังไม่มีประโยคหรืออยู่นอกขอบเขตหลักสูตร".
- `GET /programs/{id}/plos/feedback` → `list[FeedbackAction]`, 404 unknown program; declared before any `/{plo_id}` route.

- [ ] Step 1: failing tests (mock `redraft_from_needs`, repositories): order redundancy → bloom → unused; below-threshold findings ignored; `code_only` / switch off → `[]` and no repository call; second finding on a replaced PLO → skipped with the exact text; refusal and failure recorded with exact texts; bloom note built by the prompt builder and passed as `note_th`; `result_bloom_level` recorded; `fresh_review` returns its review even when `send_back` raises; job response carries `feedback`; GET route 200/404.
- [ ] Step 2-4: FAIL → implement → full verify (incl. `dump_prompts.py --check`; regenerate `docs/prompt-inventory.md` with the script if it now lists the new builder). Step 5: commit `feat(review): send agreed findings back as redrafts, with a trail`.

### Task 4: UI — trail on the review page, chip on the PLO page, mocks

**Files:** `frontend/src/types/ploReview.ts` (`FeedbackAction`), new `frontend/src/pages/components/FeedbackTrail.tsx`, `frontend/src/pages/PloReview.tsx`, `frontend/src/pages/PloSynthesis.tsx`, `frontend/src/pages/components/SupersededPlos.tsx`, `frontend/src/mock/handlers.ts`.

- [ ] Step 1: Review page loads `GET /plos/feedback` with the review (and after a review job finishes). `FeedbackTrail` shows the latest round (`review_created_at` of the newest row) as "ส่งกลับไปแก้แล้ว": per row a kind label (ซ้ำซ้อน / ระดับ Bloom / Need ที่ยังไม่ได้ใช้), the reviewer's reason, then for `applied` the before statement(s) (from the superseded list, matched by `superseded_by == result_plo_id` and `cause == "review"` within the round) and the after statement with its PLO id and, for Bloom, "ขอระดับ X · ได้ระดับ Y"; for `skipped`/`failed` the label "ข้าม"/"ไม่สำเร็จ" and the reason. Older rounds in a collapsed `<details>`. Hidden when there are no rows.
- [ ] Step 2: PLO page: chip "แก้ตามผลตรวจ" on a card whose `plo_id` and `statement_th` equal an `applied` row's `result_plo_id` and `result_statement_th`, linking to the review page route. `SupersededPlos`: `cause === "review"` reads "แทนที่ตามผลตรวจโดย {id}" (keeping the "ฉบับใหม่" rule from phase 3).
- [ ] Step 3: Mocks: GET `/plos/feedback` (404 unknown program); the mock review run appends a believable round (one applied redundancy using the mock's from-needs replace logic with `cause: 'review'`, one skipped) so the page has something to show; the mock copy/re-synthesis/delete paths handle the new store like `superseded`.
- [ ] Step 4: `npm run build`, `npm run lint`. Step 5: commit `feat(ui): send-back trail on the review page; chip and cause on the PLO page`.

### Task 5: docs

**Files:** `CLAUDE.md` (rule 7: the post-PLO tail now changes PLOs automatically through send-back, by the designer's decision of 2026-10-26, with the trail and superseded history; the "QA failure never fails the session" sentence extends to send-back), `.claude/rules/plo-review.md` (replace "nothing reads it back" with the send-back rules: agreed findings only, one round, order, same redraft path, KSEC advisory, trail), `.claude/rules/api-data.md` (`plo_redraft` core shared by route and send-back; it takes no lock — callers hold the program busy; trail table life), `.claude/skills/curriculum-design-agent/references/data-schemas.md` (`FeedbackAction`, `SupersededPLO.cause`).

- [ ] Step 1: edit, matching each file's tone. Step 2: `dump_prompts.py --check`. Step 3: commit `docs: phase 4 — review send-back and its trail`.
