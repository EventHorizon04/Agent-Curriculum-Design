# Phase 6 follow-up: one alignment redraft per PLO per loop, version-checked PUT

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** stop the apply loop from redrafting the same outcome for alignment round after round (designer decision 28), and close the two `PUT /plos/{id}` races the phase 6 final review left as tickets.

**Architecture:**
- **Alignment guard.** `LoopMemory` gains a Need-set memory for applied alignment redrafts, beside the existing merge memory.
- **PUT.** `PUT /plos/{id}` becomes an update-only, version-conditional write.
- **Redraft check.** `redraft_from_needs`' optimistic check compares `version` rather than the statement.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-04-four-agent-pipeline-phase6-design.md` (decision 28; decisions 13 and 24 for context).

## Global Constraints

- **Git:**
  - Branch `feat/four-agent-pipeline`. Run `git branch --show-current` before every commit.
  - Stage by explicit path. Never commit `.env`, `.env.demo` or `dist/`.
  - Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Database and LLM:**
  - Implementers never run alembic, never connect to a DB and never call a real LLM.
  - No schema change: `plos.version` already exists.
- **Conventions:**
  - `from __future__ import annotations`, type hints, `loguru`, repository pattern.
  - Thai for user-facing strings, English for code, comments and logs.
- **Verify:**
  - `uv run pytest -q`, with no unraisable warnings.
  - `uv run ruff check src tests`
  - `uv run ruff format --check src tests`
  - `uv run mypy src`
  - `uv run python scripts/dump_prompts.py --check`

## Review Focus

1. **Round 1 applies an alignment redraft to PLO3; round 2 Bloom-redrafts PLO3; round 3 raises alignment on PLO3 again.** The round-3 finding is skipped, because the guard is keyed on the Need set, not on the statement.
2. **A round whose only agreed findings are guarded alignment findings** stops as a pass, and no further review runs.
3. **Two PUTs on the same PLO race:** the second answers 409, and no row is duplicated or resurrected.
4. **A PUT on a PLO that a redraft just merged away** answers 404/409 and never re-inserts it.

---

### Task 1: one alignment redraft per PLO per loop (decision 28)

**Files:**
- `src/curriculum_agent/stages/plo_feedback.py`
- `src/curriculum_agent/stages/plo_review_loop.py`, only if `has_agreed_work` needs the memory passed in
- docs: `.claude/rules/plo-review.md` (the loop bullet), `CLAUDE.md` rule 7 (one clause)
- tests: `tests/unit/test_plo_feedback.py`, `tests/unit/test_plo_review_loop.py`

**Interfaces:**
- `LoopMemory.aligned: set[frozenset[str]]`, default empty.
  - An applied alignment action adds `frozenset(result PLO's source_need_ids)`; the applied path of `_send_alignment` adds it.
  - A dry run does not add.
- `REASON_ALIGNED_EARLIER = "PLO นี้แก้ความสอดคล้องไปแล้วในรอบก่อน — เป็นข้อสังเกต"`.
  - `_send_alignment` checks it after `unavailable_reason` and before any redraft.
  - The live PLO is matched by `frozenset(source_need_ids) in memory.aligned`.
- `actionable_count` does not count rows skipped with `REASON_ALIGNED_EARLIER`, the same treatment as `REASON_KSEC_NO_NEED`.
- `has_agreed_work(..., memory: LoopMemory | None = None)` does not count an agreed alignment finding on a guarded PLO. The loop passes its memory.

**Steps:**
- [ ] **Step 1: write the failing tests.**
  - `test_alignment_applied_once_per_plo_per_loop`: round 1 applied, then a round-2 alignment finding on the same Need set is skipped with the exact text.
  - `test_alignment_guard_survives_bloom_redraft`: Review Focus 1.
  - `test_guarded_alignment_is_not_actionable`: `actionable_count` returns 0 for such a row.
  - `test_round_with_only_guarded_alignment_is_a_pass`: Review Focus 2, at the loop level with a fake review and send_back.
  - `test_dry_run_never_adds_to_aligned`.
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: run the full verify and confirm PASS.**
- [ ] **Step 5: commit** `feat(send-back): one alignment redraft per PLO per loop (designer decision 28)`.

### Task 2: version-checked PUT and redraft check

**Files:**
- `src/curriculum_agent/data/repositories.py`
- `src/curriculum_agent/api/routes/plos.py` (`update_plo`)
- `src/curriculum_agent/stages/plo_redraft.py`
- `.claude/rules/api-data.md`
- tests: `tests/unit/test_api_plos.py` (or the PUT test file), `tests/unit/test_redraft_concurrent_edit.py`, `tests/unit/test_plo_feedback.py`

**Interfaces:**
- `PLORepository.update_if_version(plo: PLO, *, expected_version: int) -> bool`.
  - Implemented as `UPDATE plos SET … WHERE program_id = :pid AND plo_id = :id AND version = :expected`, built from the same row mapping `bulk_insert` uses (`_plo_row_data`).
  - Returns False when no row matched. It never inserts.
- `PUT /plos/{id}`:
  - Writes through `update_if_version(updated, expected_version=match.version)`; the `updated` row carries `version = match.version + 1` as today.
  - False → 409 `"PLO นี้ถูกเปลี่ยนระหว่างแก้ไข — โหลดใหม่แล้วลองอีกครั้ง"`.
  - The existing 404 for a PLO not found at read time is unchanged.
  - Every other PUT behaviour is unchanged: stale marking, `designer_edited_at`, the hard gate.
- `redraft_from_needs`' `expect` becomes `{plo_id: version}`.
  - `PLORepository.replace(expect=...)` compares `version`, so a PUT that changes only bloom, verb or rationale also refuses the replace.
  - The `PLOChangedDuringRedraft` → 409/skipped mapping and its Thai text are unchanged.
- Dead test: `test_an_error_outside_the_actions_is_swallowed` (`tests/unit/test_plo_feedback.py` ~336) no longer exercises its path. Repoint it at a skipped row whose trail write fails, or at an exception raised outside the actions, so it asserts something real again.

**Steps:**
- [ ] **Step 1: write the failing tests.**
  - `test_put_conflicting_version_answers_409_and_writes_nothing`
  - `test_put_on_row_deleted_between_read_and_write_answers_409_no_insert` (Review Focus 4)
  - `test_put_success_bumps_version_once`
  - `test_replace_refuses_on_version_change_only` (a PUT that changed only `action_verb_th`)
  - the repaired swallow test
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.**
- [ ] **Step 4: run the full verify and confirm PASS.**
- [ ] **Step 5: commit** `fix(plos): version-checked PUT and redraft check`.

### Task 3 (controller): apply re-run and UI smoke test

- [ ] **Step 1: apply re-run.**
  - Start the copy backend with `PLO_REVIEW_LOOP_MODE=apply` and run a fresh full copy through `/plos/run`.
  - Record the rounds, the stop reason, how many alignment redrafts each PLO got, usage and wall time against `.scratch/reports/2026-11-06-phase6c-loop.md`.
  - Append the result to that report as section 5 and commit it.
- [ ] **Step 2: UI smoke test.**
  - Open the frontend in mock mode and walk through: the review page (findings, the alignment section, rounds in the trail, the open-comments box, the approve button), then the report page (stored report, stale banner, empty state).
  - Note any defect for a fix task.

### Task 4: revalidate write is version-checked; mock loop stop is consistent (found by Task 3)

**Files:** `src/curriculum_agent/api/routes/plos.py` (`revalidate_plo` job body), `frontend/src/mock/handlers.ts`; tests `tests/unit/test_api_plos.py` (or the revalidate test file).

**Interfaces:**
- **`revalidate_plo`.** The job body writes the re-judged PLO through `PLORepository.update_if_version(updated, expected_version=match.version)` instead of `bulk_insert`. `updated` carries `version = match.version + 1` and keeps `designer_edited_at`, as today.
  - On False the job fails with the Thai error `"PLO นี้ถูกแก้ระหว่างตรวจ SMART — ตรวจใหม่อีกครั้ง"`: raise so `jobs._run` records it as `error_th`, the way other job failures surface.
  - Nothing is inserted.
- **Mock (smoke test finding).**
  - The mock review run's last round stops with "ผ่านแล้ว" while the stored review it leaves still has agreed redundancy and Bloom findings. That cannot happen against the real backend: pass means no agreed actionable finding.
  - Make the mock consistent. Either:
    - the stored round-2 review has no agreed actionable finding (findings below the threshold may stay); or
    - keep the findings and stop with the real reason text for that case.
  - Prefer the first option, so the open-comments box still shows the skipped unused-Need row.

- [ ] **Step 1: write the failing tests.**
  - `test_revalidate_conflicting_version_fails_job_writes_nothing`
  - `test_revalidate_success_bumps_version_once`
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement.** Fix the mock.
- [ ] **Step 4: run the backend verify, `npm run build` and `npm run lint`.**
- [ ] **Step 5: commit** `fix(plos): version-checked revalidate write; mock loop stop matches its review`.
