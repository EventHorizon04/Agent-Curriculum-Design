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
  absent, so adding "just one more field" to the dossier fails there first; the
  shared-evidence share and the previous review are absent by construction — the
  dossier has no field for either. **The vote is code's, over judged runs:** each run passes `accept_review` first, and `consensus_review` only counts — a redundancy is voted pair by pair and a three-PLO group survives only when every pair in it has a majority, so the stored set never asserts a pair no majority asserted; the free text and `dropped_findings` come from the run that best matches the vote, so the dropped warning still describes the summary shown. **A review that could not run
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
- **Send-back (Agent 4) acts on a review in code, once, and the trail is the
  safety.** `fresh_review_with_feedback` (`stages/plo_review.py`; `fresh_review`
  wraps it, so the graph tail and the REST job both get it) runs
  `stages/plo_feedback.py` right after a *fresh agent* review is stored. A reused
  stored review, a `code_only` review and `plo_review_send_back=False` send
  nothing. Only **agreed** findings count (`agreed_runs >= agreement_threshold`);
  a 2/5 Bloom finding is ignored. Order: redundancy, then Bloom (only when
  `suggested_level` is set and differs), then an unused Need with verdict
  `consider` (skipped when unwritten or out of scope, or when a PLO already cites
  it this round). KSEC findings stay advisory. **Every action goes through
  `stages/plo_redraft.redraft_from_needs`**, the designer's merge core with
  `cause="review"`, so `MAX_GROUP_SIZE`, the merge floor and the SMART gate all
  apply; a redundancy whose Need union exceeds `MAX_GROUP_SIZE` is skipped
  ("รวมแล้วเกิน 5 Need"). **Before each action the live PLO set is re-read**; a finding naming a PLO
  replaced earlier in the round is skipped ("PLO นี้ถูกแทนที่ไปแล้วในรอบนี้"), checked *before* "not
  found" because a freed `plo_id` is reused (lowest free) by the new outcome, so
  a redraft can renumber an outcome. Known one-round limit: overlapping redundancy groups
  (PLO1+PLO6, then PLO3+PLO6) apply the first and skip the second; a later review
  may catch PLO3. **The trail:** one `plo_feedback_actions` row per considered
  actionable finding (`applied` / `skipped` / `failed`, with a Thai reason),
  written right after its action so an applied change is never left without a
  row if the round stops later; a failed trail write is logged at error level and
  the round continues. Any exception inside an action records it `failed`;
  nothing in send-back fails the review job or the session. The Bloom redraft
  note (`prompts/plo_feedback.build_bloom_redraft_note_th`) names the level in
  English plus up to 3 example verbs and must never contain a forbidden PLO word
  — a Thai label for Remember/Understand would be จำ/เข้าใจ; a test checks every level.
