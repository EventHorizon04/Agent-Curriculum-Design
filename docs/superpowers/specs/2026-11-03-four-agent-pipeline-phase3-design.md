# Four-agent pipeline, phase 3: the PLO page

Date: 2026-11-03. Branch: `feat/four-agent-pipeline`.
Status: the designer asked to start without a question round ("เริ่มเลย") and to
judge the result on screen. Every decision below is the builder's call, made
from the phase-1 spec's phase-3 list and the code as it stands; each is marked
so it can be reversed.

## Why

Phase 1 named five things for the PLO page and left them for later:

1. Highlight the Needs that can be merged.
2. Attach an unused Need to an existing PLO.
3. Show the PLOs a merge superseded.
4. A loading state while one PLO is re-checked by the SMART agent.
5. Align the manual merge's group bound with the dedup bound (5).

Today, on the PLO page:

- The merge panel lists every active Need, cited or not, has no upper bound on
  how many can be ticked, and does not say which PLOs the merge will replace.
- `POST /plos/from-needs` **hard-deletes** every PLO citing a selected Need
  (`PLORepository.replace`). Nothing of the replaced outcome survives, so the
  designer cannot see what was there before.
- A re-check swaps the button text to "กำลังตรวจ..." and nothing else changes
  on the card.
- `MergeNeedsRequest.need_ids` has `min_length=2` and no maximum; the Need-stage
  merge (`POST /needs/merge`) and `need_dedup` both stop at `MAX_GROUP_SIZE = 5`.

## Decisions (builder's calls)

1. **Superseded PLOs are kept, read-only, in a new table `superseded_plos`.**
   The live `plos` table cannot hold them: its key is `(program_id, plo_id)` and
   a merge normally reuses the lowest freed `plo_id`. Each row stores a JSON
   snapshot of the whole replaced PLO, the `plo_id` that replaced it
   (`superseded_by`) and `superseded_at` (naive UTC, like every DB timestamp).
   `PLORepository.replace` writes the snapshots in the same transaction as the
   delete, so a PLO is either live or in history, never lost and never both.
   *Cost if wrong:* one table and one migration to drop.
2. **No restore.** A superseded PLO is shown, not brought back. Restoring would
   have to re-check the 6-10 bounds, the one-PLO-per-Need invariant and the
   Needs it cited, which may since be merged or excluded. Splitting the merged
   PLO's Needs back out is done by a new merge, as today.
3. **History is the history of the current PLO set.** Anything that deletes
   every PLO of a program (`PLORepository.delete_by_program`, called by a
   synthesis re-run and by the program delete cascade) deletes its
   `superseded_plos` rows in the same transaction. A full program copy copies
   them, with ids remapped like every other row; an `evidence_only` copy does
   not.
4. **"Attach an unused Need" is a merge, not a new route.** Attaching Need N to
   PLO P means "draft one outcome from P's Needs plus N", which is exactly
   `POST /plos/from-needs` with `need_ids = P.source_need_ids + [N]`: it
   supersedes P (and nothing else, since N is unused), re-drafts, re-validates
   and normally keeps P's number. The UI offers it on each PLO card. All the
   existing checks (merged-away, excluded, unwritten, 6-10 bounds, 502 with
   nothing changed) apply unchanged.
5. **The manual merge takes 2-5 Needs.** `from-needs` refuses more than
   `MAX_GROUP_SIZE` (imported from `stages/need_dedup.py`, not restated) with a
   Thai 422, checked in the route like `/needs/merge` does, before any LLM call.
   A PLO already drafted from 5 Needs cannot have a sixth attached.
6. **"Mergeable" means "not behind any PLO yet".** The merge panel groups the
   active Needs into *unused* (highlighted, listed first) and *already in PLOx*
   (labelled with the PLO that cites them). Both stay selectable: picking a used
   Need is how a designer folds two outcomes into one. While Needs are ticked,
   the panel previews which PLOs the merge will replace and which Needs will be
   left without an outcome, computed in the browser from `source_need_ids` the
   same way `plos_citing` does on the server. The server stays the authority;
   the preview only explains.
7. **Loading state on the card itself.** While a card is being re-checked
   (`plo_revalidate` job for that `plo_id`) or is about to be replaced by a
   merge or attach in flight, the card is dimmed, its actions disabled, and a
   line with the existing `animate-run-sweep` mark says what is happening
   ("กำลังตรวจ SMART ใหม่" / "กำลังร่าง PLO ใหม่แทนข้อนี้") with elapsed seconds.
   No new spinner: the visual identity replaced spinners with the sweep.
8. **Superseded PLOs are listed in a collapsed section** under the live list:
   "PLO ที่ถูกแทนที่ (n)", newest first, each with its old id, statement, the
   Needs it cited, "แทนที่โดย PLOx" and the time. Muted, no actions.

## API

- `GET /programs/{id}/plos/superseded` → `list[SupersededPLO]`, newest first.
  404 when the program does not exist. A stored snapshot that no longer
  validates as a `PLO` (validators tightened since it was written) is skipped
  with a log warning rather than failing the list.
- `POST /programs/{id}/plos/from-needs`: unchanged shape and response; 422
  "เลือก Need 2-5 ข้อเพื่อรวมเป็น PLO" above 5 ids. After a successful call the
  replaced PLOs appear in `/superseded`.

`SupersededPLO` (models.py): `id: str` (uuid), `program_id: str`,
`superseded_by: str`, `superseded_at: datetime`, `plo: PLO`.

## Goals

- A designer can see, before clicking, which PLOs a merge will replace.
- A designer can add an unused Need to an outcome from that outcome's card.
- Every PLO a merge or attach replaced can still be read on the page.
- The card being re-checked or replaced shows it.
- No manual merge can draft one PLO from more than 5 Needs.

## Non-goals

- Restoring a superseded PLO (decision 2).
- Detaching one Need from a multi-Need PLO.
- A delete-PLO action.
- Recording a whole synthesis re-run as superseded PLOs (decision 3).
- Showing superseded PLOs in the PLO report, the review, or the มคอ.2 exports.
- Agent 4 send-back and its trace (phase 4).

## Anti-goals

- A PLO that disappears from both the live list and the history after a merge.
- A preview that disagrees with what the server then replaces (it must use the
  same rule: every PLO citing any selected Need).
- Weakening any existing `from-needs` check to make attach work.
