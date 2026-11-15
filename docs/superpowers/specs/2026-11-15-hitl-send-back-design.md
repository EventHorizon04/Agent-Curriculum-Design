# HITL send-back: per-PLO send-back, whole-set Need send-back with a note

Date: 2026-11-15. Branch: `feat/four-agent-pipeline`. Status: the designer chose the shape; this short design awaits approval.

## Why

Research Plan phase 1 has an open item: test the HITL buttons at both checkpoints (Needs, PLOs), namely confirm, merge, send back and attach a note, in both modes. Merge, notes and approval already exist. **Send back** does not exist as a real button: the Need page has only a re-run button, single mode cannot attach a note to it, and the PLO checkpoint has only approve. UTCC faculty will use this for real, so the button must do what its name says.

## What the designer decided (2026-11-15)

| Checkpoint | Send back means |
|---|---|
| PLO (`plo_review` page) | **Per PLO.** The designer ticks one or more PLOs, writes a reason for each, and the AI rewrites only those. The rest are untouched. |
| Need (`need_analysis` page) | **Whole set with a note.** The designer writes a note and the AI redoes the Need set. |

Both apply in multi and single mode.

## Approaches considered

- **Per-item for both checkpoints.** Rejected by the designer. Per-Need rewriting has no path today, needs a new prompt after the lock, and is hardest in single mode. It is about twice the work.
- **Whole-set for both checkpoints.** Rejected by the designer. At the PLO checkpoint, a teacher usually objects to one or two outcomes, and redoing the set throws away the ones they accepted.
- **Chosen:** per PLO plus a whole-set Need send-back. The PLO half reuses the redraft path that the review loop's automatic send-back and the designer merge already use. The Need half extends the existing re-run.

## Design

### PLO send-back (per item)

- **UI**, on the PLO checkpoint page:
  - Each PLO card gets a "ส่งกลับ" toggle and a required reason field (Thai, free text).
  - One button, "ส่งกลับให้ AI แก้ (N ข้อ)", sends every ticked PLO.
  - It is disabled while any ticked PLO has an empty reason, and while a job runs.
- **API**:
  - `POST /programs/{id}/plos/send-back` with body `{items: [{plo_id, reason_th}]}`.
  - It requires `X-API-Key`, like every write route.
  - It starts one job, kind `plo_send_back`, through the usual single-flight guard (409 when busy).
- **Work**: for each item in order, call `stages/plo_redraft.redraft_from_needs`:
  - `need_ids` = that PLO's `source_need_ids`.
  - `note_th` = the reason.
  - `cause="send_back"`.
  - In single mode, use the single agent's drafter (`_single_drafter`), never multi's synthesis. A single program must not reach a multi prompt.
- **Checks still apply.** Every bound, the SMART gate and the hard-check last word work as they do for a designer merge.
- **Hand-edited PLOs:** a PLO the designer edited by hand may be sent back. The designer asked for the rewrite, unlike the automatic send-back, which never touches such a PLO.
- **Result, per item:**
  - Rewritten: new id and statement.
  - Refused: `RedraftRefused` detail.
  - Failed: `RedraftFailed`.
  - One item's failure does not stop the others.
- **Trail:**
  - The replaced PLO is kept in `superseded_plos` with `cause="send_back"` and the reason.
  - The new PLO's card shows "ส่งกลับโดยผู้ออกแบบ: <reason>" and the old statement, in the same way the review loop's redrafts show theirs.
- **Review after a send-back (designer's decision of 2026-11-15, option ก).** A send-back does not start the review loop by itself, but in multi mode the existing rule stands: the set changed after the last review, so approval stays locked until the designer runs the review again. That review **never rewrites a PLO the designer sent back**. It is treated like a hand-edited PLO: its findings stay as comments. With no sent-back PLO in the set, the review loop behaves exactly as before, and a test pins that, because the loop is part of the locked pipeline. Single mode has no review and is unaffected.
- **Where the controls live.** The PLO checkpoint page (`plo_review`) has no PLO cards today, so it gains a list of the current PLOs with the send-back toggle and reason field, near the approve button. *Builder's call.*

### Need send-back (whole set, with a note)

- **UI**, on the Need checkpoint page:
  - The re-run button becomes "ส่งกลับให้ AI ทำใหม่", with the note field ("หมายเหตุถึง AI") above it, in both modes.
  - The note is optional, but the field invites one.
  - A confirm states what is replaced: the current Need set, and any merges or exclusions the designer made, if the re-run replaces them today. The builder checks what it replaces.
- **Multi:** unchanged route, `POST /needs/combine/run` with `note_th`. Agent 2 reruns over the stored skills.
- **Single:** `POST /needs/run` accepts `note_th` (`DesignerNoteRequest`) for single programs and passes it to `run_single_needs`. The needs-task opening message appends it with `append_note`, as the PLO half already does.
  - With no note, the opening message is byte-identical to today's, so the lock runs are unaffected.

### Mock mode

`npm run dev:mock` handlers and scenarios cover both send-backs, so the button test can be rehearsed without the backend.

## Non-goals

- Per-Need send-back.
- Re-running the review loop after a PLO send-back.
- Changing the Pipeline page's session "reject", which ends a session and is not a send-back.
- Any change to what research runs execute.

## Consequences for the prompt lock

The single needs-task builder in `prompts/single_agent.py` gains note text, used only when a note is given. The file's hash changes, so the lock manifest is regenerated after this lands. The record says the change is note-only and that runs without a note send identical prompts. No other prompt file changes.

## Left to the builder

- Whether `plo_send_back` needs a migration, which depends on whether job kinds are constrained in the DB.
- The exact card layout, using existing components and tokens and following the frontend identity rules.
- The order of results in the job output.
