# Four-agent pipeline, phase 2: the designer merges and excludes Needs; evidence locks after extraction

- **Date:** 2026-11-03
- **Branch:** `feat/four-agent-pipeline`
- **Status:** design agreed in chat; spec under review.
- **Builds on:** `2026-10-26-four-agent-pipeline-phase1-design.md`. Phase 1 listed "manual merge or exclude of Needs" and "editing evidence" as phase 2.

## Why

**Needs.** At the Need checkpoint (`need_analysis`) the designer can only *split* a Need that Agent 2 merged. They cannot:
- join two Needs the duplicate check left apart. This happens often since 2026-11-03: the dedup check now merges only what a majority of 5 calls agree on, and borderline pairs are left for the designer on purpose;
- drop a Need they judge should not become a PLO.

**Evidence.** It can be added and deleted, but not edited. And nothing stops a change after extraction. An edit then would leave skills, Needs and PLOs tracing to text that no longer says what they were drawn from.

The base architecture puts the human at the start (metadata and stakeholders) and the end (PLO reviewer). This branch extends it with a Need checkpoint, and phase 2 is what makes that checkpoint useful.

## The designer's decisions (2026-11-03)

1. **Merging.** At the Need page the designer selects Needs and presses "รวม". The selected Needs become one merged Need.
2. **Excluding.** The designer presses "ตัดออก" on a Need, and it is taken out of the set that becomes PLOs.
3. **Editing evidence.**
   - Evidence can be edited only during input, before skill extraction has run.
   - After extraction, nothing can be done to evidence: no edit, no add, no delete.
   - The lock applies at the API, not just the UI.
4. **Changing evidence after extraction.** Copy the program in a new "evidence only" mode, which carries over metadata and evidence and nothing else, and work on the copy.
5. The earlier guesses played back in chat were not corrected and stand:
   - a manual merge uses the same mechanism as Agent 2's automatic merge;
   - the originals are kept and can be split back;
   - a group has 2-5 Needs;
   - exclusion is reversible and nothing is deleted;
   - a Need that a stored PLO cites cannot be merged or excluded.

## Goals

- Merge 2-5 active Needs into one merged Need from the Need page. The merged Need is indistinguishable from an Agent 2 merge, except for who decided it.
- Exclude an active Need and restore it, from the Need page. An excluded Need is invisible to everything downstream of the checkpoint.
- Edit an evidence item's user-entered fields before extraction.
- Refuse every evidence mutation once the program has skills.

## Non-goals

- Editing a Need's sentence by hand.
- Re-merging after a split. Splitting and then merging again already covers this.
- Carrying manual merges or exclusions across an Agent 2 re-run. See below.
- PLO-page work (phase 3), and Agent 4 send-back (phase 4).
- Unlocking evidence in place after extraction. A designer who must change evidence after that point copies the program with the new "evidence only" mode (below) and works on the copy.

## Anti-goals

- **No silent loss of trace.**
  - An excluded or merged-away Need stays stored, with its `source_evidence_ids`, and stays visible on the Need page.
  - Nothing is deleted, except a merged Need that is split, as today.
- **No PLO left citing a Need that has disappeared from the active set.** That is why merging or excluding a cited Need is refused rather than allowed.
- **No evidence change after extraction through any route.** That includes `POST /evidence/` with an existing `evidence_id`, which is an upsert today, and the `classify-stream` rewrite.

## Design

### Need: exclusion

- **Data.**
  - New nullable column `needs.excluded_at` (timestamp, naive UTC like the rest of the DB).
  - The `Need` model gets `excluded_at: datetime | None = None`. The default is required because Needs also arrive as checkpoint dicts.
  - One Alembic migration whose `down_revision` is the current head (`a7c3e91d5b24` at the time of writing; check before writing it).
  - The program copy clones columns, so the field is copied with no extra work.
- **Active means not merged away and not excluded.**
  - `NeedRepository.list_active_by_program` adds `excluded_at IS NULL`.
  - Every downstream reader already goes through it: synthesis, report, review facts, the Excel export, SMART tools, and the graph's `review_needs` reload on resume.
  - The one reader that does not is `POST /plos/from-needs` (`api/routes/plos.py`, `_merge_needs`). It reads all Needs and rejects merged-away ones by hand, so it gets the same treatment for excluded ones: 422, "Need นี้ถูกตัดออกแล้ว — คืน Need ก่อนนำมารวมเป็น PLO".
- **Routes** (both in `api/routes/needs.py`, both under `sync_writer`, both returning the updated `Need`):
  - `POST /programs/{id}/needs/{need_id}/exclude`
  - `POST /programs/{id}/needs/{need_id}/restore`
  - Refusals, all with Thai detail:
    - 404: unknown Need.
    - 422: the Need is merged away (exclude its merged Need instead).
    - 422: excluding an already excluded Need, or restoring one that is not excluded.
    - 409: a stored PLO cites the Need (`plos_citing`).
    - 409: the program is busy.
  - Restoring has no PLO check, because restoring cannot strand a citation.
- **A merged Need can be excluded.** The whole merged capability then drops out, and its originals stay merged into it.
- **Counts.** `stage_reached` / `has_needs` and the checkpoint's core and optional counts read active Needs, so an excluded Need stops counting.
  - A program where every Need is excluded has no active Needs. The existing preconditions (synthesis refuses with 422 when there are no Needs) answer that case, and nothing new is needed.
  - A core count below 6 is the existing policy warning, not a refusal. The designer is choosing.

### Need: manual merge

- **Route.** `POST /programs/{id}/needs/merge`, body `{need_ids: list[str], reason_th: str | None}`, returns the new merged `Need`. It runs under `sync_writer`, so a job, a session or another writer gets 409 while it runs.
- **Checks, in order, before any LLM call** (all 422 unless stated, all with Thai detail):
  1. 2 to 5 distinct ids (`MAX_GROUP_SIZE`).
  2. Every id exists in the program; otherwise 404-style 422 "ไม่พบ Need: …", as in `from-needs`.
  3. Every Need is active: not merged away, not excluded.
  4. No selected Need is unwritten (`is_unwritten_need`). Same reason and text style as `from-needs`.
  5. No selected Need is cited by a stored PLO: **409**.
  6. **Merge floor.** If the merge would take the core-Need count below `MIN_CORE_AFTER_MERGE` (4), and the count is not already below it, refuse. This is the same rule as `need_merge.enforce_merge_floor` and `from-needs`.
- **Scope is not checked.** Selecting an out-of-scope Need is a designer override, as in `from-needs`: allowed, and logged.
- **Building the merge.**
  - Build a `FoldGroup` from the selected Needs in demand order.
  - Its `reason_th` is the designer's reason, or the fallback "ผู้ออกแบบหลักสูตรเลือกรวม Need เหล่านี้" when none is given.
  - Call `need_merge._write_merged` with the same inputs `merge_duplicates` builds:
    - skills keyed by id;
    - the evidence-to-stakeholder-type map;
    - the program context line.
  - `_write_merged` makes one `need_combination`-slot LLM call, with the existing output and reasoning caps.
- **If the sentence call fails** (`_write_merged` returns `None`), nothing is written. Answer **502**: "เขียนประโยค Need ที่รวมแล้วไม่สำเร็จ ลองใหม่อีกครั้ง". This differs from Agent 2, which leaves a group unmerged silently, because here a person is waiting for the answer.
- **Writing.** In one transaction, set `merged_into` on the selected Needs and insert the merged Need. Factor the "set `merged_into` on the originals" logic out of `merge_duplicates` so both paths share it.
- **Merging a Need that is itself merged: nest, don't flatten.**
  - The selected merged Need is one member like any other. Its `merged_into` points to the new Need, and it keeps its own `merged_from`, `merged_by` and reason.
  - Splitting the new Need restores the selected Needs, the inner merged Need among them. Splitting that one again restores its originals.
  - This keeps the anti-goal, since nothing is deleted but a split merged Need, and it keeps who decided each step.
  - `_write_merged` pools `member_skill_ids`, which a merged Need already holds as a union, so nothing changes there.
  - The UI's originals disclosure shows a nested merged Need with its own disclosure.
  - The 2-5 bound applies to the designer's selection.
  - *This is the controller's call*, after the builder check found that flattening deleted a trail.
- **Core/optional and KSEC of the merged Need** are recomputed by `_write_merged`, as for Agent 2:
  - `score_members` gives `is_optional`;
  - `ksec_categories` is the sorted union.
- **The floor check runs before the LLM call**, so it uses the worst case: projected core = current core − selected core + (1 if any selected Need is core, else 0).
  - Pooled evidence is never smaller than a member's, so a merge that includes a core member stays core.
  - A merge of optional Needs alone can only keep or raise the core count.
- **Split rules for the new cases.**
  - Splitting an **excluded** merged Need is refused (422, "คืน Need ก่อนแยก"). Otherwise its exclusion would silently vanish with the deleted row.
  - Splitting a PLO-cited Need stays 409, as today.
- **Works while a session is paused at the Need checkpoint**, as split does today. A suspended session is not "running" for `sync_writer`, and `review_needs` reloads active Needs from the database on resume. Merges and exclusions made during the pause take effect, and the stale Need dicts in the checkpoint state are never used.
- **Who merged it.** Add `merged_by: Literal["agent", "designer"] | None = None` to `Need`, with a migration column next to `excluded_at`.
  - Agent 2's merge sets `"agent"` and the manual route sets `"designer"`.
  - The Need card shows "รวมโดยผู้ออกแบบ" or "รวมโดย AI".
  - *This is the controller's call*, so that the trail says who decided.
- **Re-running Agent 2 resets both.** `need_combination` deletes and rewrites every Need, which already discards splits and merges. Manual merges and exclusions are discarded the same way.
  - The Need page states this beside the re-run control: "รัน Agent 2 ใหม่จะล้างการรวมและการตัดออกที่ทำด้วยมือ".
  - The designer chose re-runs as the way to get fresh merges in phase 1, and carrying edits across new Need ids has no stable key to hang on.

### Evidence: edit before extraction, locked after

- **What "extraction has run" means.** The program has at least one stored skill row (`SkillRepository`) **or** at least one stored Need.
  - The Need clause covers a stored program whose skills were somehow absent. *This is the controller's call.*
  - A re-run of extraction keeps the program locked, because it starts with skills present.
  - A **failed first extraction does not lock.** Extraction raises before `delete_by_program` and writes skills only on success, so a failed run stores none. The designer can still fix the evidence that broke it.
  - The lock is enforced at the **API routes** only. Repository-level writers that are not designer edits are unaffected: the program copy clones rows, and seed scripts write directly.
- **The lock** is one helper, e.g. `evidence_locked(program_id) -> bool`. It is checked in:
  - `POST /evidence/` (add, and upsert of an existing id);
  - the new edit route;
  - `DELETE /evidence/{id}`;
  - `GET /evidence/classify-stream`, which rewrites rows.
  - Each answers **409**: "สกัดทักษะจาก evidence แล้ว แก้ เพิ่ม หรือลบ evidence ไม่ได้ — คัดลอกหลักสูตรแบบเฉพาะข้อมูลนำเข้าหากต้องแก้".
- **Edit route.** `PUT /programs/{id}/evidence/{evidence_id}` takes the user-entered fields: `stakeholder_type`, `source_name`, `raw_text_th`, `source_url`.
  - The `requirement`/`general` classification is derived in code from `stakeholder_type` (`classify_evidence_type`), so it is recomputed on every edit.
  - It answers 404 for an unknown or wrong-program id, 409 when locked, and 422 for invalid fields, the same validation as add.
  - It needs the API key, like add and delete.
- **`POST /evidence/` with an existing `evidence_id`.** Before the lock it keeps behaving as today, so the upload path is unaffected. After the lock it is refused like any add.
- **`evidence_id` is client-supplied and stable.** The UI mints it, and `PUT` never changes it. A skill's `source_evidence_id` therefore keeps pointing at the same row.

### Program copy: "evidence only" mode (the designer's decision, 2026-11-03)

- **Route.** `POST /programs/{id}/copy` takes an optional body field `mode: Literal["full", "evidence_only"] = "full"`.
  - `full` is today's copy, unchanged.
  - `evidence_only` clones the program metadata and its evidence rows only, with fresh `evidence_id`s through the existing `remap_ids`. It copies no skills, skill groups, Needs, PLOs or review.
  - The copy is therefore unlocked: the designer edits the evidence and re-runs Agent 1.
  - `copied_from` is set as today.
- **UI.** The copy action on the programs list offers the two modes, with labels "คัดลอกทั้งหมด" and "คัดลอกเฉพาะข้อมูลนำเข้า (แก้ evidence ได้)".
  - The evidence page's lock note links to it.
- **Tests:** an `evidence_only` copy has evidence with new ids and no skills, Needs or PLOs; its evidence is not locked; `full` is unchanged.

### UI

- **Need page (`NeedAnalysis.tsx`, `NeedCard.tsx`).** Follow the existing visual identity: ink-stamp, mandate and marker classes in `index.css`; no Tailwind palette colours.
  - **Selecting.** Every active card gets a select checkbox. A bar shows how many are selected, an optional reason field and a "รวม Need ที่เลือก (n)" button.
    - The button is enabled at 2-5 selected.
    - While the call runs, it shows the same busy state the split uses.
    - An error shows the route's Thai detail in the bar.
  - **Excluding.** Every active card gets "ตัดออก", behind the two-step confirm pattern the evidence delete uses.
  - **Excluded Needs** move to a collapsed section "Need ที่ตัดออก (n)" below the active list. Each shows its sentence, its evidence trail link and "คืน".
  - **Merged Needs** keep the existing originals disclosure and split button, and now show who merged them.
  - A 409 from any of these refreshes the page, as split does today.
  - The reset note sits beside the Agent 2 re-run control.
- **Evidence page (`StakeholderNeeds.tsx`).**
  - **Before the lock:** each item gets "แก้ไข". This opens the add form pre-filled, and save sends `PUT`.
  - **After the lock:** the add form, the file import, edit and delete are all hidden. A note in their place says why, with the same text as the 409.
  - The page learns the lock from a field on an existing read, e.g. `GET /evidence/` returns `{items, locked}`, or from a small `GET /evidence/lock`. *This is left to the builder*; one read is enough.

## Tests

- **Validators and models first.**
  - `Need` accepts the old checkpoint dicts without `excluded_at` / `merged_by`.
  - Excluded Needs are absent from `list_active_by_program`.
- **Exclude and restore:** success; every refusal (404, merged away, already excluded, not excluded, PLO-cited 409, busy 409); the resume reload drops an excluded Need.
- **Downstream:** synthesis does not draft an excluded Need; `from-needs` refuses one.
- **Manual merge:**
  - each refusal, in the order above;
  - the floor;
  - success writes `merged_into`, `merged_from`, `merged_by="designer"` and the reason;
  - a failed sentence call writes nothing and answers 502;
  - merging a merged Need nests it, and two splits restore the originals;
  - splitting an excluded merged Need gives 422;
  - a merge while a session is paused at `need_analysis` succeeds, and the resume reload sees it.
- **Agent 2 merge:** sets `merged_by="agent"`.
- **Evidence:**
  - edit before the lock recomputes the classification;
  - after the lock, add, upsert, edit, delete and classify-stream each answer 409;
  - the lock helper is true with skills only and with Needs only.
- **Frontend:** follow the existing page tests if any exist. No new test framework.

## Calls made by the controller (for the designer to check)

1. **Who merged it.** `merged_by` records whether the agent or the designer merged a Need, and the card shows it.
2. **Nesting.** Merging a merged Need nests rather than flattens.
3. **Floor check.** It uses the worst case, computed before the LLM call.
4. **Failed sentence.** A failed sentence on a manual merge answers 502 and writes nothing.
5. **Split while excluded.** Splitting an excluded merged Need is refused.
6. **What locks evidence.** The lock is "skills or Needs stored", and a failed first extraction does not lock.
7. **Scope.** It is not checked on a manual merge; this is a designer override, as in `from-needs`.
