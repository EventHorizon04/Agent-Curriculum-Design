# Four-agent pipeline, phase 1: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split skill extraction and Need analysis into two persisted, chained agents. Move duplicate-Need merging to the Need stage (automatic, splittable, multi-KSEC). Add a pipeline-wide model switch.

**Architecture:**
- **Agent 1** = `skill_extraction` followed by a new `skill_grouping` stage, which clusters inside each KSEC bucket and persists `SkillGroup` rows.
- **Agent 2** = `need_combination`. It writes one Need per stored group concurrently, then the new `need_merge` module runs dedup and stores merged Needs.
  - Originals keep `merged_into`; the merged Need carries `merged_from`.
  - Every downstream reader uses `NeedRepository.list_active_by_program`.
- **`plo_synthesis`** no longer folds anything.
- **Jobs:** the two agents run as two jobs chained by an `on_success` hook in `api/jobs.py`.
- **UI:** each agent gets its own rail stage and page (`skill_extraction`, `need_analysis`).

**Tech Stack:** Python 3.11, FastAPI, LangGraph, SQLAlchemy async + Alembic, Pydantic v2, Instructor, loguru; React 19 + Vite + TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-26-four-agent-pipeline-phase1-design.md`. Read it before any task. The section numbers below (§N) refer to it.

## Global Constraints

**Git**
- Work on branch `feat/four-agent-pipeline` only. Run `git branch --show-current` before every commit, because another session can switch branches in this worktree. Never touch `main`.

**Code conventions** (CLAUDE.md)
- `from __future__ import annotations` and type hints on every signature.
- Logging through loguru only.
- Pydantic v2 for anything crossing a boundary.
- No hand-parsed LLM JSON.
- Prompts live in `src/curriculum_agent/prompts/`, one builder per file.
- Data access goes through `data/repositories.py`.
- Thai for designer-facing strings (HTTP `detail`, UI copy). English for code, comments and logs.

**Fixed values**

| Constant | Value |
|---|---|
| `need_dedup.MAX_GROUP_SIZE` | `5` |
| `need_merge.TOP_SKILL_CAP` | `7` |
| `MIN_CORE_AFTER_MERGE` | `4` (unchanged) |
| `MAX_CORE_PLOS` | `10` (unchanged) |

**Migrations**
- New Alembic revisions chain from the current head `d1e2f3a4b5c6`. Task 2's migration has `down_revision = "d1e2f3a4b5c6"`, and Task 3's has `down_revision` = Task 2's revision. Run `uv run alembic heads` after each one; it must print a single head.

**Commands**
- Backend tests: `uv run pytest tests/unit -q`
- Lint: `uv run ruff check src tests`
- Types: `uv run mypy src`
- Frontend: `npm --prefix frontend run build` and `npm --prefix frontend run lint`

**Behaviour that must not change**
- With `PIPELINE_PROVIDER`/`PIPELINE_MODEL` unset, every slot resolves exactly as on `main`.
- Clustering never crosses a KSEC bucket.
- A merged Need's `member_skill_ids` and `source_evidence_ids` are the union of its originals'.
- Stored Needs are never deleted by a merge, only marked with `merged_into`.

## Review Focus

Things most likely to bite a real user that a task's happy-path tests miss. Each has a pinned test in the task named.

1. **A program stored before this branch** has Needs without the new columns and skills without groups.
   - Old Need rows must read as active, single-tag Needs.
   - `/needs/combine/run` must answer a Thai 422 that sends the designer to re-run skill extraction, not a 500.
   - Tests: Task 2 and Task 8.
2. **A LangGraph checkpoint dict carrying `ksec_category` (old key)** must still validate as a `Need` with `ksec_categories=[that tag]` (Task 2).
3. **A dedup answer naming an out-of-scope, unwritten or unknown Need**, or exceeding 5 members, is dropped whole. It must not crash the run or merge a filtered Need (Task 5).
4. **Split against a cited Need, and split while a graph session is paused at the Need checkpoint.**
   - When a PLO cites the merged Need: 409.
   - During a paused session: allowed, and the resumed session drafts from the restored originals, not the deleted merged Need.
   - Tests: Task 7.
5. **Agent 2 failing after Agent 1 succeeded** keeps the new skills and groups, records the failure on the Agent 2 job, and leaves the previous Needs in place (Task 8).

---

### Task 1: Pipeline-wide model switch

**Files:**
- Modify: `src/curriculum_agent/config.py` (Settings fields, `_apply_provider_model_defaults` ~L452-485)
- Modify: `.env.example`
- Test: `tests/unit/test_pipeline_model_switch.py` (new)

**Interfaces:**
- Produces:
  - `Settings.pipeline_provider: Literal["ollama","openrouter","opentyphoon"] | None = None`
  - `Settings.pipeline_model: str = ""`

- [ ] **Step 1: Write failing tests.** Build every `Settings` with `_env_file=None` plus the dummy secrets pattern from `tests/unit/test_config.py`.
  - `test_unset_pipeline_matches_today_per_slot`: for every `slot in SLOTS`, `Settings(_env_file=None, ...)` resolves the same `(provider, model)` with and without `pipeline_provider=None, pipeline_model=""`. Snapshot the expected pairs by computing them before the change in the test itself: compare against a `Settings` built without the new kwargs.
  - `test_pipeline_pair_applies_to_every_slot_without_own_setting`: `pipeline_provider="openrouter", pipeline_model="x/y"`, so every slot's provider is `"openrouter"` and its model is `"x/y"`.
  - `test_slot_own_provider_wins_and_never_takes_pipeline_model`: add `validation_provider="ollama"`, so validation is `("ollama", _PROVIDER_DEFAULT_MODEL["ollama"])` and the others are `("openrouter","x/y")`.
  - `test_slot_own_model_only_runs_on_pipeline_provider`: add `plo_review_model="a/b"`, so plo_review is `("openrouter","a/b")`.
  - `test_empty_provider_still_disables_under_pipeline`: add `need_dedup_provider=""`, so `settings.need_dedup_provider == ""`.
  - `test_pipeline_model_without_provider_refused`: `pipeline_model="x/y"` alone raises `ValidationError`.
- [ ] **Step 2: Run them.** `uv run pytest tests/unit/test_pipeline_model_switch.py -q`. Expected: FAIL (unknown fields).
- [ ] **Step 3: Implement.**
  - Add the two fields.
  - In `_apply_provider_model_defaults`, use `self.model_fields_set` to tell a slot field set by env or kwargs from a class default. A slot whose provider field is not in `model_fields_set` takes `pipeline_provider` when that is set. Its model takes `pipeline_model` only when its provider came from `pipeline_provider` and its own model field is not in `model_fields_set`. Otherwise keep today's chain.
  - Refuse `pipeline_model` without `pipeline_provider` in a `model_validator`.
  - Document both settings in `.env.example` under the slot section.
- [ ] **Step 4: Run the new tests plus `tests/unit/test_llm_slots.py tests/unit/test_config.py`.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: PIPELINE_PROVIDER/PIPELINE_MODEL switch for every LLM slot`.

### Task 2: Need schema v2 (multi-tag, merge links, active read)

**Files:**
- Modify: `src/curriculum_agent/models.py` (`Need`, ~L280-360)
- Modify: `src/curriculum_agent/data/orm.py` (`NeedTable`)
- Modify: `src/curriculum_agent/data/repositories.py` (`NeedRepository`)
- Modify: `src/curriculum_agent/data/program_copy.py` (`_REFERENCE_COLUMNS`)
- Modify: every reader of `Need.ksec_category`:
  - `exporters/excel_matrix.py:76`
  - `prompts/stage_3_plo.py:70`
  - `prompts/plo_review.py:119`
  - `stages/plo_review_facts.py:50,117`
  - `stages/smart_agent_tools.py:58,313`
  - `stages/need_dedup.py:72,121`
  - `stages/need_combination.py:697`
  - `models.py:606` (the review-facts model field becomes `ksec_categories: list[str]`)
- Create: `migrations/versions/<rev>_need_multi_ksec_and_merge_links.py`
- Test: `tests/unit/test_need_schema_v2.py` (new); update existing tests that read `.ksec_category` on a `Need`.

**Interfaces:**
- Produces, on `Need`:
  - `ksec_categories: list[KSECCategory]`: min 1, deduplicated, ordered K, S, E, C.
  - `top_skill_ids: list[str] = []`
  - `merged_from: list[str] = []`
  - `merged_into: str | None = None`
  - `merge_reason_th: str = ""`
  - `is_merged` property: `bool(self.merged_from)`.
- Produces: a `mode="before"` validator that maps an incoming `ksec_category` key to `ksec_categories=[value]` when `ksec_categories` is absent.
- Produces: `NeedRepository.list_active_by_program(program_id: str) -> list[Need]` (rows with `merged_into IS NULL`).
- Produces: `NeedRepository.split(program_id: str, merged_need_id: str) -> list[Need]`. In one transaction it deletes the merged row, clears `merged_into` on its originals, and returns them. Task 7 calls it.
- Produces: a Thai label helper `ksec_label(need: Need) -> str` in `stages/need_grouping.py`, joining the tags with `"+"` (e.g. `"K+S"`). Prompts and the exporter use it.

- [ ] **Step 1: Write failing tests** in `test_need_schema_v2.py`:
  - `test_old_key_maps_to_single_tag_list`: `Need.model_validate({..., "ksec_category": "S"}).ksec_categories == [KSECCategory.S]`.
  - `test_tags_deduplicated_and_ordered`: `ksec_categories=["S","K","S"]` gives `[K, S]`.
  - `test_empty_tags_rejected`: `ksec_categories=[]` raises `ValidationError`.
  - `test_unmerged_need_defaults`: `merged_into is None`, `merged_from == []`, `not need.is_merged`.
  - `test_ksec_label_joins_tags`: `ksec_label(need_with([K, S])) == "K+S"`.
  - `test_copy_remaps_merged_into`: `"merged_into" in _REFERENCE_COLUMNS`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement the model, ORM and repository.**
  - **Migration:**
    - Add `ksec_categories` JSONB NOT NULL, backfilled as `jsonb_build_array(ksec_category)`.
    - Drop `ksec_category`.
    - Add `top_skill_ids` and `merged_from` as JSONB, `server_default '[]'`.
    - Add `merged_into` as String, nullable.
    - Add `merge_reason_th` as Text NOT NULL, `server_default ''`.
    - Write a matching `downgrade` that takes the first tag back.
  - **Repository:** add `list_active_by_program` and `split`.
- [ ] **Step 4: Switch every reader listed above** from `.ksec_category` to `.ksec_categories` or `ksec_label`.
  - `plo_review_facts` coverage counts a Need under every tag it carries. Add `test_coverage_counts_each_tag_of_a_multi_tag_need` to `tests/unit/test_plo_review_facts.py`.
  - `need_combination` constructs Needs with `ksec_categories=[group.ksec]`.
  - Run `uv run pytest tests/unit -q` and fix tests that read the old attribute. Fixture code that *constructs* Needs with `ksec_category=` keeps working through the validator.
- [ ] **Step 5: Verify.** `uv run pytest tests/unit -q`, `uv run ruff check src tests` and `uv run mypy src` all pass.
- [ ] **Step 6: Commit** `feat: Need carries multiple KSEC tags and merge links`.

### Task 3: SkillGroup persistence

**Files:**
- Modify: `src/curriculum_agent/models.py` (add `SkillGroup`)
- Modify: `data/orm.py` (add `SkillGroupTable`)
- Modify: `data/repositories.py` (add `SkillGroupRepository`)
- Modify: `data/program_copy.py`: copy `skill_groups`. Its `group_id` is a global key, so it is minted fresh and remapped like `need_id`.
- Modify: `ProgramRepository.delete_cascade`: delete skill_groups before skills.
- Create: `migrations/versions/<rev>_skill_groups.py`
- Test: `tests/unit/test_skill_group_repository.py` (pure model and copy-build tests, in the style of `test_program_copy_build.py`)

**Interfaces:**
- Produces `SkillGroup(BaseModel)`. Its fields are today's `need_combination._Group` fields plus `group_id: str`, `program_id: str` and `is_graduate: bool`:
  - `ksec: KSECCategory`
  - `skill_ids`
  - `evidence_ids`
  - `skill_names`
  - `skill_frequencies`
  - `bloom_level`
  - `demand_score`
  - `is_optional`
  - `classification_coverage`
  - `stakeholder_coverage`
  - `stakeholder_types`
  - `in_field_skill_count`
  - `graduate_capability_skill_count`
- Produces `SkillGroupRepository` with these methods:
  - `delete_by_program(program_id) -> int`
  - `bulk_insert(groups: list[SkillGroup]) -> None`
  - `list_by_program(program_id) -> list[SkillGroup]`: the stored order is preserved, using an `ordinal` Integer column set at insert.

- [ ] **Step 1: Write failing tests:**
  - `test_skill_group_round_trips_through_json`
  - `test_copy_build_remaps_skill_group_ids`: a copied program's group `skill_ids` point at the copy's new skill ids, and `group_id` is fresh.
  - `test_delete_cascade_lists_skill_groups_before_skills`: inspect the statement order, the way the existing cascade test does, if one exists. Otherwise assert on the table list the function uses.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement the model, table, migration, repository, copy and cascade.**
- [ ] **Step 4: Run** `uv run pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: persist skill groups between the two agents`.

### Task 4: Agent 1 clusters; Agent 2 writes from stored groups, concurrently

**Files:**
- Create: `src/curriculum_agent/stages/skill_grouping.py`
- Modify: `src/curriculum_agent/stages/need_combination.py`:
  - move `_build_groups` and its docstring out
  - `run` reads groups
  - sentence calls go through `gather_bounded`
- Modify: `src/curriculum_agent/graph.py`: add a `skill_grouping` node between `skill_extraction` and `need_combination`; add `skill_groups: list[dict]` to `AgentState`.
- Test: `tests/unit/test_skill_grouping_stage.py` (new). Move the clustering-population tests' imports in `test_clustering_populations.py` and `test_cluster_budget.py` to the new module.

**Interfaces:**
- Consumes: `SkillGroup` and `SkillGroupRepository` (Task 3).
- Produces: `skill_grouping.build_skill_groups(program_id: str, skills: list[ExtractedSkill], stakeholder_type_by_evidence: dict[str, str], program_context: str | None) -> list[SkillGroup]`. This is today's `_build_groups` body, with `group_id=str(uuid4())`, the `is_graduate` side and `program_id` set.
- Produces: `skill_grouping.run(state) -> AgentState`.
  - Input follows the "None = load, [] = refuse" rule: `state["extracted_skills"]` is None, so load from `SkillRepository`; it is `[]`, so raise before deleting.
  - It replaces the stored groups and sets `state["skill_groups"]`.
- Produces: `need_combination.run(state)` reads `state["skill_groups"]` (None loads from `SkillGroupRepository`; `[]` or none stored raises `ValueError` with Thai text `"ยังไม่มีกลุ่มทักษะสำหรับโปรแกรมนี้ กรุณารันขั้นสกัดทักษะใหม่ก่อนรวมเป็น Need"`).
- Produces: one Need per group. Statement calls run through `gather_bounded(settings.llm_max_concurrency, ...)`. Need order follows group order.

- [ ] **Step 1: Write failing tests:**
  - `test_grouping_never_mixes_buckets`: with the clustering call stubbed, every group's member skills share one bucket.
  - `test_grouping_refuses_empty_skill_list_before_delete`
  - `test_need_combination_reads_stored_groups_without_clustering`: patch `cluster_skill_names` to raise, so the run still produces one Need per group.
  - `test_need_combination_refuses_when_no_groups`: asserts the Thai message.
  - `test_statement_calls_run_concurrently`: a stubbed `complete_need_combination` records the maximum number of in-flight calls, which must be > 1 with 3 groups and `llm_max_concurrency>=2`. Output order equals group order.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Move the clustering, keeping the existing log lines.
  - Wire the graph node.
  - Update `test_graph_hitl.py` and `test_stage_preconditions.py` for the new node.
- [ ] **Step 4: Run** `uv run pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor: clustering moves to Agent 1, Need sentences written concurrently`.

### Task 5: Dedup and merge at Agent 2

**Files:**
- Modify: `stages/need_dedup.py`:
  - `MAX_GROUP_SIZE = 5`
  - delete the KSEC rejection
  - prompt rows carry `ksec_label`
- Modify: `prompts/need_dedup.py`: the rules text becomes 2-5 members, any KSEC.
- Create: `stages/need_merge.py`
- Create: `prompts/merged_need.py`
- Modify: `stages/need_combination.py`: call merge before persisting.
- Modify: `plo_synthesis.py`:
  - move `enforce_merge_floor`, `build_units`, `core_slot_count` and `_core_members` into `need_merge.py`, adapted to Needs
  - delete `FoldGroup` use
- Test: `tests/unit/test_need_merge.py` (new); update `test_need_dedup.py` and `test_need_dedup_prompt.py`.

**Interfaces:**
- Consumes: `find_duplicate_groups(needs, metadata) -> list[FoldGroup]` (unchanged signature).
- Produces in `need_merge.py`:
  - `TOP_SKILL_CAP = 7`
  - `rank_top_skills(skills: list[ExtractedSkill]) -> list[ExtractedSkill]`:
    - collapse by `normalize_need_name`, keeping the max `importance_score`
    - sort by `(-importance_score, normalized name)`
    - cut to `TOP_SKILL_CAP`
  - `enforce_merge_floor(needs: list[Need], folds: Sequence[FoldGroup]) -> list[FoldGroup]`: same rule and order as today's version in `plo_synthesis`.
  - `async def merge_duplicates(program_id: str, needs: list[Need], skills: list[ExtractedSkill], metadata: ProgramMetadata, stakeholder_type_by_evidence: dict[str, str]) -> list[Need]`. It returns the full list to store:
    - originals, with `merged_into` set where merged
    - plus one new merged Need per surviving fold
  - Only Needs that are `is_in_scope` and not `is_unwritten_need` are offered to dedup.
- Produces in `prompts/merged_need.py`: `build_merged_need_prompt(top_skill_names: list[str], ksec_tags: list[str], bloom_level: str, reason_th: str, *, program_context: str | None) -> list[dict[str, str]]`.
  - It reuses the Need-sentence rules from `build_summarize_need_prompt`. Factor the shared rule text into a module-level constant there rather than copying it.
  - The answer validates as `need_combination._NeedStatement`. Make that class importable as `NeedStatement`.

**Merged Need fields** (§2.5): recompute from the pooled member skills with `compute_demand_score`, `classification_coverage`, `is_optional_group`, `group_bloom`, stakeholder coverage and the in-field/graduate counts, exactly as `build_skill_groups` computes them for a group.
- `freq = len(member_skill_ids)`
- `merged_from` is in demand order
- `merge_reason_th = fold.reason_th`
- `top_skill_ids` are the ranked ids

- [ ] **Step 1: Write failing tests** in `test_need_merge.py`, with dedup and sentence calls stubbed:
  - `test_merged_need_trail_is_union_of_originals` (member_skill_ids, source_evidence_ids)
  - `test_merged_need_tags_are_union_in_ksec_order`: K + S gives `[K, S]`
  - `test_top_skills_capped_at_seven_by_importance`
  - `test_duplicate_skill_name_keeps_higher_score`
  - `test_originals_marked_merged_into_not_deleted`
  - `test_out_of_scope_and_unwritten_needs_never_offered`: the stub records its input
  - `test_group_of_five_accepted_six_dropped` (in `test_need_dedup.py`)
  - `test_mixed_ksec_group_accepted` (in `test_need_dedup.py`)
  - `test_failed_merged_sentence_leaves_group_unmerged`: the stub raises, the originals have `merged_into is None`, and no merged row exists
  - `test_merge_floor_unfolds_lowest_demand_first`: port the existing floor test from `test_plo_synthesis_dedup.py`
  - `test_dedup_switched_off_merges_nothing`: `need_dedup_provider=""`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `need_merge.py` and the prompt builder. Call `merge_duplicates` in `need_combination.run` after the sentences are written and before `delete_by_program` / `bulk_insert`. The core-count warning counts active Needs only.
- [ ] **Step 4: Run** `uv run pytest tests/unit -q` and `uv run python scripts/dump_prompts.py` (regenerate the inventory). Then run `uv run python scripts/dump_prompts.py --check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: Agent 2 merges duplicate Needs into one multi-tag Need`.

### Task 6: Downstream reads active Needs; plo_synthesis stops folding

**Files:**
- Modify: `stages/plo_synthesis.py`:
  - remove the dedup and fold path at ~L616-635 and the `need_dedup` import
  - each unit is one Need
  - the stored-Needs load uses `list_active_by_program`
- Modify: every `NeedRepository().list_by_program` call site except `GET /needs/` and the trace route:
  - `api/routes/plos.py:88,153,198,286,326,383,572,646`
  - `stages/plo_report.py:33`
  - `stages/plo_review.py:262,375`
  - `data/repositories.py:66`
- Modify: `api/routes/plos.py` from-needs. A selected Need whose `merged_into` is set answers 422 `"Need นี้ถูกรวมเข้ากับ Need อื่นแล้ว — เลือก Need ที่รวมแล้วแทน"`.
- Delete or replace: `tests/unit/test_plo_synthesis_dedup.py`.
- Test: `tests/unit/test_active_needs_downstream.py` (new).

**Interfaces:**
- Consumes: `list_active_by_program` (Task 2).

- [ ] **Step 1: Write failing tests:**
  - `test_synthesis_one_slot_per_active_need`: three active Needs plus two merged-away originals gives three slots, and no originals are cited.
  - `test_synthesis_makes_no_dedup_call`: patch `complete_need_dedup` to raise, and synthesis still succeeds.
  - `test_from_needs_refuses_merged_away_need`: 422 with the Thai text.
  - `test_report_unused_needs_exclude_merged_away`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Leave `graph.py` alone; Task 7 adds the checkpoint reload.
- [ ] **Step 4: Run** `uv run pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor: PLO stages read active Needs and no longer fold`.

### Task 7: Split route and checkpoint reload

**Files:**
- Modify: `api/routes/needs.py`: add the split route; `GET /needs/` gains `active_only: bool = False`.
- Modify: `graph.py`: after `interrupt` returns, `review_needs` reloads `state["needs"]` from `list_active_by_program` before returning.
- Test: `tests/unit/test_need_split.py` (new); extend `tests/unit/test_graph_hitl.py`.

**Interfaces:**
- Consumes: `NeedRepository.split` (Task 2) and `sync_writer` (`api/jobs.py`).
- Produces: `POST /programs/{program_id}/needs/{need_id}/split -> list[Need]`. Refusals, in this order:

  | Status | When | Thai detail |
  |---|---|---|
  | 404 | Need unknown | `"ไม่พบ Need นี้"` |
  | 422 | not merged | `"Need นี้ไม่ได้มาจากการรวม จึงแยกไม่ได้"` |
  | 409 | a PLO cites it | `"Need นี้ถูกใช้สร้าง PLO แล้ว — แยกก่อนสร้าง PLO หรือรันสังเคราะห์ PLO ใหม่หลังแยก"` |
  | 409 | program busy | busy text from `program_busy` |

- [ ] **Step 1: Write failing tests:**
  - `test_split_restores_originals_and_deletes_merged`
  - `test_split_refused_when_plo_cites_it`
  - `test_split_refused_for_unmerged_need`
  - `test_split_refused_while_job_running`
  - `test_list_needs_active_only_hides_originals`
  - `test_review_needs_reloads_active_needs_on_resume`: state holds a merged Need, storage holds the restored originals; after the node, `state["needs"]` holds the originals.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Register the route under the existing needs router prefix. Add it to the busy-guard list documented in `.claude/rules/api-data.md` (Task 11 writes the docs).
- [ ] **Step 4: Run** `uv run pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: split a merged Need back at the Need checkpoint`.

### Task 8: Two chained jobs

**Files:**
- Modify: `api/jobs.py`: add `start_job(..., on_success: Callable[[], Awaitable[None]] | None = None)` and the same keyword on `start_job_or_409`. `_run` awaits it after recording `succeeded`, and logs any exception from it at ERROR without changing the finished job.
- Modify: `api/routes/needs.py`:
  - `POST /needs/run` starts a `skill_extraction` job running Agent 1 (`skill_extraction.run`, then `skill_grouping.run`, each under `asyncio.wait_for(..., 300)`), with `on_success` starting the `need_combination` job.
  - `/needs/skills/run` runs Agent 1 with no chain.
  - `/needs/combine/run` requires stored skill groups. Without them it answers 422 `"ยังไม่มีกลุ่มทักษะ กรุณารันสกัดทักษะใหม่ก่อน"`. The old skills-only precondition text stays for the no-skills case.
- Modify: `models.JobKind`: keep `needs_pipeline` for old rows; no new kind.
- Test: extend `tests/unit/test_needs_jobs.py` and `tests/unit/test_job_runner.py`.

**Interfaces:**
- Consumes: `skill_grouping.run` (Task 4).

- [ ] **Step 1: Write failing tests:**
  - `test_needs_run_chains_need_combination_after_skill_job`: after `spawned.drain()`, two job rows exist, `skill_extraction` then `need_combination`, both succeeded.
  - `test_skills_run_does_not_chain`
  - `test_agent2_failure_keeps_agent1_output_and_old_needs`: Agent 2's stub raises. The skill job succeeded, the need job failed with an `error_th`, and the stored Needs are unchanged.
  - `test_on_success_not_called_on_failure`
  - `test_on_success_exception_does_not_flip_job_status`
  - `test_combine_run_422_without_groups`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: Agent 1 and Agent 2 run as two chained jobs`.

### Task 9: `need_analysis` rail stage (backend)

**Files:**
- Modify: `graph.py`:
  - `DESIGNER_STAGES` inserts `"need_analysis"` after `"skill_extraction"`
  - `REVIEW_NODE_STAGE["review_needs_node"] = "need_analysis"`
  - `stage_reached` returns `"need_analysis"` when `has_needs`, `"skill_extraction"` when only `has_skills`
- Test: update `tests/unit/test_session_stage_mapping.py` and `tests/unit/test_stage_reached.py`.

- [ ] **Step 1: Update the tests** to the new mapping:
  - `stage_reached(has_evidence=True, has_skills=True, has_needs=True, has_plos=False) == "need_analysis"`
  - `stage_reached(..., has_skills=True, has_needs=False, ...) == "skill_extraction"`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Grep the API for other users of `DESIGNER_STAGES` and stage strings (`api/routes/programs.py`, sessions) and keep them consistent.
- [ ] **Step 4: Run** `uv run pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: Need analysis gets its own designer stage`.

### Task 10: Frontend: two pages, merged Need card, multi-tag KSEC

**Files:**
- Modify: `frontend/src/constants/stages.ts`:
  - `skill_extraction` becomes ordinal 3, label `"สกัดทักษะ"`, summary `"อ่านหลักฐานเป็นทักษะ แล้วจัดกลุ่มตาม KSEC"`, no `engineStages` and no `gateNote`
  - new `need_analysis` at route `/need-analysis`, ordinal 4, label `"วิเคราะห์ Need"`, summary `"รวมกลุ่มทักษะเป็น Need และรวม Need ที่ซ้ำกัน"`, `gateNote: "ตรวจและอนุมัติที่ขั้นนี้"`
  - later stages shift +1
  - the top comment is rewritten
- Modify: `App.tsx`: add the route.
- Modify: `api/jobs.ts`: `JOB_PAGE.need_combination = '/need-analysis'`.
- Modify: `pages/Pipeline.tsx`: suspended-stage copy for `need_analysis`.
- Modify: `pages/PloReport.tsx` and `PloReview.tsx`: their stage key lists.
- Create: `frontend/src/pages/NeedAnalysis.tsx`. This is the Need part of `SkillExtraction.tsx` moved over:
  - the Need cards
  - the combine re-run with the designer note
  - the `need_combination` job status
- Modify: `pages/SkillExtraction.tsx`: keep skills and the extraction re-run; add skill groups per KSEC bucket (needs `GET /needs/skill-groups`, see below); keep the stale-Needs banner; add a link to `/need-analysis`; watch only `needs_pipeline` and `skill_extraction`; show a notice when a `need_combination` job is running.
- Modify: `pages/components/NeedCard.tsx`, merged variant:
  - `"รวมจาก N ข้อ"` badge
  - every KSEC tag
  - top-skill chips
  - the merge reason, labelled `"เหตุผลของโมเดล"`
  - an expandable list of original statements (from `GET /needs/` with `active_only=false`, matched on `merged_into`)
  - a `"แยกกลับ"` button calling the split route; a 409/422 `detail` shows in the page's error notice
- Modify: everything that reads `ksec_category` on a Need: `PloReport.tsx`, `PloReview.tsx`, `PloSynthesis.tsx`, `types/ploReview.ts`, `mock/db.ts`, `mock/handlers.ts`, `mock/scenarios.ts`. The mocks get the split route and one merged Need scenario.
- Backend addition in this task: `GET /programs/{id}/needs/skill-groups -> list[SkillGroup]` in `api/routes/needs.py`, plus `test_list_skill_groups_route` in `tests/unit/test_needs_router.py`.

**Interfaces:**
- Consumes: `Need` JSON fields from Task 2, the split route from Task 7, and job kinds from Task 8.
- UI rules: use component classes in `index.css` (`frontend-visual-identity`): the stamp/mandate/marker inks and the ● ◐ ○ rail. No Tailwind palette classes.

- [ ] **Step 1: Backend route test, then the route.** `uv run pytest tests/unit/test_needs_router.py -q` passes.
- [ ] **Step 2: Implement the pages, card, stages, routes and mocks.**
- [ ] **Step 3: Verify.** `npm --prefix frontend run build` and `npm --prefix frontend run lint` both exit 0.
- [ ] **Step 4: Manual check in mock mode** (`npm --prefix frontend run dev:mock`):
  - the rail shows 7 stages
  - `/skill-extraction` shows no Need cards
  - `/need-analysis` shows the merged card with two tags, and clicking "แยกกลับ" in the mock restores two cards
  - Record what was checked in the commit body.
- [ ] **Step 5: Commit** `feat(ui): separate skill and Need pages, merged Need card`.

### Task 11: Docs and rules

**Files:**
- Modify: `CLAUDE.md`. Update the stack/LLM paragraph and immutable rules 6 and 7, and replace the "Never merge or cluster skills across a KSEC bucket" pitfall. State that this branch relaxes them by the designer's decision of 2026-10-26.
  - **LLM paragraph:** the `PIPELINE_*` switch.
  - **Rule 6:** one active Need gives one PLO. Merging happens at Agent 2: up to 5 Needs, across KSEC, with the originals kept and splittable.
  - **Rule 7:** checkpoints at evidence, Need and PLO. Agents 1 and 2 are two chained jobs with no checkpoint between them.
  - **The pitfall becomes:** clustering stays in-bucket; only Agent 2's merge produces multi-tag Needs.
  - Leave the other rules intact.
- Modify: `.claude/rules/need-pipeline.md`. Rewrite the dedup paragraph (Agent 2, max 5, cross-KSEC, merged Need construction, active vs merged, split).
- Modify: `.claude/rules/llm-slots.md`: the precedence order with `PIPELINE_*`.
- Modify: `.claude/rules/api-data.md`:
  - the split route in the busy-guard list
  - `on_success` chaining
  - `skill_groups` in program copy and cascade
- Modify: `.claude/skills/curriculum-design-agent/references/data-schemas.md`: the `Need` and `SkillGroup` shapes.
- Verify: `uv run python scripts/dump_prompts.py --check` passes.

- [ ] **Step 1: Edit the docs.**
- [ ] **Step 2: Run** `uv run python scripts/dump_prompts.py --check` and `uv run pytest tests/unit -q`. Expected: PASS.
- [ ] **Step 3: Commit** `docs: describe the four-agent pipeline phase 1`.

### Task 12: Measurement

Timing needs live services and LLM keys. The controller runs this, not a subagent.

- [ ] **Step 1: Check that the services are up.** Run `.\scripts\start-services.ps1`, then `.\scripts\start-backend.ps1`, and confirm a program holding the largest available corpus exists (the TCISM set, if loaded). If neither is available, record "not measured: <reason>" in the report and stop.
- [ ] **Step 2: Run `POST /needs/run` on that program.** Read the backend log for the per-agent durations, the dedup line (groups proposed, accepted, unfolded) and the multi-tag Need count.
- [ ] **Step 2b: Before figure (optional).** For a before figure, check out the commit before Task 4 in a separate worktree and repeat Step 2 there. Otherwise record that only the after figure exists.
- [ ] **Step 3: Record the results** in `.scratch/reports/2026-10-26-phase1-timing.md`. Commit only if `.scratch/reports` is tracked; otherwise leave the file in place and report it.
