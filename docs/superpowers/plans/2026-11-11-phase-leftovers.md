# Phase 2-5 leftovers: excluded Needs in the report, consistent write auth, extraction-bound and EC/K grouping measurements

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** close the items earlier phases left open on branch `feat/four-agent-pipeline`. The designer asked on 2026-11-11 for all of them to be done.

**Leftovers and what this plan does with each:**
- **Excluded Needs in the PLO report (phase 2).** Task 1.
- **Write routes without auth (phase 2).** Task 2, after the designer chooses an approach.
- **Downstream effect of the extraction bound (phase 5).** Task 3, a measurement on the copy DB.
- **Weak EC/K grouping (2026-10-28 report, open item 3).** Task 4, an offline A/B on stored skills, shipped only if better.
- **Batching need_dedup / plo_review.** Not done; see Ruling below.

**Tech Stack:** FastAPI, Pydantic v2, pytest, React + Vite + TypeScript.

**Spec:** none for this plan. These are follow-ups from:
- phase 2 (`docs/superpowers/specs/2026-11-03-four-agent-pipeline-phase2-design.md`);
- phase 5 (the extraction report `.scratch/reports/2026-11-03-phase5-extraction.md`);
- `.scratch/reports/2026-10-28-glm-full-pipeline.md` (open item 3).

**Ruling (batching):** not built.
- **Why:** `need_dedup` warns above 30 Needs and `plo_review` above 15 PLOs. `MAX_CORE_PLOS` is 10, so the review only exceeds 15 with many optional PLOs. No corpus so far has come close: the largest run had 16 active Needs and 10 PLOs.
- **Cost if wrong:** a larger corpus gets one long call instead of several. The existing warnings name it.

## Global Constraints

- **Git:**
  - Branch `feat/four-agent-pipeline`. Run `git branch --show-current` before every commit.
  - Stage by explicit path. Never commit `.env`, `.env.demo` or `dist/`.
  - Trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Database and LLM:**
  - Implementers never run alembic, never connect to a DB and never call a real LLM.
  - No schema change.
- **Conventions:**
  - `from __future__ import annotations`, type hints, `loguru`, repository pattern.
  - Thai for user-facing strings, English for code, comments and logs.
  - Frontend visual identity: use the component classes in `index.css` and the stamp, mandate and marker inks. Never the Tailwind palette.
- **Verify:**
  - `uv run pytest -q`
  - `uv run ruff check src tests`
  - `uv run ruff format --check src tests`
  - `uv run mypy src`
  - `uv run python scripts/dump_prompts.py --check`
  - In `frontend/`: `npm run build` and `npm run lint` (0 errors).

## Review Focus

1. **A Need excluded after the report was stored:** the next report lists it under excluded and not under "Need ที่ไม่ได้เป็น PLO". It is never listed in both.
2. **A Need folded into a merged Need (`merged_into`)** is not an exclusion and must not appear in the excluded list.
3. **A report stored before this change** (no `needs_excluded` key) still renders, showing no excluded section.

---

### Task 1: the PLO report lists the Needs the designer excluded

**Files:**
- `src/curriculum_agent/stages/plo_report.py`
- `src/curriculum_agent/data/repositories.py`, only if a query is needed. `NeedRepository.list_by_program` already returns every Need, so filter on `excluded_at is not None and merged_into is None`.
- `frontend/src/pages/PloReport.tsx`
- `frontend/src/mock/handlers.ts` and/or `frontend/src/mock/scenarios.ts`, so the complete scenario shows one excluded Need.
- Docs: the `plo_report` paragraph in `.claude/rules/api-data.md` or the skill's `references/data-schemas.md`, wherever the report dict's keys are listed (one line).
- Tests: the report stage test file (find it with `grep -rl "plo_report" tests/unit`).

**Interfaces:**
- `report["needs_excluded"]` is a list of `{"need_id", "statement_th", "ksec_categories", "demand_score", "excluded_at"}`, with `excluded_at` as an ISO string, sorted by `excluded_at` then `need_id`.
- `report["counts"]["needs_excluded"]` is an int.
- `needs_not_synthesized` stays as is. It already reads only active Needs, so an excluded Need cannot appear in both lists. Pin that with a test.
- UI:
  - In `PloReport.tsx`, add a section after "Need ที่ไม่ได้เป็น PLO" titled `Need ที่ผู้ออกแบบตัดออก`.
  - Each row shows the statement, the KSEC label and the date, formatted the way the page already formats dates (or `toLocaleDateString('th-TH')` if it formats none).
  - Add one line under the title: `ตัดออกที่ขั้นวิเคราะห์ Need — กู้คืนได้ที่หน้า Need`.
  - When the list is empty or the key is missing, render no section.
  - Add the count next to the existing "Need ไม่ได้ใช้" figure only if that strip has room for it. That is the implementer's call.

**Steps:**
- [ ] **Step 1: write the failing tests.**
  - `test_report_lists_excluded_needs`
  - `test_merged_original_is_not_listed_as_excluded`
  - `test_excluded_need_is_not_also_not_synthesized`
  - `test_report_without_exclusions_has_empty_list`
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement**, backend then UI and mock.
- [ ] **Step 4: run the full verify and confirm PASS.**
- [ ] **Step 5: commit** `feat(report): list the Needs the designer excluded`.

### Task 2: consistent write auth, with the key typed in the UI (designer's choice, 2026-11-11)

**Today:**
- `require_api_key` guards only some writes: evidence, programs, PLO PUT and revalidate, and session DELETE.
- These writes are open: every needs write, `plos/run`, `report/run`, `review/run`, `from-needs`, and session start, approve and reject.
- The frontend sends no `X-API-Key`.
- `APP_ENV=production` refuses to start without `API_KEY`, while the demo refuses to start *with* one (`scripts/start-demo.ps1`).

**Designer's choice:**
- Every write route requires the key.
- The designer types the key once per browser session. It is kept in `sessionStorage` and sent on every request. It is never built into the bundle.

**Files:**
- Backend:
  - every router under `src/curriculum_agent/api/routes/` that has a non-GET route without `dependencies=[Depends(require_api_key)]`
  - `src/curriculum_agent/api/deps.py` (unchanged unless needed)
- Frontend:
  - `frontend/src/api/client.ts`
  - the raw `fetch` in `frontend/src/pages/StakeholderNeeds.tsx` (~230, the classify stream)
  - a new `frontend/src/components/ApiKeyDialog.tsx` (or the closest existing modal pattern), mounted once in the app shell
- Docs and scripts:
  - `.env.example` (the API_KEY comment)
  - `docs/demo-runbook.md`
  - `scripts/start-demo.ps1` (the "API_KEY must stay unset" check)
  - `.claude/rules/api-data.md` (one bullet on auth)
- Tests: a new `tests/unit/test_api_auth_coverage.py`, plus updates to any test that now gets a 401.

**Interfaces:**
- **Backend.**
  - Every route whose methods include POST, PUT, PATCH or DELETE carries `require_api_key`. GET routes stay open, as `docs/demo-runbook.md` already states.
  - `require_api_key` keeps its rule: `settings.api_key` None or blank means auth is off (dev).
  - The test `test_every_write_route_requires_the_api_key` walks `app.routes` (`curriculum_agent.api` app factory or module app) and asserts that each non-GET `APIRoute`'s dependant tree contains `require_api_key`. Its allowlist starts empty: if a write route must stay open, list it with a reason and report it.
  - The test `test_write_without_key_is_401_when_key_set` sets `settings.api_key` and posts to one formerly open route (e.g. `POST /programs/{id}/needs/{need_id}/exclude`) without the header, expecting 401.
- **Frontend.**
  - `client.ts` adds a request interceptor that sets `X-API-Key` from `sessionStorage['curriculum.apiKey']` when present. Wrap every storage access in try/catch.
  - A response interceptor handles 401 as follows:
    - It opens the key dialog through a small event/emitter.
    - It awaits the designer's key, stores it, and retries the original request once with the header.
    - A second 401 rejects as usual. Cancelling the dialog rejects with the original error.
    - Concurrent 401s share one dialog.
  - The raw `fetch` for the classify stream sends the same header. On a 401 it uses the same dialog and retries once.
  - Dialog:
    - Title `กรอก API key`, with one `type="password"` input (`autoComplete="off"`), buttons `บันทึก` and `ยกเลิก`.
    - One line of help: `ขอ key จากผู้ดูแลระบบ — เก็บไว้เฉพาะแท็บนี้จนกว่าจะปิด`.
    - Use the component classes in `index.css`.
  - The key never goes into a URL, a log or `localStorage`.
  - Mock mode (`?mock=`) needs no key; the mock handlers bypass axios auth or never return 401.
- **Demo.** `start-demo.ps1` no longer fails when `API_KEY` is set. It warns when `API_KEY` is unset ("writes are open to anyone past Access"), and the runbook tells the operator to set it and hand the key to the designer.

**Steps:**
- [ ] **Step 1: write the failing tests.**
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement**, backend then frontend, then docs and script.
- [ ] **Step 4: run the full verify and confirm PASS.**
- [ ] **Step 5: commit** `feat(auth): every write route requires the API key; the UI asks for it`.

### Task 3 (controller): what the extraction bound changes downstream

- Make two fresh full copies of `program` on the copy DB, with the reasoning and `max_tokens` extraction bound on (the default) and off (`0`).
- Run Agent 1 and Agent 2 (`/needs/run`) on each.
- Compare skills per KSEC bucket, the skill groups, active Needs, merges, and the Need statements themselves.
- Append the result to `.scratch/reports/2026-11-03-phase5-extraction.md` and commit it.

### Task 4b: ship the EC bucket rule (A/B result: `.scratch/reports/2026-11-11-ec-k-grouping-ab.md`)

**Files:**
- `src/curriculum_agent/prompts/cluster_skills.py`
- `src/curriculum_agent/stages/llm_clustering.py`
- `src/curriculum_agent/stages/skill_grouping.py`
- `docs/prompt-inventory.md`, regenerated with `uv run python scripts/dump_prompts.py`
- The skill's `references/prompts.md`: one short paragraph on why, under the clustering prompt.
- Tests: `tests/unit/test_cluster_skills_prompt.py` (or wherever the clustering prompt is tested), plus the llm_clustering cache-key tests.

**Interfaces:**
- **Prompt builder.**
  - The signature becomes `build_cluster_skills_prompt(skill_names, target_clusters=None, program_context=None, ksec: KSECCategory | None = None)`.
  - When `ksec` is `KSECCategory.EC`, insert this rule line immediately before the `- label_th MUST be written in Thai` line, verbatim:
    `- These skills are attitudes (E) and adaptability or self-development traits (C). Do not gather them into one general 'good character' group. Group each trait by where the graduate shows it: in the quality of and accountability for their own work (accuracy, care, owning errors, professional integrity); toward other people and cultures (ethical conduct across cultures, respect for diversity, working relationships); or toward change and their own career (adapting to technology and society, lifelong learning, leadership, entrepreneurship). A trait that fits none of these may form a group of its own.`
  - Any other `ksec`, or None, adds nothing, so the K, S, E and C prompts are byte-identical to today.
- **Threading `ksec` through.**
  - Add `ksec: KSECCategory | None = None` to `cluster_skill_names`, `_cluster_pass` and `_cluster_map_reduce`. In map-reduce, the batch passes get it; the merge prompt is unchanged.
  - `skill_grouping._cluster_factory` passes the bucket's `ksec`.
- **Cache.**
  - `cluster_skill_names` puts `str(ksec)` in the cache key, because the prompt now varies by bucket.
  - `_clustering_contract_fingerprint` also hashes the EC variant (`build_cluster_skills_prompt([], None, None, KSECCategory.EC)`), so editing the rule invalidates entries.
  - Existing non-EC cache entries are invalidated once by the key change. That is acceptable.
- **Docstring.** Add a short paragraph to `build_cluster_skills_prompt`'s docstring giving the A/B result:
  - 7 of 9 runs gave three stable dimensions against control's unstable grab-bag;
  - one group over target;
  - the K rule was tried and dropped.
  Match the docstring's existing history style.

**Steps:**
- [ ] **Step 1: write the failing tests.**
  - `test_ec_bucket_prompt_carries_the_dimension_rule`
  - `test_other_buckets_prompt_unchanged`: compare K, S and None against the output of a call without `ksec`.
  - `test_cache_key_differs_by_ksec`
  - `test_grouping_passes_bucket_to_clustering`
- [ ] **Step 2: run the tests and confirm they FAIL.**
- [ ] **Step 3: implement**, then regenerate `docs/prompt-inventory.md`.
- [ ] **Step 4: run the full verify and confirm PASS**, including `dump_prompts.py --check`.
- [ ] **Step 5: commit** `feat(grouping): EC bucket groups attitudes by where the graduate shows them`.

### Task 4 (controller first): EC/K grouping A/B

- On the skills from Task 3's bounded run, cluster the EC and K buckets with the current prompt and with a candidate prompt change. Run each 3 times, since the output is stochastic.
- Write both partitions side by side in a report.
- Ship the prompt change (implementer task, plus `dump_prompts.py` regeneration) only if it is clearly more coherent and no less stable. Otherwise record the negative result.
