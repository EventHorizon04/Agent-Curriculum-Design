# Four-agent pipeline, phase 1: split the Need stage, dedup at the Need stage, one model switch

Date: 2026-10-26. Branch: `feat/four-agent-pipeline` (cut from `main` the same day).
Status: design agreed in chat; spec under review.

This branch is the new primary line for the service and for research. `main`
keeps the current pipeline untouched for possible later use, so nothing here
is merged back into `main`.

## Why

The designer reorganised the pipeline around four agents:

| Agent | Job | Today |
|---|---|---|
| 1 Skill extract | extract skills, cluster them inside each KSEC bucket | extraction in `skill_extraction`; clustering runs inside `need_combination._build_groups` |
| 2 Need analyze | write one Need per skill group, find and merge duplicate Needs | sentence writing in `need_combination`; `need_dedup` runs at the **start of `plo_synthesis`** |
| 3 PLO synthesis | one PLO per Need, SMART validation | `plo_synthesis` + validation agent |
| 4 PLO review | review the finished set | `plo_review` (advisory only) |

Phase 1 is the restructuring the other phases depend on. Three problems drive it:

1. **The skill → Need run dies on large inputs.** `POST /needs/run` runs
   `skill_extraction` and `need_combination` back to back in one job
   (`api/routes/needs.py:run_need_pipeline`). With many stakeholders or many
   skills it runs past its time budget or fails, and the designer re-runs the
   whole thing. Where exactly it dies has not been measured. One visible cause:
   `need_combination.run` writes each Need sentence in a sequential
   `for group in groups: await ...` loop.
2. **Duplicate Needs are folded invisibly.** `need_dedup` folds Needs into one
   PLO slot inside `plo_synthesis`. The designer never sees which Needs were
   judged the same, can't undo it, and the Need list shows them as separate.
3. **Research needs one model across the pipeline.** Seven slots with
   different default models make a run hard to compare with another one.

## Decisions (the designer's)

1. **Two jobs, no checkpoint between them.** Agent 1 (extract + cluster) and
   Agent 2 (write Needs + dedup) are separate jobs. Each stores its output
   before the next starts and has its own time budget. Agent 1 finishing
   starts Agent 2 automatically. If Agent 2 fails, it can be re-run alone from
   Agent 1's stored output, without re-extracting. The designer reviews only
   at the Need checkpoint, as today.
2. **Clustering moves to Agent 1.** Clustering still runs per KSEC bucket
   (K, S, EC), never across buckets.
3. **Dedup moves to Agent 2 and merges automatically.** Needs that ask for the
   same capability become **one new Need**. The designer does not confirm each
   merge.
4. **How a merged Need is written:**
   - Pool the member skills of every Need in the group.
   - When the same skill appears more than once (from different evidence
     items, with different demand), keep the higher score.
   - Rank the pooled skills by demand and take the **top 5-7**.
   - Write a new Need sentence from those top skills.
   - Store the top skills on the Need as its skill tags.
   - The evidence trail stays complete: every evidence item behind every
     original Need.
5. **A merged Need may carry more than one KSEC tag.** Multi-tag Needs arise
   **only** from dedup merging. Clustering stays inside one bucket, so an
   unmerged Need still has exactly one tag.
6. **A dedup group may hold up to 5 Needs** (was 3).
7. **The designer can split a merged Need back** at the Need checkpoint. Split
   deletes the merged Need, and the original Needs become usable again exactly
   as they were.
8. **One model switch for the whole pipeline.** Phase 1 builds only the
   mechanism. Which model to use is decided later, from measurements, after the
   pipeline work. Until then, every slot keeps its current default.
9. **The immutable rules in CLAUDE.md are relaxed** where they conflict with
   this design (rule 6 grouping bounds, rule 7 checkpoint list, the
   "never merge across a KSEC bucket" pitfall). CLAUDE.md and the matching
   `.claude/rules/*.md` are rewritten on this branch to describe the new
   behaviour, so the next session doesn't "fix" it back.

## Goals

- `POST /needs/run` survives the corpus that kills it today, or fails in a way
  that keeps Agent 1's output and names which agent failed.
- The designer sees every merged Need: which Needs it came from, why the model
  judged them one capability, and its KSEC tags. They can undo any merge before
  PLOs are drafted from it.
- `plo_synthesis` drafts exactly one PLO per active Need. It does no folding of
  its own.
- Setting one provider and one model in `.env` runs every LLM call in the
  pipeline on that model.

## Non-goals (later phases)

- Manual merge or exclude of Needs by the designer (phase 2).
- Editing evidence (phase 2).
- Any PLO-page UI work: highlighting mergeable Needs, attaching an unused Need
  to a PLO, showing superseded PLOs, the SMART re-check loading state (phase 3).
- Agent 4 changes: new checks, automatic send-back, the trace UI for it (phase 4).
- Batching `need_dedup` / `plo_review` for very large sets, and token
  accounting (phase 5).
- Choosing the single model.
- End-to-end orchestration of the whole run (after the pipeline is tested).

## Anti-goals (would make this a failure even if it runs)

- A merged Need whose trail is smaller than the union of its originals'
  trails. Immutable rule 2 still holds in spirit: every PLO traces to evidence.
- An original Need that disappears, so that a split cannot restore it.
- With the new pipeline-model settings unset, any slot resolving to a
  different provider or model than it does on `main` today.
- Clustering that mixes KSEC buckets. Broad cross-bucket groups give broad
  Needs, and those give PLOs that fail SMART-S. Multi-tag is for merges only.

## Design

### 1. Agent 1 job: extract + cluster

- `skill_extraction` keeps its job.
- The clustering half of `need_combination._build_groups` moves here: bucket
  by KSEC, split graduate/institutional, dedupe names, allocate cluster
  targets, cluster.
- The resulting **skill groups are persisted**, so Agent 2 starts from them
  without calling the clustering slot. A group carries:
  - KSEC bucket and resolved tag
  - member skill ids
  - Bloom level (`group_bloom`)
  - skill frequencies
  - the graduate/institutional side
- **Storage shape is the builder's call.** Either a `skill_groups` table, or
  a group id on skill rows plus the group-level fields elsewhere. It goes
  through an Alembic migration and a repository class.
- Re-running Agent 1 replaces the program's skills and groups, as skill
  extraction replaces skills today.

### 2. Agent 2 job: write Needs, dedup, merge

1. **Write one Need per stored skill group**, exactly as `need_combination`
   does today: `_NeedStatement`, fallback markers, rationale, demand score,
   optional rule.
   - **Builder's call (mine):** run the sentence calls concurrently, bounded
     by `settings.llm_max_concurrency` (`gather_bounded`, as `plo_synthesis`
     does). Keep output order stable, in group order. This is the cheapest fix
     for the timeout in problem 1.
2. **Dedup.** One call to the `need_dedup` slot.
   - **Input:** the Needs that are written (not `is_unwritten_need`) and in
     scope (`is_in_scope`), in demand order.
   - **My call:** out-of-scope and unwritten Needs are never merged.
     `plo_synthesis` drops them anyway, and merging one into an in-scope Need
     would smuggle it past the scope filter.
3. **Accept groups** with the existing `accept_groups` discipline, changed as
   follows:
   - Drop the "members span more than one KSEC tag" rejection.
   - Raise `MAX_GROUP_SIZE` to 5.
   - Unchanged: fewer than two known members, a member already taken (the
     first group wins), and a rule-breaking group dropped whole, never trimmed.
4. **Merge floor.** Keep `enforce_merge_floor`'s rule, moved from
   `plo_synthesis` to this stage: merging may not take the core Need count
   below `MIN_CORE_AFTER_MERGE` (4) unless the set was already below it.
   Groups are unfolded lowest-demand first, as today.
5. **Build the merged Need** for each kept group:
   - **Pooled skills:** the union of the members' `member_skill_ids`. Skill
     rows sharing a normalised name collapse to the one with the highest
     `importance_score`. In today's code rows that share a name always carry
     the same score, because `_compute_skill_importance` works per normalised
     name across the program. "Keep the higher score" is therefore a guard,
     not a branch that currently fires.
   - **Top skills:** the pooled skills sorted by `importance_score`, highest
     first, ties broken by name. Take 7 when at least 7 exist, otherwise all
     of them. ("5-7" is the designer's range; 7 as the cap is my call.)
   - **Sentence:** one `need_combination`-slot call, written from the top
     skills' names with the same Need-sentence rules (`_NeedStatement`). The
     prompt also receives the dedup `reason_th`. Add a builder function in
     `prompts/` for it, or extend `build_summarize_need_prompt`.
   - **`top_skill_ids`** (new field): the ids of the top skills, in rank order.
     These are the Need's skill tags.
   - **`member_skill_ids`, `source_evidence_ids`:** the union over all
     originals. The trail is complete, not just the top skills.
   - **`ksec_categories`:** the sorted union of the originals' tags, in
     K, S, E, C order.
   - **`bloom_level`:** `group_bloom` over the pooled skills (the existing rule).
   - **`demand_score`, `is_optional`, `stakeholder_coverage`,
     `source_stakeholder_types`, `freq`, `classification_coverage`, in-field
     and graduate counts:** recomputed from the pooled skills with the same
     functions `need_combination` uses (`compute_demand_score`,
     `is_optional_group`, …). **My call:** the score is recomputed, not taken
     as the max of the originals. A capability asked for by more voices should
     rank higher.
   - **`merged_from`** (new field): the original need ids, in demand order.
   - **`merge_reason_th`** (new field): the dedup reason.
6. **If writing a merged Need's sentence fails, that group is not merged.**
   The originals stay active and the failure is logged. This is my call, and
   it matches the existing "the step can only fold" rule: a failure never
   costs a Need and never ships a `[ต้องทบทวน]` merged Need.
7. **Persist:**
   - Store the originals with `merged_into = <merged need id>`.
   - Store merged Needs as ordinary rows with `merged_from` set.
   - Run the same delete-then-insert replacement as today.
   - The refusal-before-delete guards stay as they are.

### 3. Active vs merged Needs

- **Active Needs:** Needs with `merged_into` empty. Every downstream reader
  works on active Needs only:
  - `plo_synthesis`
  - `plo_report` (unused-Need list)
  - `plo_review` facts
  - `POST /plos/from-needs`
  - the Excel exporter
  - the SMART agent's tools
  - `cited_need_ids`
  - core/optional counts at the Need checkpoint
- **Repository:** add one active-only read to the repository and use it
  everywhere. No call site should filter by hand.
- **`GET /needs/`** returns all Needs with the new fields, so the UI can show
  originals under their merged Need. **Builder's call:** add an `active_only`
  flag or a separate route.
- **Program copy (`data/program_copy.py`):** `remap_ids` must rewrite
  `merged_into` and `merged_from` along with the other id references.

### 4. Split a merged Need

- **Route:** `POST /programs/{program_id}/needs/{need_id}/split`.
- **Refusals:**
  - 404: the Need is unknown.
  - 422: the Need is not a merged Need.
  - 409: a stored PLO cites it. The Thai message says to re-run PLO synthesis
    after splitting, or to split before drafting PLOs.
  - 409: the program is busy (same busy rule as the other synchronous writers,
    `sync_writer` / `program_lock`).
- **Effect, in one transaction:** delete the merged Need and clear
  `merged_into` on its originals.
- **Returns:** the restored originals.
- **No re-merge.** Re-running Agent 2 is how the designer gets fresh merges.
- **Graph path.** A session paused at `review_needs_node` holds
  `state["needs"]` from before the split. Resuming with it would draft from a
  deleted Need.
  - **My call:** when `review_needs` resumes, it reloads `state["needs"]` from
    the active-only repository read before returning.
  - The stages' "None = load, [] = refuse" input rule is unchanged. The
    checkpoint node is where the designer's edits are folded back into
    state, so phase 2's Need edits will flow through the same way.
  - A split is not refused while a session is paused there.
- **`POST /plos/from-needs`** answers 422 in Thai when a selected Need has
  been merged away.

### 5. Multi-tag KSEC on a Need

- **Model:** `Need.ksec_category: KSECCategory` becomes
  `Need.ksec_categories: list[KSECCategory]`, with at least one entry, no
  duplicates, in K, S, E, C order.
- **Migration:** add the new column, backfill it as `[ksec_category]`, then
  drop the old column. Checkpoint dicts with the old key must still validate
  (`mode="before"` validator mapping `ksec_category` → `[ksec_category]`),
  following the pattern `Need` already uses for checkpoint-era dicts.
- **Consumers to update:**
  - `exporters/excel_matrix.py`
  - `prompts/stage_3_plo.py`: show all tags
  - `prompts/plo_review.py`
  - `stages/plo_review_facts.py`: coverage counts a multi-tag Need under every
    tag it carries
  - `stages/smart_agent_tools.py`
  - `prompts/need_dedup.py` input
  - frontend `NeedCard`, `PloReport`, `PloReview`, `PloSynthesis`,
    `types/ploReview.ts`, and the mocks
- `ExtractedSkill.ksec_category` stays single-valued.

### 6. `plo_synthesis` stops folding

- Remove the `find_duplicate_groups` / `enforce_merge_floor` / fold path.
- Every active, in-scope, written Need is its own unit.
- The scope filter, unwritten filter, `MAX_CORE_PLOS` ceiling, numbering and
  optional series are unchanged.
- `POST /plos/from-needs` is unchanged apart from reading active Needs.
- The manual merge's group bound is left as it is in phase 1. Aligning it with
  the dedup bound is phase 3 work.

### 7. Graph, jobs and routes

- **Graph:** `skill_extraction → need_combination → review_needs_node`, with
  the clustering moved as above.
- **Two rail stages, two pages (the designer's decision).** Agent 1 and
  Agent 2 each get their own stage on the rail and their own page, so the
  designer sees the data flow from skills to Needs. Only the Need page carries
  the checkpoint. The skill page is a view the run passes through, not a gate.
  - `DESIGNER_STAGES` gains a stage after `skill_extraction`. **My call:** name
    it `need_analysis`, after Agent 2.
  - `REVIEW_NODE_STAGE["review_needs_node"]` becomes `need_analysis`.
  - `stage_reached`: stored Needs answer `need_analysis`, and skills alone
    answer `skill_extraction`.
  - `test_session_stage_mapping.py` and the frontend rail list change with it.
- **Later, not now:** once the pipeline has been tested, the designer plans to
  orchestrate the whole run end to end. Phase 1 does not build toward that
  beyond keeping the two jobs separate and chainable.
- **`POST /needs/run`:** runs Agent 1 as one job. On success it starts Agent 2
  as a second job. Both appear in `GET /jobs`.
- **`/needs/skills/run`:** reruns Agent 1 only and does **not** chain into
  Agent 2. **My call:** the chaining in decision 1 belongs to `POST /needs/run`
  and the graph, not to the Agent 1 job itself. This route exists so the
  designer can read re-extracted skills before the Needs are redrawn (which
  would also undo their splits), and the stale-Needs banner stays.
- **`/needs/combine/run`:** reruns Agent 2 only. It reads stored skill groups
  and answers 422 in Thai when there are none.
- **Time budgets:** each job has its own `asyncio.wait_for` budget. The
  numbers are the builder's call: start at 300 s each and adjust from the
  measurement below.
- **Job kinds:** builder's call (`skill_extraction` / `need_combination`).
  `useReloadOnJobs` on the skill page must reload on either kind.

### 8. One model for the pipeline

- **New settings:** `PIPELINE_PROVIDER` and `PIPELINE_MODEL`.
- **Precedence**, per slot, highest first:
  1. The slot's own `*_PROVIDER` / `*_MODEL`, when set in the environment.
  2. `PIPELINE_PROVIDER` / `PIPELINE_MODEL`, when set.
  3. The slot's current default (field default, then `default_models`, then
     the provider default).
  4. `LLM_PROVIDER`, as the existing fallback.
- **Provider and model resolve as a pair.** `PIPELINE_MODEL` applies only to
  slots whose provider came from `PIPELINE_PROVIDER`.
  - A slot that sets its own `*_PROVIDER` gets its own `*_MODEL`, or that
    provider's default. It never gets `PIPELINE_MODEL`.
  - A slot that sets only `*_MODEL` runs that model on the provider it
    resolves to.
  - This way a model name never reaches an endpoint it wasn't chosen for.
- **Disableable slots:** an explicit empty `*_PROVIDER` still switches off
  `need_dedup`, `validation` and `plo_review`. `PIPELINE_PROVIDER` never
  re-enables a slot that was switched off.
- **Telling explicit env from field defaults:** use `model_fields_set` (or an
  equivalent) so that a provider default declared on the class, such as
  extraction's `"openrouter"`, does not count as set.
- **Both unset:** resolution is byte-for-byte what `main` resolves today.
  Test this per slot.
- **Validation:** `PIPELINE_MODEL` without `PIPELINE_PROVIDER` is a startup
  error, so a model name never goes to the wrong endpoint.
- **Startup log:** keep the line that lists each slot's resolved
  provider/model.
- **Bounded reasoning stays per call site.** For example, `plo_review`'s
  reasoning cap stays as it is.

### 9. UI: the skill page and the Need checkpoint page

- **Skill page (`SkillExtraction.tsx`, Agent 1):**
  - shows the extracted skills and the stored skill groups per KSEC bucket
  - re-run button for extraction (`/needs/skills/run`)
  - the stale-Needs banner
  - no Need cards and no approve action
  - links on to the Need page
- **Need page (new, Agent 2):**
  - the Need cards, the split action, a re-run button for Agent 2
    (`/needs/combine/run`), and the checkpoint
  - moves the Need-related parts out of `SkillExtraction.tsx`
  - the Agent 2 job status
- **Merged Need card:**
  - a badge "รวมจาก N ข้อ"
  - its KSEC tags, more than one possible
  - its top-skill tags
  - the merge reason, labelled as the model's (like `rationale_th`)
  - an expandable list of the original Need statements
  - a "แยกกลับ" button
- **Originals:** not listed as separate active cards while merged.
- **After a split:** the page reloads, and the originals appear as normal cards.
- **Split refused:** show the 409 or 422 `detail` text.
- **Job status:** each page shows its own agent's job while it runs, and says
  so when it fails. The skill page also says when Agent 2 has started.
- Follow `frontend-visual-identity`: component classes in `index.css`, no
  Tailwind palette.

### 10. Docs

Rewrite to match the new behaviour:

- **CLAUDE.md:**
  - stack/LLM paragraph: the pipeline-model switch
  - rule 6: one Need → one PLO; merges happen at the Need stage, up to 5,
    across KSEC
  - rule 7: checkpoints are evidence, Need, PLO; Agents 1 and 2 are two jobs
    with no checkpoint between them
  - the KSEC pitfall: clustering stays in-bucket, dedup may cross buckets
- **`.claude/rules/need-pipeline.md`:** dedup section, multi-tag Needs, the
  active/merged distinction
- **`.claude/rules/llm-slots.md`:** precedence
- **`.claude/rules/api-data.md`:** new route, job chain, copy remap
- **The curriculum-design-agent skill's `references/data-schemas.md`:** the
  `Need` shape
- **Prompt inventory:** `scripts/dump_prompts.py` regenerates
  `docs/prompt-inventory.md`, and `--check` must pass.

## Measurement

- **Before any code change:** time each part of `POST /needs/run` on the
  largest corpus available (the TCISM document set): extraction, clustering
  per bucket, and the Need sentence calls. Record the numbers in the plan or
  a `.scratch/reports/` note.
- **After:** time each agent again on the same corpus.
- **Success:** both jobs finish inside their budgets on that corpus. If one
  still doesn't, the failure names the agent, Agent 1's output survives, and
  the remaining gap goes to phase 5.
- **Dedup:** record how many groups were proposed, accepted and unfolded, and
  how many multi-tag Needs resulted.

## Left to the builder

- The persistence shape for skill groups.
- Job kind names.
- Per-job time budgets.
- Whether `GET /needs/` gets a flag or a sibling route.
- The prompt builder for merged Need sentences.
- Test layout. Validators first, per project convention.

## Calls I made (designer to check)

- Out-of-scope and unwritten Needs are never merged.
- A merged Need's demand score is recomputed from the pooled evidence, not the
  max of its originals.
- The top-skill cap is 7.
- A failed merged-sentence call leaves that group unmerged.
- Split is refused while a PLO cites the merged Need.
- The merge floor (4 core Needs) is kept, now at the Need stage.
- Need sentence calls run concurrently.
- The new rail stage for Agent 2 is named `need_analysis`.
- Only `POST /needs/run` (and the graph) chains Agent 1 into Agent 2.
  `/needs/skills/run` stays extract-only.
- At the Need checkpoint, the graph reloads active Needs from storage when the
  designer approves, so a split made during a paused session takes effect.
- `PIPELINE_MODEL` goes only with `PIPELINE_PROVIDER`. Provider and model are
  never mixed across levels.
