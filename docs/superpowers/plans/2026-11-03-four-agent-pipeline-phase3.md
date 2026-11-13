# Four-agent pipeline phase 3 (PLO page) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep superseded PLOs as read-only history, cap the manual merge at 5 Needs, and give the PLO page an unused-Need picker with a supersede preview, attach-a-Need on each card, a per-card loading state and a superseded section.

**Architecture:** One new table `superseded_plos` written inside `PLORepository.replace`'s transaction; one new GET route; `from-needs` gains an upper bound. "Attach" is the existing `from-needs` call with the card's Needs plus one. The UI work is in `PloSynthesis.tsx`, split into components under `pages/components/`.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, pytest; React + TypeScript + Vite, mock handlers in `frontend/src/mock/handlers.ts`.

**Spec:** `docs/superpowers/specs/2026-11-03-four-agent-pipeline-phase3-design.md`

## Global Constraints

- Branch `feat/four-agent-pipeline`. Run `git branch --show-current` before every commit; stage by explicit path; never `git add -A`; never commit `.env`, `.env.demo`, `dist/`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never run `alembic` against any DB. Migrations are written and unit-tested only; the controller applies them.
- Never print DSNs, passwords or API keys.
- `from __future__ import annotations`, type hints everywhere, `loguru` only, repository pattern for DB access, Thai for user-facing strings, English for code/comments/logs.
- DB timestamps are naive UTC (`datetime.now(UTC).replace(tzinfo=None)`), JSON output carries `+00:00` like `JobInfo` does.
- Frontend: no Tailwind palette colours — use the component classes and the three inks in `index.css` (stamp/mandate/marker); loading marks use the existing `animate-run-sweep`, no spinner.
- Verify with: `uv run pytest -q`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`; frontend `npm run build` and `npm run lint` in `frontend/`.

## Review Focus

- A merge whose LLM call fails (502) must write **no** history rows — history lands only with the replace.
- A synthesis re-run (`delete_by_program`) and a program delete must leave no orphan `superseded_plos` rows.
- A full program copy's history snapshots must carry the **new** `program_id` and remapped Need/evidence ids; an `evidence_only` copy carries none.
- Ticking a 6th Need in the UI must be impossible, and the server must still refuse 6 ids if a client sends them.
- Attach on a card whose PLO already cites 5 Needs, or when no unused Need exists, must be disabled, not fail at the server.

---

### Task 1: `superseded_plos` storage

**Files:**
- Modify: `src/curriculum_agent/models.py` (add `SupersededPLO` next to `PLO`)
- Modify: `src/curriculum_agent/data/orm.py` (add `SupersededPLOTable`)
- Create: `migrations/versions/c4e2a7f9d813_superseded_plos.py` (down_revision `b8d4f6a1c935`)
- Modify: `src/curriculum_agent/data/repositories.py` (`PLORepository.replace`, `PLORepository.delete_by_program`, `ProgramRepository.delete_cascade`, new `SupersededPLORepository`)
- Modify: `src/curriculum_agent/data/program_copy.py` (`ProgramRows`, `load_rows`, `build_copy`, `copy_program`)
- Test: `tests/unit/test_superseded_plos.py` (new); extend `tests/unit/test_program_copy_build.py`

**Interfaces:**
- Produces: `SupersededPLO(id: str, program_id: str, superseded_by: str, superseded_at: datetime, plo: PLO)`; `PLORepository.replace(program_id, remove_plo_ids, add) -> int` (signature unchanged); `SupersededPLORepository().list_by_program(program_id: str) -> list[SupersededPLO]` newest first.

Table `superseded_plos`: `id` String PK, `program_id` String (FK to `programs.program_id` if `plos` has one — mirror `PLOTable`), `plo_id` String, `snapshot` JSONB, `superseded_by` String, `superseded_at` DateTime; index on `program_id`.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_superseded_plos.py`, in the style of the existing repository tests (read `tests/unit/test_plo_repository.py` first and use the same DB fixture/mocking approach):
  - `test_replace_snapshots_removed_plos`: two stored PLOs PLO1, PLO2; `replace(pid, ["PLO1","PLO2"], [new PLO1])` → `list_by_program` returns 2 rows, each `superseded_by == "PLO1"`, `plo.plo_id` in {PLO1, PLO2}, `plo.statement_th` equal to the stored ones.
  - `test_replace_with_nothing_removed_writes_no_history`.
  - `test_delete_by_program_clears_history` and `test_delete_cascade_clears_history`.
  - `test_list_skips_snapshot_that_no_longer_validates`: insert a row whose snapshot fails `PLO.model_validate` → list returns the valid rows only, no raise.
  - `test_list_newest_first`.
  - In `test_program_copy_build.py`: full copy clones history rows with fresh `id`, the new `program_id` both on the row and inside the snapshot, and remapped `source_need_ids`/`source_evidence_ids`; `evidence_only` copy has none.
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_superseded_plos.py tests/unit/test_program_copy_build.py -q` → FAIL.
- [ ] **Step 3:** Implement. In `replace`, before the delete, select the rows being removed and add one `SupersededPLOTable` per row (snapshot = the row as a `PLO` json dump, `superseded_by` = `add[0].plo_id`, or skip history when `add` is empty) — same session, same commit. `delete_by_program` and `delete_cascade` delete `superseded_plos` for the program in their transaction. Copy: add `superseded: list[SupersededPLOTable]` to `ProgramRows`, load it, clone in full mode with `id=_uuid4()`, `program_id=new_id`, and the snapshot's `program_id` set to `new_id` after `remap_ids`; empty in `evidence_only`; add it to the insert loop after `plos`. Migration creates/drops the table.
- [ ] **Step 4:** Run the two test files → PASS; then `uv run pytest -q`, ruff, mypy.
- [ ] **Step 5:** Commit `feat(data): keep superseded PLOs in superseded_plos`.

### Task 2: routes — cap the manual merge, list superseded

**Files:**
- Modify: `src/curriculum_agent/api/routes/plos.py`
- Test: `tests/unit/test_api_plos.py` (or the file that already tests `from-needs` — find it with grep `from-needs` in `tests/`)

**Interfaces:**
- Consumes: `SupersededPLORepository.list_by_program`, `SupersededPLO`, `MAX_GROUP_SIZE` from `stages/need_dedup.py`.
- Produces: `GET /programs/{program_id}/plos/superseded` → `list[SupersededPLO]`; `from-needs` 422 detail `"เลือก Need 2-5 ข้อเพื่อรวมเป็น PLO"` when `len(need_ids) > MAX_GROUP_SIZE`.

- [ ] **Step 1: Failing tests:** `test_from_needs_refuses_six_needs` (6 ids → 422 with that detail, no LLM call made, nothing replaced); `test_from_needs_accepts_five`; `test_list_superseded_404_unknown_program`; `test_list_superseded_returns_repository_rows`. Declare `/superseded` before any `/{plo_id}` route.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. The bound check goes at the top of `create_plo_from_needs`, before the program lookup's LLM path and before `sync_writer`; import `MAX_GROUP_SIZE`, do not restate 5. Keep `min_length=2` on the model.
- [ ] **Step 4:** Run → PASS; full suite, ruff, mypy.
- [ ] **Step 5:** Commit `feat(api): cap from-needs at 5 Needs; list superseded PLOs`.

### Task 3: frontend data, mocks, superseded section, card loading state

**Files:**
- Modify: `frontend/src/types/*` (add `SupersededPLO` type mirroring the model)
- Modify: `frontend/src/mock/handlers.ts` (GET `/plos/superseded`; `from-needs` mock: 422 above 5 with the same Thai text, and on success move the replaced PLOs into the mock's superseded store with `superseded_by`/`superseded_at`, newest first)
- Create: `frontend/src/pages/components/SupersededPlos.tsx`
- Modify: `frontend/src/pages/PloSynthesis.tsx`

**Interfaces:**
- Produces: `PloSynthesis` loads `superseded` alongside `plos` (and on every reload path that reloads PLOs); `PLOCard` takes a `pending?: { label: string; since: number }` prop that dims the card, disables its actions and shows the sweep line with elapsed seconds.

- [ ] **Step 1:** Add the type, the mock routes, and `SupersededPlos` (collapsed `<details>` "PLO ที่ถูกแทนที่ (n)", hidden when n = 0; each item: old `plo_id`, statement, cited Need ids, "แทนที่โดย {superseded_by}", local time of `superseded_at`; muted, no actions).
- [ ] **Step 2:** Card loading state: `pending = {label: "กำลังตรวจ SMART ใหม่"}` for the card whose `plo_id` is the running `plo_revalidate` job's; during a merge/attach in flight, `{label: "กำลังร่าง PLO ใหม่แทนข้อนี้"}` for every card the request will replace (Task 4 provides the set; in this task wire it from the current merge selection using the same rule: cards whose `source_need_ids` intersect the selected ids). Elapsed seconds tick once a second while pending.
- [ ] **Step 3:** `npm run build`, `npm run lint` (0 errors). Check in the mock server (`npm run dev:mock`) that a revalidate dims only that card and a merge moves the replaced card into the superseded section.
- [ ] **Step 4:** Commit `feat(ui): superseded PLO section and per-card loading state`.

### Task 4: frontend — Need picker with preview, attach on card

**Files:**
- Create: `frontend/src/pages/components/MergeNeedPicker.tsx` (replaces the inline merge panel in `PloSynthesis.tsx`)
- Modify: `frontend/src/pages/PloSynthesis.tsx`, `PLOCard` (attach control)
- Create (if a shared constant file exists, put it there): `MAX_MERGE_NEEDS = 5` in `frontend/src/constants/`

**Interfaces:**
- Consumes: Task 3's `pending` prop and superseded reload.
- Produces: one helper `plosCiting(plos, needIds): PLO[]` (every PLO whose `source_need_ids` intersects `needIds` — the server's `plos_citing` rule) used by both the preview and the card pending state.

- [ ] **Step 1:** `MergeNeedPicker`: active Needs split into "ยังไม่มี PLO" (highlighted with a component-class chip, listed first, by demand) and "อยู่ใน PLOx" (labelled with the citing PLO ids). Checkboxes disabled once 5 are ticked, with the hint "รวมได้ไม่เกิน 5 Need". Under the list while ≥1 ticked: "จะแทนที่: PLO3, PLO5" (or "ไม่แทนที่ PLO เดิม — เพิ่มเป็นข้อใหม่") and "Need ที่จะไม่มี PLO หลังรวม: …" (Needs cited only by replaced PLOs and not selected). Keep the existing note field and submit button and the existing error/409 handling.
- [ ] **Step 2:** Attach on `PLOCard`: a "เพิ่ม Need" control listing unused Needs; disabled with a title when the PLO cites 5 Needs ("PLO นี้มี Need ครบ 5 ข้อแล้ว") or no unused Need exists. Confirm calls the same submit path as the picker with `need_ids = [...plo.source_need_ids, chosen]`; the card shows the Task 3 pending state; on success reload PLOs, Needs and superseded.
- [ ] **Step 3:** Mock check: tick 6 impossible; preview lists the right PLOs; attach on a 1-Need card replaces only that card and it lands in the superseded section. `npm run build`, `npm run lint`.
- [ ] **Step 4:** Commit `feat(ui): unused-Need picker with supersede preview; attach a Need to a PLO`.

### Task 5: docs

**Files:** `.claude/rules/api-data.md`, `CLAUDE.md` (rule 6's phase-1 note on `from-needs`), `.claude/skills/curriculum-design-agent/references/data-schemas.md`, `docs/prompt-inventory.md` only if `scripts/dump_prompts.py --check` fails.

- [ ] **Step 1:** api-data.md: a bullet on `superseded_plos` (written by `replace` in the same transaction, cleared with the set, copied in full mode only, list skips invalid snapshots), the 2-5 bound on `from-needs`, attach = `from-needs`. CLAUDE.md rule 6: replace "The manual `POST /plos/from-needs` merge route is unchanged in phase 1" with the phase-3 behaviour in one sentence (2-5 Needs, replaced PLOs kept read-only in `superseded_plos`). data-schemas.md: `SupersededPLO`.
- [ ] **Step 2:** `uv run python scripts/dump_prompts.py --check`.
- [ ] **Step 3:** Commit `docs: phase 3 PLO page — superseded history, 2-5 merge bound`.
