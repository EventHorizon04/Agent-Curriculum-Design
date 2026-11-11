---
paths:
  - "src/curriculum_agent/stages/plo_review*.py"
  - "src/curriculum_agent/prompts/plo_review.py"
  - "tests/**/test_plo_review*.py"
---

# PLO QA review (stage 06) pitfalls

Moved out of the root CLAUDE.md so it loads only when working on the files above.
These are standing project rules, not suggestions — same weight as CLAUDE.md.

- **The agent is given little on purpose, and the review changes nothing
  itself.** `stages/plo_review.py` stores findings and the stage 06 page shows
  them; the only thing that turns a finding into a change is send-back (last
  bullet), run by code after the review is stored. A KSEC suggestion is never a
  PLO KSEC field. **Every number is
  code's:** `stages/plo_review_facts.py` computes the dossier, the KSEC coverage
  and the Bloom histogram (both count every PLO, optional ones included — the
  designer's decision of 2026-10-12 — while `core_count` against the 6-10 band
  counts core only), the unused-Need selection (top 5 by `demand_score` plus
  every `professional_council` one) and the fingerprint; `current`, `agrees` and
  `declared` are code's too, because the model can only claim them, and `Finish`
  has no field for a number. **The dossier leaves four things out, because the
  more upstream detail the agent reads, the more it anchors on it and re-litigates
  earlier stages instead of judging the set as written (information bias):**
  evidence text, member skill names, the shared-evidence share between PLOs
  (measured misleading — an unrelated pair shared 55%, a true duplicate pair
  under 20%), and SMART diagnoses or the previous review (it would restate an old
  verdict). `need_detail` answers only for a Need in the dossier's unused list, and
  refuses an unwritten one; it returns counts only (member count and voices per
  stakeholder type), never `rationale_th`. An unwritten (`[ต้องทบทวน]`) Need's statement *is* its
  skill names, so the prompt shows a placeholder in its place — keyed on
  `UnusedNeedFinding.unwritten`, not on the exclusion reason, and for cited Needs
  too. A unit test renders the prompt the model actually reads and asserts the
  skill names, evidence and skill ids, `rationale_th` and SMART markers are
  absent, so adding "just one more field" to the dossier fails there first (phase 6
  extended it over a prompt that carries voices); the
  shared-evidence share and the previous review are absent by construction — the
  dossier has no field for either. **The vote is code's, over judged runs, with early stop:** `_review` runs `plo_review_runs // 2 + 1` runs first (3 of 5; 2 of 3), and when all of them are usable and their `review_key`s are equal (`plo_review_consensus.review_key`: redundancy pairs, alignment PLO ids, Bloom `(plo_id, level-or-declared, verb)`, unused `(need_id, verdict)`, KSEC `(plo_id, suggested set)`) the other runs are not made and the vote is over those, with `runs_requested = plo_review_runs`; otherwise the rest run and every usable run is counted. The stored `agreement_threshold` is `runs_succeeded // 2 + 1` (2 after a 3-run stop), but send-back's bar `max(threshold, runs_requested // 2 + 1)` stays 3, so an early stop never lowers what acts. Each run passes `accept_review` first, and `consensus_review` only counts — a redundancy is voted pair by pair and a three-PLO group survives only when every pair in it has a majority, so the stored set never asserts a pair no majority asserted; the free text and `dropped_findings` come from the run that best matches the vote, so the dropped warning still describes the summary shown. **A review that could not run
  stores `reviewed_by="code_only"`** with `code_only_reason`
  (`disabled`/`failed`/`timeout`) and the code facts, and no agent finding is
  manufactured — the SMART agent's discipline, for the same reason: a validator
  that could not run must not report. The job still succeeds. **The fingerprint
  covers the program's Needs** as sorted `(need_id, demand_score)` pairs as well
  as the PLOs, because the unused-Need answer depends on them: a rescored Need
  makes the review stale. A review is reused while the fingerprint is unchanged
  and shown labelled stale once it moves; `stage_reached` counts only a current
  one as stage 06. Entries `accept_review` refuses are counted in
  `dropped_findings` and the stage 06 page warns, because the agent's
  `summary_th` is not re-checked and can still mention a dropped finding.
- **Alignment is judged on voices, never on evidence text (phase 6, designer's
  option ก).** Each PLO's dossier entry carries, per cited Need, the Need's sentence
  and its **voices**: distinct evidence items per stakeholder type (ผู้ประกอบการ 3,
  ศิษย์เก่า 2), computed in code by `plo_review_facts.need_voices` from the Need's
  `source_evidence_ids` and the evidence rows' `stakeholder_type`. It is not
  `Need.stakeholder_coverage`: that counts member skill rows, so one employer
  document naming three skills read as "3". "จำนวนผู้ขอ" means this count
  everywhere in the code. The reviewer returns an `AlignmentFinding` (does the
  statement answer what its Needs ask?) with a reason and suggestion; nothing else
  is added to what it sees, so the information-bias rule above stands. `_review`
  reads the evidence table once for the stakeholder types; the reviewer still never
  sees a span of it.
- **The verb and Bloom finding is voted by plurality among the runs that agreed on
  it, and the level is still the gate.** `BloomFinding` gained `suggested_verb_th`
  and `suggestion_th`; the prompt asks whether the verb fits the work and the degree
  level, not only the level. `plo_review_consensus._bloom` counts an entry that
  proposes neither a level change nor a verb as no vote; an entry with no level
  change votes for the declared level, so a verb-only entry never carries a level
  change on its own (a minority level suggestion cannot ride on a verb majority:
  the level change is the plurality of the agreeing runs, ties go to the level
  nearest the declared one). The verb mirrors that rule (final review M2): an
  agreeing entry that names no verb votes to *keep* the verb, a verb is carried
  only when it beats keep, keep wins a tie against any verb, and a tie between
  verbs that beat keep takes the first seen — so {level change, verb X, verb Y}
  carries no verb, where counting only the entries that named one used to carry X.
  `review_key` already separates every vote and stayed as it was; a parametrised
  test covers each of its components. Send-back acts on a Bloom finding with a level change **or** a
  verb; acceptance still requires the suggested level when one is given, because
  the verb is guidance and the SMART checks govern it.
- **The KSEC gap is a code fact, acted on only inside the agent loop.** A category
  with zero PLOs (`ksec_coverage.missing`) needs no vote. Send-back drafts a PLO
  from the highest-`demand_score` Need of that category that no PLO cites and that
  is written and in scope (`is_unwritten_need`, `exclusion_reason`), under the
  existing ceiling. With no such Need it records `skipped` ("ไม่มี Need หมวดนี้ —
  ต้องเพิ่มที่ขั้น Need"), a comment for the designer that is **not** counted as
  actionable (`actionable_count`), so it never keeps the loop running. With
  send-back off or a `code_only` review nothing is sent back, the gap included.
  Per-PLO KSEC suggestions stay advisory: a PLO's KSEC comes from its Needs.
- **Send-back (Agent 4) acts on a review in code, once per round, and the trail is
  the safety.** `fresh_review_with_feedback` (`stages/plo_review.py`; `fresh_review`
  wraps it, so the graph tail and the REST job both get it) runs
  `stages/plo_feedback.py` right after a *fresh agent* review is stored. A reused
  stored review, a `code_only` review and `plo_review_send_back=False` send
  nothing. Only **agreed** findings count: `agreed_runs >= max(agreement_threshold,
  runs_requested // 2 + 1)` — a majority of the runs *asked for*, not of those
  that succeeded, so with 5 requested a finding needs 3 votes whatever succeeded
  (one surviving run of five sends nothing back; 1 requested needs 1). Order: redundancy, alignment, Bloom/verb (only when a level
  change or a verb is suggested), the KSEC gap, then an unused Need with verdict
  `consider` (skipped when unwritten or out of scope, or when a PLO already cites
  it this round). Per-PLO KSEC suggestions stay advisory. **Every action goes through
  `stages/plo_redraft.redraft_from_needs`**, the designer's merge core with
  `cause="review"`, so `MAX_GROUP_SIZE`, the merge floor and the SMART gate all
  apply; a redundancy whose Need union exceeds `MAX_GROUP_SIZE` is skipped
  ("รวมแล้วเกิน 5 Need"). **Before each action the live PLO set is re-read**; a finding naming a PLO
  replaced earlier in the round is skipped ("PLO นี้ถูกแทนที่ไปแล้วในรอบนี้"), checked *before* "not
  found" because a freed `plo_id` is reused (lowest free) by the new outcome, so
  a redraft can renumber an outcome. Known one-round limit: overlapping redundancy groups
  (PLO1+PLO6, then PLO3+PLO6) apply the first and skip the second; a later review
  may catch PLO3. **The trail:** one `plo_feedback_actions` row per considered
  actionable finding (`applied` / `skipped` / `failed`, with a Thai reason). An
  **applied** row is written by `PLORepository.replace` in the transaction that
  swaps the PLOs (`redraft_from_needs(trail=...)` builds it for the accepted
  draft, `replace(trail_row=...)` inserts it; final review I4): written afterwards,
  the loop's `asyncio.timeout` could cancel between the commit and the row and
  leave a changed PLO with no row saying why. `_record` then only keeps and logs
  it. Skipped, failed and planned rows change nothing and are written right after
  their action, one at a time; a failed write of one is logged at error level and
  the round continues.
  **`send_back` receives the set the review judged** and, before each action,
  skips a named PLO whose live `statement_th` or `source_need_ids` differ
  ("PLO นี้ถูกแก้หลังการตรวจ — ไม่ส่งกลับ"); order of skip checks: replaced this
  round, edited since the review, not found. `PUT /plos/{id}` is not blocked
  while a review runs; this check is what keeps a hand edit made *before* the
  action from being redrafted away. A hand edit made *during* the action's draft
  (which can take minutes) is caught at the write: `replace` gets `expect`, the
  superseded PLOs' statements as read before the draft, re-reads them locked, and
  refuses when one is gone, reads differently or is designer-edited — `skipped`
  "PLO นี้ถูกแก้ระหว่างร่างใหม่ — ไม่เขียนทับ" (final review I1). **`redraft_from_needs(..., accept=...)`** is called after a
  successful draft and before `replace`; a returned Thai reason raises
  `RedraftRefused(422, reason)` with nothing written. `from-needs` passes none.
  Send-back's accept refuses a `smart_escalated` draft unless every PLO it
  replaces was already escalated (an unused-Need add replaces nothing, so any
  escalated draft is refused) and, for Bloom, a draft whose `bloom_level` is not
  the suggested level; both are `skipped` with a Thai reason. **After an applied
  send-back the stored review is stale by construction** (the set changed right
  after the review was stored): in `off` mode the rail shows the PLO stage until
  the designer re-runs the review, and in the loop the last step is always a fresh
  review, which is what makes the set at the checkpoint reviewed. A round has no
  action cap and holds the program busy while it runs; the loop has its time
  budget (below). Any exception inside an action records it `failed`;
  nothing in send-back fails the review job or the session. The Bloom redraft
  note (`prompts/plo_feedback.build_bloom_redraft_note_th`) names the level in
  English plus up to 3 example verbs and must never contain a forbidden PLO word
  — a Thai label for Remember/Understand would be จำ/เข้าใจ; a test checks every level.
- **Every redraft note carries the review's advice and the old statement, and no
  forbidden word (phase 6, designer's decision of 2026-11-04).** Before, only the
  Bloom send-back passed the reviewer's words; a redundancy merge or an unused-Need
  draft handed synthesis the Needs alone, so it redrafted without knowing what was
  wrong. Each finding kind has its own builder in `prompts/plo_feedback.py`
  (redundancy, alignment, Bloom/verb, KSEC gap, unused Need), going through the
  existing `note_th` channel: the finding's `reason_th` and `suggestion_th` (each
  capped at 280 characters, the cap shrinking before the statements are cut) and
  the statement(s) being replaced under "ร่างเดิมที่ผู้ตรวจติ", the whole note
  capped at `MAX_NOTE_CHARS` (900). **Every quoted piece is masked first**
  (`mask_forbidden_words`, then cut: masking after the cut could split a word)
  because an escalated statement may legitimately contain a forbidden word and
  quoting it would hand synthesis the very word it must not write;
  `test_notes_never_carry_forbidden_words` renders every builder over a statement
  with เข้าใจ. A new builder needs the same test.
- **The review loop (`stages/plo_review_loop.py`) repeats review and send-back, and
  every stop writes one `loop_end` trail row.** `fresh_review_with_feedback` holds
  the `_REVIEW_IN_FLIGHT` guard and delegates to `run_review_loop`; the phase-4 body
  survives as `_review_once_with_send_back`, which `off` mode and
  `plo_review_max_rounds=0` run. A round is: review the live set, store it,
  `send_back(round_no=i)`; the cap counts **send-backs**, so the loop makes at most
  `max_rounds + 1` reviews (6) and the last step is always a review. **Stop
  reasons**, each a Thai `loop_end` row (`outcome="stopped"`, with the round).
  Pass — read off the stored review, not off the rows (final review M3): no finding
  agreed by send-back's own rule (`plo_feedback.has_agreed_work`) and no missing
  KSEC category with a Need a gap draft could use; send-back still runs on a pass,
  so the no-Need KSEC comments are recorded. Send-back failed ("ส่งกลับไม่สำเร็จ —
  หยุด"): agreed work, yet no actionable row, because `send_back` stopped early and
  logged why. No change (a round applied nothing: every action skipped or failed,
  so another round would read the same set; this covers every action skipped for a
  hand edit, the floors or an earlier merge). Cap. Send-back off ("ปิดการส่งกลับ —
  ไม่แก้ PLO", its own reason, not "no agent"). No agent review (a `code_only`
  first review). Reviewer late ("ผู้ตรวจไม่ตอบในรอบนี้ — ใช้ผลตรวจรอบก่อน", final
  review M4): a round ≥ 2 review came back `code_only` after an agent review in
  this loop; the last agent review is stored again so the checkpoint keeps its
  comments, but only when its fingerprint equals the code-only one's — a stored
  review must describe the stored set, and usually it no longer does, since the
  round before applied something. Error, and timeout. The whole loop runs under `plo_review_loop_timeout_seconds` (5400): when
  it runs out the round in progress is abandoned, its rows stay (every redraft is a
  complete replace with its own trail row, and `send_back` appends to the caller's
  list as it writes), and one final review of the stored set runs under the normal
  review timeout. A provider's own `TimeoutError` is an in-round failure, not the
  loop budget (`scope.expired()` tells them apart). Only a failure of the *first*
  review reaches the caller, as the single pass always did; a timeout or error
  later is a stop reason, never a failed session. The last stored review is the one
  shown, its unresolved findings being the comments at the checkpoint.
- **Shadow mode writes no PLO; `apply` is the default since 2026-11-11.** `plo_review_loop_mode="shadow"`
  reviews once and calls `send_back(dry_run=True)`: every action runs its checks
  and is recorded `planned` with its instruction, nothing is redrafted. The checks
  include every one `redraft_from_needs` makes before its draft —
  `plo_redraft.check_redraft` (unknown, merged-away, excluded or unwritten Need,
  the `MAX_CORE_PLOS` ceiling, the `MIN_CORE_AFTER_MERGE` floor), the function the
  live path calls, so a refusal is `skipped` with the same text (final review I3);
  only the post-draft `accept` cannot be planned. A dry run books what a live one
  would have (the PLOs an action would replace count as replaced, its Needs as
  taken, and one stand-in PLO per planned draft joins the set the next check
  counts), so later actions of the round see the same world and the plan does not
  overstate real actions; the designer reads the plan
  to see what `apply` would do. It works on a copy of the loop's memory and teaches
  it nothing. The designer made `apply` the default on 2026-11-11 (spec decision
  29) after the guarded apply run; `shadow` stays available for a dry look.
- **Merge drift guard: a PLO a redundancy merge wrote is not merged again within
  the loop.** Phase 4's live runs merged more on every review (9 -> 8 -> 7 PLOs).
  `LoopMemory.merged` holds the Need set (`frozenset(source_need_ids)`) of every
  PLO an applied redundancy wrote; a later round naming a live PLO with that Need
  set is `skipped` ("PLO นี้เพิ่งรวมมาในรอบก่อน"). Keyed on the Needs since final
  review I2: the old `(plo_id, statement_th)` key was laundered by any alignment or
  Bloom redraft of the merged PLO in between, which rewrites the statement but
  drafts from the same Needs. The floors
  (`MIN_CORE_AFTER_MERGE`, `MAX_GROUP_SIZE`) still hold.
- **One alignment redraft per PLO per loop (designer decision 28).** Same pattern as
  the merge guard: `LoopMemory.aligned` holds the Need set of every PLO an applied
  alignment redraft wrote (a dry run never adds). A later alignment finding on a live
  PLO with that Need set is `skipped` with `REASON_ALIGNED_EARLIER` ("PLO นี้แก้ความสอดคล้อง
  ไปแล้วในรอบก่อน — เป็นข้อสังเกต"), checked after `unavailable_reason` and before any
  redraft, so it survives a Bloom redraft in between. `actionable_count` ignores such
  rows (like `REASON_KSEC_NO_NEED`), and `has_agreed_work(..., memory)` does not count
  an agreed alignment finding on a guarded PLO, so a round with nothing else is a pass.
- **A PLO the designer edited by hand is never rewritten by send-back
  (`designer_edited_at`, designer's decision of 2026-11-04).** `PUT /plos/{id}` with a
  changed statement sets it, and nothing clears it but replacing the outcome
  (`from-needs` writes a new draft without it). `unavailable_reason` skips a
  redundancy, alignment or Bloom finding naming such a PLO, and `_send_unused`
  skips an unused-Need draft whose Need such a PLO cites, with "PLO นี้ผู้ออกแบบแก้เอง —
  ไม่เขียนทับ"; the findings still show as comments. The check order is replaced
  this round, edited since the review, designer-edited, missing. The marker is the
  stored row's own: `stale` is not enough, because a revalidate overwrites it.
