# Four-agent pipeline phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the designer merge and exclude Needs at the Need checkpoint. Let them edit evidence until skill extraction runs, after which evidence is locked. Add an "evidence only" program copy as the way out of the lock.

**Architecture:**
- **Exclusion** is a nullable `excluded_at` column, filtered in `NeedRepository.list_active_by_program`, the one read every downstream stage already uses.
- **Manual merge** reuses `need_merge._write_merged` behind a new synchronous route under `sync_writer`, and records `merged_by`.
- **The evidence lock** is one helper, checked by every evidence-mutating route.
- **The copy** gets a `mode` switch in `build_copy`.

**Tech Stack:**
- Backend: FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, Instructor, pytest.
- Frontend: React + TypeScript (Vite), axios client `frontend/src/api/client`.

**Spec:** `docs/superpowers/specs/2026-11-03-four-agent-pipeline-phase2-design.md`. Read it before each task; it is the authority.

## Global Constraints

- **Branch.** `feat/four-agent-pipeline` only. Run `git branch --show-current` before every commit. Stage by explicit path. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Code conventions.**
  - `from __future__ import annotations`.
  - Type hints on every signature.
  - `loguru` for logging, not stdlib `logging`.
  - Repository pattern: no SQL in routes.
  - Pydantic v2 at every boundary.
- **Language.** Thai for designer-facing strings (HTTP `detail`, UI). English for code, comments and logs.
- **Do not touch:**
  - `CLAUDE.md`
  - `.claude/`
  - `.env*`

  Task 8 is the only task that edits `CLAUDE.md` and `.claude/rules`.
- **No real LLM calls, DB or servers** in tests. Follow the fakes and conftest in `tests/`, e.g. `tests/support/jobs.py`.
- **Verify before every commit:**
  - `uv run pytest tests/unit -q`
  - `uv run ruff check src tests`
  - `uv run ruff format --check src tests`
  - `uv run mypy src`
  - `uv run python scripts/dump_prompts.py --check`
  - Frontend tasks also run `npm --prefix frontend run build` and `npm --prefix frontend run lint`.
- **New Need fields need defaults** (`excluded_at: datetime | None = None`, `merged_by: Literal["agent", "designer"] | None = None`), because Needs also arrive as checkpoint dicts.
- **Frontend visual identity.**
  - Use the component classes in `frontend/src/index.css` (the stamp, mandate and marker inks). No Tailwind palette colours.
  - Reuse the existing two-step confirm pattern (`StakeholderNeeds.tsx`, `confirmingDeleteId`) and the busy and error handling of split (`NeedAnalysis.tsx`).
- **Mock mode.** If `frontend/src/mock` serves the routes a page calls, add mock handlers for each new route, so `npm run dev:mock` keeps working.

## Review Focus

1. **Evidence edited while the first extraction job is running.** No skills are stored yet, so the lock says unlocked. Evidence mutations must also answer 409 while the program is busy (`program_busy`). Test in Task 4.
2. **A double-clicked merge, or two tabs.** The second request runs while the first is still registered as a writer, and must get 409, not a second merged Need. Test in Task 3.
3. **Duplicate ids in a merge selection** (`["N1", "N1"]`). They must give 422 ("เลือก Need ซ้ำ"), not a one-member "merge". Test in Task 3.
4. **Agent 2 re-run after manual edits.** The rewritten Needs carry `excluded_at=None` and `merged_by` set only on Agent 2's own merges. No stale exclusion survives under a new id. Test in Task 1.
5. **`POST /plos/from-needs` given an excluded Need.** It must give 422, since it reads all Needs, not active ones. Test in Task 2.

---

### Task 1: Need fields, migration, repository, and Agent 2 `merged_by`

**Files:**
- Modify:
  - `src/curriculum_agent/models.py` (`Need`, around line 291)
  - `src/curriculum_agent/data/orm.py` (`NeedTable`, around line 89)
  - `src/curriculum_agent/data/repositories.py` (`NeedRepository`, around line 361)
  - `src/curriculum_agent/stages/need_merge.py` (`_write_merged` around line 183, `merge_duplicates` around lines 262-314)
- Create: `migrations/versions/<rev>_need_exclude_and_merged_by.py`, with `down_revision` = the current head. Run `uv run alembic heads`; it was `a7c3e91d5b24`.
- Test:
  - `tests/unit/test_need_exclude.py` (new)
  - `tests/unit/test_need_merge.py` (extend)
  - `tests/unit/test_need_schema_v2.py` (extend)

**Interfaces:**
- **Produces** on `Need`:
  - `excluded_at: datetime | None = None`
  - `merged_by: Literal["agent", "designer"] | None = None`
- **Produces** `need_merge.mark_merged(needs: list[Need], merged: list[Need]) -> list[Need]`. It returns the originals in their order, with `merged_into` set for each id that appears in some merged Need's `merged_from`. Other Needs pass through unchanged. `merge_duplicates` uses it in place of its inline `parent_of` block.
- **Produces** `need_merge._write_merged(..., merged_by: Literal["agent", "designer"] = "agent")`. The returned Need carries it.
- **Produces** on `NeedRepository`:
  - `async set_excluded(program_id: str, need_id: str, excluded_at: datetime | None) -> Need`, which raises `KeyError` for an unknown id or the wrong program;
  - `async write_merge(program_id: str, originals: list[Need], merged: Need) -> Need`. In one session it sets each original's `merged_into = merged.need_id` and inserts `merged`, then commits.
- **Changes** `list_active_by_program`: the filter becomes `merged_into IS NULL AND excluded_at IS NULL`.

Steps:
- [ ] **Step 1: Write failing tests.**
  - `test_need_accepts_dict_without_new_fields`: a `Need.model_validate` of a dict without either key gives `excluded_at is None` and `merged_by is None`.
  - `test_list_active_skips_excluded`: use the repository test style already used in `test_active_needs_downstream.py` or `test_need_split.py`.
  - `test_mark_merged_sets_parent`: two originals and one merged Need with `merged_from` = both. Each original gets `merged_into` = the merged id; a third Need is untouched.
  - `test_merge_duplicates_sets_merged_by_agent`.
  - `test_need_combination_rewrite_clears_manual_state` (Review Focus 4): after need_combination's `delete_by_program` plus `bulk_insert`, no Need has `excluded_at` set and none has `merged_by == "designer"`.
- [ ] **Step 2:** Run `uv run pytest tests/unit/test_need_exclude.py tests/unit/test_need_merge.py tests/unit/test_need_schema_v2.py -q`. Expect FAIL.
- [ ] **Step 3: Implement.**
  - Add the model fields and ORM columns:
    - `excluded_at`: `DateTime`, nullable;
    - `merged_by`: `String`, nullable.
  - Write the migration: add two nullable columns, and drop them in `downgrade`.
  - Add the repository methods, `mark_merged`, and the `merged_by` parameter.
- [ ] **Step 4:** Rerun the tests until they PASS, then run the full verify list.
- [ ] **Step 5:** Commit `feat(needs): excluded_at and merged_by on Need; active Needs exclude excluded ones`.

### Task 2: Exclude/restore routes; split and from-needs respect exclusion

**Files:**
- Modify:
  - `src/curriculum_agent/api/routes/needs.py` (next to the split route, around lines 71-95)
  - `src/curriculum_agent/api/routes/plos.py` (`_merge_needs`, next to the merged-away check around line 394)
- Test:
  - `tests/unit/test_need_exclude.py`
  - `tests/unit/test_need_split.py` (extend)
  - `tests/unit/test_active_needs_downstream.py` (extend)

**Interfaces:**
- **Consumes:** `NeedRepository.set_excluded`, and `Need.excluded_at` (Task 1).
- **Produces:**
  - `POST /programs/{program_id}/needs/{need_id}/exclude` and `POST /programs/{program_id}/needs/{need_id}/restore`. Both return `Need`, need the API key like split, and run under `sync_writer`.

Refusals, in this order, each with the spec's Thai text or equivalent wording:
1. 409 busy (from `sync_writer`).
2. 404 "ไม่พบ Need นี้".
3. 422 merged away: "Need นี้ถูกรวมเข้ากับ Need อื่นแล้ว — ตัด Need ที่รวมแล้วแทน".
4. 422 on exclude when already excluded: "Need นี้ถูกตัดออกอยู่แล้ว".
5. 422 on restore when not excluded: "Need นี้ไม่ได้ถูกตัดออก".
6. On exclude only, 409 when a stored PLO cites the Need: "มี PLO อ้างถึง Need นี้ — ลบหรือรวม PLO ก่อนตัด Need".

Split: an excluded merged Need gives 422 "คืน Need ก่อนแยก". It is checked after the 404 and before the not-merged 422.

`_merge_needs` in `plos.py`: an excluded Need gives 422 "Need นี้ถูกตัดออกแล้ว — คืน Need ก่อนนำมารวมเป็น PLO".

Steps:
- [ ] **Step 1: Write failing tests:**
  - `test_exclude_then_restore`: the Need leaves and then rejoins `GET /needs/?active_only=true`;
  - every refusal above, including busy 409, following `test_need_split.py`'s fixtures;
  - `test_exclude_cited_need_409`;
  - `test_restore_has_no_plo_check`;
  - `test_split_excluded_merged_need_422`;
  - `test_from_needs_refuses_excluded` (Review Focus 5);
  - `test_resume_reload_drops_excluded`, following `test_need_split.py:166`;
  - `test_synthesis_skips_excluded`, in `test_active_needs_downstream.py`.
- [ ] **Step 2:** Run them. Expect FAIL.
- [ ] **Step 3:** Implement the routes and the two checks. Set `excluded_at` to `datetime.now(UTC).replace(tzinfo=None)` (naive UTC, as in the DB convention).
- [ ] **Step 4:** Tests PASS, then the full verify list.
- [ ] **Step 5:** Commit `feat(needs): designer can exclude and restore a Need; split and from-needs respect exclusion`.

### Task 3: Manual merge route

**Files:**
- Modify: `src/curriculum_agent/api/routes/needs.py`
- Test: `tests/unit/test_need_manual_merge.py` (new)

**Interfaces:**
- **Consumes:**
  - `need_merge._write_merged(..., merged_by="designer")`, `NeedRepository.write_merge` (Task 1);
  - `need_dedup.FoldGroup`, `MAX_GROUP_SIZE`;
  - `need_grouping.MIN_CORE_AFTER_MERGE`, `is_unwritten_need`;
  - `plo_synthesis.plos_citing`;
  - `api/jobs.sync_writer`.
- **Produces:** `POST /programs/{program_id}/needs/merge`.
  - Body: `ManualMergeRequest(need_ids: list[str], reason_th: str | None = Field(default=None, max_length=400))`.
  - Response: `Need` (the merged one).
  - It needs the API key.

**Checks, in this order, all before any LLM call:**
1. 409 busy (`sync_writer`).
2. 422 duplicate ids: "เลือก Need ซ้ำ".
3. 422 unless there are 2-5 ids: "เลือก Need 2-5 ข้อเพื่อรวม".
4. 422 unknown: "ไม่พบ Need: <ids>".
5. 422 not active, i.e. merged away or excluded: "Need <id> ไม่อยู่ในชุดที่ใช้งาน".
6. 422 unwritten. Reuse the `from-needs` wording style.
7. 409 PLO-cited: "มี PLO อ้างถึง Need: <ids> — ลบหรือรวม PLO ก่อนรวม Need".
8. 422 floor. Compute it worst-case: `projected = current_core - selected_core + (1 if selected_core else 0)`, where core means `not is_optional`, over active Needs. Refuse when `projected < MIN_CORE_AFTER_MERGE and projected < current_core`, with "การรวมนี้จะเหลือ Need หลัก <n> ข้อ ต่ำกว่าขั้นต่ำ <MIN> ข้อ".

**Then:**
- Order the selection by demand, using `need_merge._demand_order`.
- Build `FoldGroup(needs=..., reason_th=reason_th or "ผู้ออกแบบหลักสูตรเลือกรวม Need เหล่านี้")`.
- Load what `_write_merged` needs, the way `merge_duplicates` does:
  - skills keyed by id;
  - the evidence-to-stakeholder-type map, following how `need_combination` builds `stakeholder_type_by_evidence`;
  - the program context line.
- Call `_write_merged`. If it returns `None`, answer 502 "เขียนประโยค Need ที่รวมแล้วไม่สำเร็จ ลองใหม่อีกครั้ง" and write nothing. Otherwise call `write_merge` and return the merged Need.
- Scope is not checked; log an info line when a selected Need is out of scope.
- **Nesting.** A selected merged Need is an ordinary member. It keeps its own `merged_from`, and only its `merged_into` is set.

Steps:
- [ ] **Step 1: Write failing tests,** with `complete_need_combination` / `_write_merged` faked as in `test_need_merge.py`:
  - `test_manual_merge_success`: the merged Need has `merged_by == "designer"`, `merged_from` equal to the selection in demand order, and `merge_reason_th` equal to the given reason or the fallback; each selected Need has `merged_into` set;
  - each refusal 1-8;
  - `test_manual_merge_duplicate_ids_422` (Review Focus 3);
  - `test_manual_merge_second_request_while_first_registered_409` (Review Focus 2): register a writer via `sync_writer`'s registry, or follow the busy test in `test_need_split.py`;
  - `test_manual_merge_sentence_failure_502_writes_nothing`;
  - `test_manual_merge_nests_merged_need`: merge (M1, N3); split the result, which returns M1 and N3 with M1 still merged; split M1, which returns its originals;
  - `test_manual_merge_while_session_paused`: a suspended session does not block the merge, and the resume reload sees the merged Need. Follow `test_need_split.py`'s suspended-session case.
- [ ] **Step 2:** Run them. Expect FAIL.
- [ ] **Step 3:** Implement the route.
- [ ] **Step 4:** Tests PASS, then the full verify list.
- [ ] **Step 5:** Commit `feat(needs): designer merges 2-5 Needs at the Need checkpoint`.

### Task 4: Evidence edit and lock

**Files:**
- Modify:
  - `src/curriculum_agent/api/routes/evidence.py`
  - `src/curriculum_agent/data/repositories.py` (only if a small read helper is missing)
- Test: `tests/unit/test_evidence_lock.py` (new); extend `tests/unit/test_evidence_routes.py` where existing tests now need an unlocked program.

**Interfaces:**
- **Produces** `async def evidence_lock_reason(program_id: str) -> str | None`. It returns the Thai 409 text, or `None` when the program is unlocked. It is locked when:
  - `program_busy(program_id)` is not None (return that reason; Review Focus 1); or
  - the program has at least one stored skill; or
  - the program has at least one stored Need.

  Use the existing repository reads; an `exists`-style query is fine if one is added to the repository.

  The lock text is: "สกัดทักษะจาก evidence แล้ว แก้ เพิ่ม หรือลบ evidence ไม่ได้ — คัดลอกหลักสูตรแบบเฉพาะข้อมูลนำเข้าหากต้องแก้".
- **Produces** `PUT /programs/{program_id}/evidence/{evidence_id}`.
  - Body `EvidenceUpdate(stakeholder_type: StakeholderType, source_name: str, raw_text_th: str, source_url: str | None = None)`. Use the same field validation as add.
  - It keeps `evidence_id`, recomputes `classification` with `classify_evidence_type`, and returns `StakeholderEvidence`.
  - It answers 404 for an unknown or wrong-program id and 409 when locked, and it needs the API key.
- **Changes:** `POST /evidence/`, `DELETE /evidence/{id}` and `GET /evidence/classify-stream` call `evidence_lock_reason` first and answer 409 when it is not None.
- **Changes:** `GET /programs/{program_id}/evidence/` is unchanged. Add `GET /programs/{program_id}/evidence/lock`, which returns `{"locked": bool, "reason_th": str | None}`, for the UI.

Steps:
- [ ] **Step 1: Write failing tests:**
  - `test_put_edits_before_lock`, where changing `stakeholder_type` to `professional_council` gives `classification == "requirement"`;
  - `test_put_404`;
  - for each of POST add, POST with an existing id, PUT, DELETE and classify-stream: 409 when skills exist;
  - `test_lock_with_needs_only`;
  - `test_unlocked_with_no_skills_or_needs`;
  - `test_mutation_409_while_busy` (Review Focus 1);
  - `test_lock_endpoint`.
- [ ] **Step 2:** Run them. Expect FAIL.
- [ ] **Step 3:** Implement. Existing tests in `test_evidence_routes.py` that mutate evidence on a program with skills must be adjusted so they keep their intent: give the program no skills, or assert 409 where that is the point.
- [ ] **Step 4:** Tests PASS, then the full verify list.
- [ ] **Step 5:** Commit `feat(evidence): edit before extraction; every evidence mutation is refused once skills or Needs exist`.

### Task 5: Program copy "evidence only" mode

**Files:**
- Modify:
  - `src/curriculum_agent/data/program_copy.py` (`build_copy` around line 136, `copy_program` around line 223)
  - `src/curriculum_agent/api/routes/programs.py` (`copy_program_route` around line 93)
- Test: `tests/unit/test_program_copy_build.py`, `tests/unit/test_program_copy_route.py` (extend)

**Interfaces:**
- **Produces:**
  - `CopyMode = Literal["full", "evidence_only"]`;
  - `build_copy(src, new_id, *, now, new_uuid=..., mode: CopyMode = "full") -> ProgramRows`;
  - `copy_program(source_id, new_id, *, now=None, mode: CopyMode = "full") -> bool`.
- **The route** reads an optional JSON body `ProgramCopyRequest(mode: CopyMode = "full")`. A request without a body behaves as today.
- **`evidence_only`** returns `ProgramRows` with:
  - the cloned program;
  - evidence re-keyed through `remap_ids`;
  - `skills=[]`, `needs=[]`, `plos=[]`, `review=None`, `skill_groups=[]`.

Steps:
- [ ] **Step 1: Write failing tests:**
  - `test_build_copy_evidence_only`: new evidence ids; no skills, Needs, PLOs, review or groups; `copied_from` set as in the full mode;
  - `test_copy_route_evidence_only_unlocked`: after the copy, `evidence_lock_reason(new_id)` is None (Task 4);
  - `test_copy_route_without_body_is_full`.
- [ ] **Step 2:** Run them. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Tests PASS, then the full verify list.
- [ ] **Step 5:** Commit `feat(programs): evidence-only copy as the way to change evidence after extraction`.

### Task 6: Need page UI (merge, exclude, restore, who merged, reset note)

**Files:**
- Modify:
  - `frontend/src/pages/NeedAnalysis.tsx`
  - `frontend/src/pages/components/NeedCard.tsx` (and the `NeedRow` type there: add `excluded_at: string | null`, `merged_by: 'agent' | 'designer' | null`)
  - mock handlers under `frontend/src/mock`, if they serve the Need routes

**Interfaces:**
- **Consumes:**
  - `POST /needs/merge` with `{need_ids, reason_th}`;
  - `POST /needs/{id}/exclude`, `POST /needs/{id}/restore` (Tasks 2-3);
  - `GET /needs/?active_only=false`, which now carries `excluded_at` and `merged_by`.

Behaviour (spec, UI section):
- **Active list.** `merged_into === null && excluded_at === null`. Each card has:
  - a select checkbox;
  - "ตัดออก" with the two-step confirm.
- **Selection bar** appears when 1 or more are selected. It shows:
  - the selected count;
  - an optional reason input (max 400);
  - the button "รวม Need ที่เลือก (n)", enabled at 2-5.

  While the call runs, the button shows the split-style busy state. An error shows the route's Thai `detail` in the bar. A 409 calls `refresh()`, as split does. On success the selection clears and the page calls `fetchAll()`.
- **Excluded Needs** go in a collapsed section "Need ที่ตัดออก (n)" below the active list. Each shows its sentence, the existing trail link and "คืน".
- **Merged Needs** show "รวมโดยผู้ออกแบบ" or "รวมโดย AI" from `merged_by`. A nested merged Need inside the originals disclosure renders with its own disclosure.
- **Reset note.** "รัน Agent 2 ใหม่จะล้างการรวมและการตัดออกที่ทำด้วยมือ" sits beside the Agent 2 re-run control.
- The existing `busy` flag includes the new in-flight states.

Steps:
- [ ] **Step 1:** Implement.
- [ ] **Step 2:** Run `npm --prefix frontend run build` and `npm --prefix frontend run lint`. Both must pass.
- [ ] **Step 3:** Commit `feat(ui): merge, exclude and restore Needs on the Need page`.

### Task 7: Evidence page and copy-mode UI

**Files:**
- Modify:
  - `frontend/src/pages/StakeholderNeeds.tsx`
  - `frontend/src/pages/Programs.tsx`
  - mock handlers, if they serve these routes

**Interfaces:**
- **Consumes:**
  - `GET /evidence/lock` and `PUT /evidence/{id}` (Task 4);
  - `POST /programs/{id}/copy` with body `{mode}` (Task 5).

Behaviour:
- **Evidence page, unlocked.** Each item gets "แก้ไข". It fills the existing add form, and saving sends `PUT` and refetches. A cancel action restores the empty add form.
- **Evidence page, locked.** The add form, file import, edit and delete are hidden. A note shows `reason_th` and a link to the programs list. The page fetches the lock state alongside the evidence list.
- **Programs page.** The copy action offers "คัดลอกทั้งหมด" (`mode: "full"`) and "คัดลอกเฉพาะข้อมูลนำเข้า (แก้ evidence ได้)" (`mode: "evidence_only"`). Copy errors keep the existing per-row error.

Steps:
- [ ] **Step 1:** Implement.
- [ ] **Step 2:** Run the frontend build and lint. Both must pass.
- [ ] **Step 3:** Commit `feat(ui): edit evidence before extraction, lock note after, evidence-only copy`.

### Task 8: Docs (controller task; no subagent)

**Files:**
- Modify:
  - `.claude/rules/need-pipeline.md` (the "Active vs merged" bullet: add exclusion, manual merge, `merged_by` and nesting);
  - `.claude/rules/api-data.md` (the `sync_writer` list gains `/needs/merge`, `/exclude` and `/restore`; the copy gains `mode`; the evidence lock);
  - `.claude/skills/curriculum-design-agent/references/data-schemas.md` (Need: `excluded_at`, `merged_by`);
  - `CLAUDE.md` (rule 7's checkpoint paragraph: one sentence noting that the designer merges and excludes at `need_analysis`, and that evidence locks after extraction).

Steps:
- [ ] **Step 1:** Edit the files.
- [ ] **Step 2:** Commit `docs: phase 2 — Need exclusion and manual merge, evidence lock, evidence-only copy`.
