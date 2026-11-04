# Four-agent pipeline, phase 6: voted SMART loop, review repair loop, report last

Date: 2026-11-04. Branch: `feat/four-agent-pipeline`.
Status: decided with the designer in chat on 2026-11-04. What is theirs is
marked **(designer)**; everything else is the builder's call, marked so it can
be reversed.

## Why

The designer drew the PLO tail as two repair loops followed by a single human
gate (a system architecture diagram shown in chat; only its loops are adopted,
not its agent names or its missing Need checkpoint):

```
PLO drafting ⇄ SMART check (≤3 rounds) → set-level review ⇄ back to PLO drafting (≤5 send-backs; the diagram said 3)
  → designer approves the output → final PLOs (report)
```

Today the tail is the other way round: the designer approves the PLOs right
after synthesis, then `plo_report` runs, then the review runs once and sends
its findings back once — so the report is printed before the review has changed
anything, and the designer approves a set the AI changes afterwards. The SMART
agent is a single run per PLO, while `need_dedup` and the review already vote
over five runs because one run was measured to be unstable.

## Decisions

### The designer's

1. **(designer)** The report shows the final result, after every agent has
   run. `plo_report` moves to the end of the tail.
2. **(designer)** The PLO checkpoint where the designer approves the set moves
   to the end, on the output: synthesis → SMART → review loop → **checkpoint**
   → report. The Need checkpoint (`need_analysis`) and the evidence checkpoint
   stay; agent names in code and docs stay as they are.
3. **(designer)** The SMART validation agent is run 5 times and the PLO must
   pass 3 of 5; a PLO that does not pass is repaired and checked again, at most
   3 rounds; still failing after that, it goes forward with its comments.
4. **(designer)** The review works the same way: 5 runs, a finding needs 3 of 5,
   a failing set is sent back to PLO drafting (the synthesis slot) for repair and
   reviewed again, at most **5 send-backs** (raised from 3 by the designer on
   2026-11-04, after the diagram); still failing, it goes forward with its
   comments. The SMART loop keeps its 3 rounds.
5. **(designer)** The review reads the whole PLO set in one pass and checks:
   1. alignment with the Needs and the stakeholder data — **option ก**: the
      reviewer sees each cited Need's sentence and how many voices per
      stakeholder type asked for it (e.g. ผู้ประกอบการ 3, ศิษย์เก่า 2), never
      evidence text;
   2. redundancy between PLOs;
   3. that the set covers K, S, E and C;
   4. that each action verb and Bloom level fit;
   5. ~~Thai language quality~~ — **dropped (designer): hard to test**;
   6. every finding comes with a recommendation and is sent back to PLO
      synthesis for repair.

### The builder's (reversible)

6. **What "3 of 5" means: a problem counts when 3 of 5 runs agree on it.**
   - SMART: a soft criterion (S object, M assessability, A level, A actor, A scope, R
     Needs, T horizon) fails when at least 3 of the 5 runs fail it. A PLO passes a
     round when the code's hard check is clean **and** no soft criterion failed by
     majority.
   - Review: a finding counts when at least 3 of the 5 runs report it (the vote
     `plo_review_consensus` already does). The set passes a round when no
     actionable finding counts.
   - The alternative, "3 runs each say the whole thing passes", was rejected. When
     five runs each flag a *different* criterion, it fails the PLO, yet there is
     nothing a majority agreed to repair, so the loop would spend its rounds
     rewriting at random.
   - The threshold is a majority of the runs *requested* (`n // 2 + 1`), as
     send-back already uses. Failed runs do not lower the bar.
7. **The hard check is not voted.** It is pure code and gives the same answer
   every time. Immutable rule 5 is unchanged:
   - the code gate on the final statement alone sets `smart_escalated`;
   - the agents cannot clear a hard failure.
8. **Soft criteria now drive repair but still never escalate.** A soft criterion
   still failing by majority after 3 rounds is stored in `soft_flags` and the
   SMART check fields, with the representative run's note. These are the
   "comments" the designer reads at the checkpoint. `smart_escalated` stays
   hard-only.
9. **The SMART agent splits into judge runs and a repair step.**
   - **Judge runs.** The 5 runs of a round judge the *same* statement, with the same tools as
     today minus `RequestRepair`, ending in `Finish`. Each run may still say what
     it would change, in a new `repair_hint_th` on `Finish`.
   - **Vote and repair.** Code votes. When the PLO fails the round, **one** repair call goes to the
     synthesis slot (today's `_repair`). Its instruction comes from the hard
     failures plus the soft criteria that failed by majority, with the hint of the
     run that best matches the vote (same `_representative` rule as the review).
   - **Rounds.** The repaired statement is judged again by 5 fresh runs. Rounds = repairs,
     bounded by `validation_max_repairs` (3).
   - **Why split.** Five runs that each repair would produce five different statements, with
     nothing to vote on.
10. **A validator that could not vote does not manufacture findings.**
    - When fewer runs succeed than the threshold needs (e.g. 2 of 5 after an
      outage), the round's soft verdicts are not used. Only hard failures drive
      repair.
    - When that happens before any round completed, the PLO is stored
      `smart_validated_by="code_only"` with the reason, as today.
    - `validation_runs=1` reproduces today's single-run behaviour (threshold 1).
11. **New settings**:
    - `validation_runs` (5);
    - `plo_review_max_rounds` (5).

    The 5 judge runs of one PLO run concurrently, under the existing
    `llm_max_concurrency` bound shared with the other PLOs.
    `validation_max_concurrent_plos` keeps bounding PLOs. The per-PLO timeout
    (`validation_timeout_seconds`) covers the whole PLO loop and is raised to
    600 s. Its old 240 s was sized for one run. The measurement below re-sizes it.
12. **Review loop.** A round is:
    1. a fresh 5-run review of the stored set;
    2. send-back of every actionable agreed finding through
       `plo_redraft.redraft_from_needs` (so every redraft runs the voted SMART loop
       above);
    3. the next round reviews the result.

    The loop stops when:
    - a round has no actionable agreed finding (pass);
    - a round applied nothing (every action skipped or failed — another round would
      see the same set);
    - `plo_review_max_rounds` rounds have run.

    The last stored review is the one shown, with its unresolved findings as the
    comments. Every round's actions go to the trail with a round number.
13. **Guard against merge drift.** Phase 4's live runs merged more on every
    review (9 → 8 → 7 PLOs), and a loop would carry that further:
    - **Merged PLOs are not merged again.** Within one loop, a PLO written by a
      redundancy merge in an earlier round is not merged again. The finding is
      recorded `skipped` ("PLO นี้เพิ่งรวมมาในรอบก่อน").
    - **Floors stay.** The existing floors (`MIN_CORE_AFTER_MERGE`, `MAX_GROUP_SIZE`) still
      hold.
14. **New review checks**:
    - **Alignment (new finding kind `AlignmentFinding`).**
      - Per PLO, the reviewer judges whether the statement answers what its cited
        Needs ask, given their sentences and voice counts.
      - The dossier gains `Need.stakeholder_coverage` (type → count) for each cited
        Need.
      - Nothing else is added: no evidence text, no rationale and no skill names.
        The information-bias rule in `.claude/rules/plo-review.md` stands, and its
        prompt-absence test is extended.
      - Send-back: redraft the PLO from its own Needs with the reviewer's
        recommendation as the note.
    - **Redundancy:** unchanged.
    - **KSEC coverage of the set.**
      - Code already counts PLOs per category. A category with zero PLOs is a code
        fact, not a vote.
      - Send-back drafts a PLO from the highest-`demand_score` unused, written,
        in-scope Need tagged with that category, under the existing ceiling.
      - When no such Need exists, it records `skipped` ("ไม่มี Need หมวดนี้ — ต้องเพิ่มที่ขั้น Need"). That is a comment for the designer.
      - Per-PLO KSEC suggestions stay advisory: a PLO's KSEC comes from its Needs.
    - **Verb and Bloom.**
      - `BloomFinding` gains an optional `suggested_verb_th`. The review prompt asks
        whether the verb fits the work and the degree level, not only the level.
      - The vote on the verb is a plurality among runs that agreed on the finding.
      - Send-back redraft note names the level and the verb.
      - Acceptance still requires the suggested level when one is given. The verb is
        guidance, and the SMART checks govern it.
    - **Unused Need `consider`:** unchanged.
    - **Order within a round:** redundancy → alignment → Bloom/verb → KSEC gap → unused Need.
15. **Graph and stages.**
    - **New tail:** `plo_synthesis → plo_review → review_plos_node → plo_report → END`.
      `DESIGNER_STAGES` becomes `… plo_synthesis, plo_review, plo_report`, and the
      frontend rail follows.
    - **Checkpoint.** `review_plos_node` maps to stage `plo_review`. The designer
      approves on the review page, which shows the set, the trail of every round
      and the open comments.
    - **Resume reloads the PLOs.** On resume, `review_plos` **reloads the PLOs from
      the DB**, as `review_needs` already does. Today it does not, so `plo_report`
      upserts the checkpoint's stale copy over any edit the designer made while
      suspended. That is a live bug the new placement would make worse.
16. **The report becomes an artifact.**
    - `plo_report` stores its result in a new `plo_reports` row: program, PLO
      fingerprint, created_at and the report JSON. The rail can then say
      "approved and reported".
    - `stage_reached` returns `plo_report` when a report exists for the current
      set, then `plo_review` for a current review, then `plo_synthesis`.
    - Lifecycle: cleared with the program's PLOs, copied by a full copy, not by
      `evidence_only`.
    - It still re-persists nothing but what is stored.
17. **REST (page-by-page) path:**
    - `POST /plos/run` chains the review job on success, as `/needs/run` chains
      Agent 2, so synthesis → review runs as one tail without a checkpoint between.
    - `/plos/review/run` runs the whole loop.
    - `/plos/report/run` stays the designer's button and is the page-by-page
      equivalent of approving.
18. **Loop shape: the last step is always a review.**
    - The round cap counts send-backs. The loop runs at most 6 reviews with 5
      send-backs, so the set the designer approves always has a current
      review, and the rail shows `plo_review`.
    - SMART counts the same way: it is judged at most 4 times (the initial
      judging plus 3 repairs).
19. **Need-level actor/scope failures are not repaired.** Immutable rule 5 already
    forbids repairing a PLO whose actor or scope fails because the *Need itself*
    is institutional or out of scope. Rewording cannot fix that.
    - **Repair instruction.** A majority failure of `A_ACTOR` or `A_SCOPE` stays
      a comment and never enters the repair instruction.
    - **Comment.** The representative run's diagnosis is kept, the "send back to
      the Need stage" text included.
20. **A repair never makes a PLO worse on the hard check.** A repair that adds a
    hard failure the previous statement did not have is discarded.
    - The previous statement stays, and the attempt still uses up its round.
    - A soft criterion can therefore never cause an escalation.
21. **"Voices" are distinct evidence items per stakeholder type.** The alignment
    dossier needs this count, not `Need.stakeholder_coverage`, because that
    field counts member skill rows: one employer document naming three skills
    reads as "3".
    - The count is computed in code from the Need's members' evidence ids and the
      evidence rows' `stakeholder_type`.
    - The phrase "จำนวนผู้ขอ" means this count everywhere else in the code too.
22. **Timeouts keep what was judged.**
    - **Per-PLO timeout.** When a PLO's SMART loop times out, the last fully judged
      statement is stored with that round's verdicts. If no round completed, the
      PLO is stored `code_only`, as today.
    - **Whole review loop.** The loop has its own budget,
      `plo_review_loop_timeout_seconds` (5400, sized for 5 send-backs; the live measurement re-sizes it). When it runs out, the round in
      progress is abandoned. Its writes are kept: every redraft is already a
      complete replace with a trail row. A final review of the stored set then runs
      under the normal review timeout.
    - **Session.** A timeout is a stop reason recorded on the trail, never a
      failed session.
23. **The KSEC gap acts only inside the agent loop.** With send-back off or
    the review `code_only`, nothing is sent back, the gap included. A gap with
    no eligible Need is a comment, not an actionable finding, so it does not
    keep the loop running.
24. **(designer, 2026-11-04) A PLO the designer edited by hand is never
    rewritten automatically.** Its findings still appear as comments.
    - **Builder's mechanics.**
      - `PUT /plos/{id}` with a changed statement sets a new persistent
        `designer_edited_at` on the PLO. The existing
        `smart_validated_by="stale"` is not enough, because a revalidate
        overwrites it.
      - The send-back actions skip any finding that would replace such a PLO,
        with the trail reason "PLO นี้ผู้ออกแบบแก้เอง — ไม่เขียนทับ". This covers a
        redundancy that names it, an alignment or Bloom redraft, and a KSEC or
        unused-Need draft whose Needs it cites.
      - The voted SMART loop judges such a PLO and stores its verdicts, but does not
        repair it (`revalidate` included).
    - **What clears the marker.** The marker goes with the row: a PLO the designer
      replaces through `from-needs` is a new draft without it. Nothing else clears
      it.
25. **Docs.** CLAUDE.md immutable rules 5 and 7 and `.claude/rules/plo-review.md` /
    `smart-gate.md` / `api-data.md` are updated to say this, with the
    designer's date.

## Goals

- The report the designer reads is the set after every agent and the designer's
  approval.
- No SMART soft verdict and no review finding acts unless 3 of 5 runs agreed on
  it.
- Every automatic change, in every round, has a trail row; what could not be
  fixed reaches the designer as a comment, not silence.
- One measured live run on the copy DB (`curriculum_phase1`) reports calls,
  tokens and time of the new tail from the usage panel, against the phase 5
  baseline, written to `.scratch/reports/`.

## Non-goals

- Thai language quality check (designer dropped it).
- Renaming agents, removing the Need or evidence checkpoint.
- Batching the review for very large sets.
- Restoring a superseded PLO.

## Anti-goals

- A soft verdict that escalates a PLO, or an agent that clears a hard failure.
- A loop that keeps merging PLOs round after round.
- An automatic change without a trail row, or a failure in the loop that fails
  the session (a failed round ends the loop; the session continues to the checkpoint).
- The reviewer seeing evidence text.
- A report generated before the designer approved the set (graph path).

## Risks

- **Cost and time.** SMART goes from one run per PLO to five per round, up to
  four judging rounds (initial + 3 repairs), and each review round redrafts
  through it. The worst case is roughly 20× today's SMART calls. The usage panel
  measures it; if the live run is unacceptable, `validation_runs` and
  `plo_review_max_rounds` are the knobs.
- **Oscillation.** A Bloom redraft can be undone by a later round's alignment
  finding. The round cap and the "applied nothing" stop bound it, and the trail
  shows it.
