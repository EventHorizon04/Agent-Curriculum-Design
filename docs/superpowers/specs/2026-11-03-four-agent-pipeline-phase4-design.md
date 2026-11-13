# Four-agent pipeline, phase 4: Agent 4 sends its findings back

Date: 2026-11-03. Branch: `feat/four-agent-pipeline`.
Status: the designer asked to carry on without a question round ("จัดการต่อ").
The one decision that is theirs was made on 2026-10-26: **plo_review findings
go back automatically, and a UI must show the trail so the AI's effect can be
traced.** Everything else below is the builder's call, marked so it can be
reversed.

## Why

Today the QA review (stage 06, `stages/plo_review.py`) only advises: it stores
findings, the review page shows them, and no code path turns a finding into a
change (`.claude/rules/plo-review.md`). The designer has to read each finding
and act on it by hand. The designer decided the agent's agreed findings should
be applied for them, with a visible trail.

## What a finding can do

The review stores four finding kinds. Only findings that passed the vote
(`agreed_runs >= review.agreement_threshold`) count; a `code_only` review has no
agent findings and sends nothing back.

| Finding | Send-back action | Builder's call |
|---|---|---|
| `RedundancyFinding` (2-3 PLOs read as one outcome) | Draft one PLO from the union of those PLOs' Needs; it replaces them. | Same operation as a designer merge on the PLO page. |
| `BloomFinding` with `suggested_level` set and different from `declared` | Redraft that PLO from its own Needs, with an instruction to write it at the suggested level and the reviewer's reason. It replaces the old one. | The SMART gate still has the last word; the trail records the level asked for and the level obtained. |
| `UnusedNeedFinding` with verdict `consider` | Draft a new PLO from that one Need. | Skipped when the Need is unwritten or out of scope (the review already marks both). |
| `KsecFinding` | Nothing. | A PLO's KSEC comes from its Needs; rewording cannot move it. It stays advisory on the review page. |

Every action goes through one function — the core of today's `from-needs`
route, moved out of the route into a stage module — so the existing checks
apply to the agent exactly as to the designer: merged-away, excluded and
unwritten Needs are refused, `MAX_CORE_PLOS` and `MIN_CORE_AFTER_MERGE` hold,
at most `MAX_GROUP_SIZE` Needs per PLO, a failed draft changes nothing, and a
replaced PLO lands in `superseded_plos` (phase 3). A refused or failed action is
recorded as skipped with its Thai reason; it never fails the job or the session.

**Order within one round:** redundancies first (they change which PLOs exist),
then Bloom redrafts (skipping a PLO a redundancy already replaced this round),
then unused Needs (the ceiling is judged after the merges freed slots).
Actions run one at a time, because each one's bounds depend on the last.

## Decisions (builder's calls)

1. **One round, no loop.** Send-back runs once, right after a *fresh* agent
   review is stored (`fresh_review`, used by `POST /plos/review/run` and by the
   graph tail when it reviews afresh). A reused stored review sends nothing. The
   changed set makes that review stale, as any edit does; the designer re-runs
   the review to judge the new set, and that run may send back again. A loop
   inside one job could oscillate (merge, then split by a later finding) and
   would multiply the cost.
2. **On by default, with a switch.** `plo_review_send_back: bool = True` in
   `config.py`. Off restores today's advisory-only behaviour.
3. **The trail is its own table, `plo_feedback_actions`.** One row per
   considered finding: `id`, `program_id`, `review_created_at` (which review
   round), `kind` (`redundancy` | `bloom` | `unused_need`), `plo_ids` (the PLOs
   the finding named, empty for an unused Need), `need_ids` (what was drafted
   from), `finding_reason_th` (the reviewer's reason), `instruction_th` (the
   note sent to synthesis, empty if none), `outcome` (`applied` | `skipped` |
   `failed`), `outcome_reason_th`, `result_plo_id`, `result_statement_th`,
   `result_bloom_level`, `created_at`. It is cleared with the PLO set
   (`delete_by_program`, program delete), copied by a full program copy with ids
   remapped, and not by an `evidence_only` copy — the same life as
   `superseded_plos`.
4. **`superseded_plos` gains `cause`** (`designer` | `review`, nullable; null
   reads as designer for rows written before), so the history says who replaced
   an outcome.
5. **Rule 7 changes.** The checkpoint after PLO was waived because neither the
   report nor the review changed designer content. Send-back does change it,
   after the PLO checkpoint and without approval — that is the designer's
   decision of 2026-10-26, and the trail plus the superseded history are what
   make it safe. CLAUDE.md rule 7 and `.claude/rules/plo-review.md` ("nothing
   reads it back") are rewritten to say so.
6. **The instruction text for a Bloom redraft** is Thai and built in code, in
   `prompts/` like every prompt: it names the suggested level and quotes the
   reviewer's reason. It goes through the existing `note_th` channel of
   `draft_from_needs`, so no prompt builder changes shape.

## API

- `GET /programs/{id}/plos/feedback` → `list[FeedbackAction]`, newest first;
  404 for an unknown program.
- `POST /plos/review/run`: unchanged request; the job result additionally
  carries `feedback: list[FeedbackAction]` for this round (empty when off,
  code-only, or nothing actionable).
- `POST /plos/from-needs`: unchanged behaviour; now a thin route over the
  shared function, with `cause="designer"`.

## UI

- **Review page (stage 06):** a section "ส่งกลับไปแก้แล้ว" for the latest round:
  each action shows the finding's kind and reason, then either the before
  (from the superseded snapshot) and after statements with the result PLO id,
  or "ข้าม" / "ไม่สำเร็จ" with the reason. Older rounds collapsed below.
- **PLO page:** a card whose current statement equals an applied action's
  `result_statement_th` (same `plo_id`) shows a chip "แก้ตามผลตรวจ" linking to
  the review page. Superseded entries with `cause="review"` read
  "แทนที่ตามผลตรวจ".
- Mocks mirror all of it.

## Goals

- After a review run, every agreed redundancy, Bloom and "consider" finding has
  either been applied or has a recorded reason why not.
- The designer can see, for each automatic change, what the reviewer said, what
  was there before and what replaced it.
- No automatic change can break a bound or a check a designer's own merge
  could not.

## Non-goals

- New review checks. Phase 1 listed "new checks" for Agent 4 without naming
  them; inventing checks is the designer's call, so it waits for their list.
- Looping review → send-back → review inside one run (decision 1).
- Acting on KSEC findings.
- Undo of an automatic change beyond what the superseded history shows.
- Sending findings back to the Need stage (re-running Agent 2).

## Anti-goals

- An automatic change with no trail row.
- A send-back failure that fails the review job or the session.
- A path where the agent can do what the designer's merge route would refuse.
