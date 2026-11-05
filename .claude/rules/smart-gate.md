---
paths:
  - "src/curriculum_agent/stages/smart_*.py"
  - "src/curriculum_agent/smart_vocabulary.py"
  - "src/curriculum_agent/stages/bloom_verbs.py"
  - "src/curriculum_agent/stages/plo_synthesis.py"
  - "src/curriculum_agent/prompts/smart_agent.py"
  - "src/curriculum_agent/prompts/stage_3_plo.py"
  - "src/curriculum_agent/api/routes/plos.py"
  - "src/curriculum_agent/models.py"
  - "tests/**/test_smart*.py"
---

# SMART gate and PLO statement pitfalls

Moved out of the root CLAUDE.md so it loads only when working on the files above.
These are standing project rules, not suggestions — same weight as CLAUDE.md.

- **The agent cannot pass itself, and `hard_failures` after the loop is why.**
  `validate_and_build` re-runs the pure checks on the final statement on every
  exit path — finished, out of budget, endpoint down — and that call sets
  `smart_escalated`. Delete it and immutable rule 5 becomes a request the model
  can decline: `Finish` has no field that clears a hard failure precisely
  because nothing downstream would notice if it did. `Finish` has no
  `statement_th` for the same reason (and no repair action: since phase 6 a repair
  is decided by the vote over `validation_runs` judge runs plus `hard_failures`,
  not requested by one run) — the Thai a designer submits to MHESI
  comes from the synthesis slot, always, and a helpful model handed that field
  would make "a repair is never answered by a different model than wrote the
  draft" one field away from false.
- **The judge, the vote and the repair are three separate things, and only the
  vote's outcome plus the hard check may start a repair (phase 6, designer's
  decision of 2026-11-04).** `run_smart_agent` -> `_voted_loop`: a round is
  `validation_runs` judge runs of the *same* statement (`_judge_round`; each seeds
  its own `ToolBudget`, ending in `Finish`, under the shared judge semaphore), then
  `smart_vote.vote` counts them, then `hard_failures` runs on the statement. A soft
  criterion fails when `n // 2 + 1` of the runs *requested* failed it; failed runs
  do not lower the bar, the rule `plo_feedback` already uses. Why not "3 runs each
  pass the whole thing": five runs flagging five different criteria would fail the
  PLO with nothing a majority agreed to fix, and the loop would rewrite at random.
  Why not five runs that each repair: five different statements and nothing to
  vote on, so judging is parallel and the repair is one call. Early stop
  (`first_batch_size`, `is_decided`): 3 runs first, and the other 2 only when the
  first 3 leave a criterion open, which gives the same answer as always running 5
  (7 of 9 PLOs stopped at 3 on the measured run). The repair instruction is built in
  code (`build_vote_repair_instruction_th`) from the hard failures' fix hints, the
  majority-failed repairable criteria with the representative run's note, and that
  run's **`repair_hint_th`**, `Finish`'s one new field: advice about *what* to
  change and never a sentence (see the first bullet). The representative run is the
  one whose failures best match the vote (most majority criteria, fewest extras,
  earliest on a tie), so its diagnosis and notes describe the verdict stored.
  `repair_count` is spent when a repair is *attempted*: a failed call, a discarded
  repair and an unchanged one are budget used, or a stuck PLO would loop on the same
  sentence. At most `validation_max_repairs` (3) repairs, so at most 4 judgings.
- **A repair never makes a PLO worse on the hard check, and `A_actor`/`A_scope` are
  never repaired.** A repaired statement that carries a hard failure the previous
  one did not is discarded and the previous statement stays (decision 20 of docs/superpowers/specs/2026-11-04-four-agent-pipeline-phase6-design.md), which
  is what keeps a soft criterion from ever causing an escalation. `A_actor` and
  `A_scope` (`smart_vote.REPAIR_EXCLUDED`) stay comments even when a majority fails
  them: both are properties of the *Need* (an institutional or out-of-scope Need),
  rewording cannot change them, and a repair spent on them is budget taken from the
  hard failures; the stored diagnosis keeps the "send back to the Need stage" text.
  A soft criterion failing by majority after the last repair is stored in
  `soft_flags` and the `SMARTCheck` field with the representative's note; those are
  the comments the designer reads, and `smart_escalated` stays hard-only.
- **A round that could not vote uses no soft verdict, and a timeout keeps what was
  judged.** Fewer successful runs than the threshold means `vote` returns `None`:
  no flag is manufactured and only hard failures drive repair; a PLO no round ever
  voted on is `code_only`. When the round *after* a repair cannot vote (or the
  per-PLO `validation_timeout_seconds`, 600, runs out before re-judging) the
  repaired draft ships as `code_only` only when it has strictly fewer hard failures
  than the last judged one (`_corrected_unjudged`: its failures are a subset of the
  judged one's by the discard rule, so shipping it can only shrink the list);
  otherwise the last judged statement ships with its vote. Rule 5 (a validator that
  could not run must not escalate) outranks re-judging the older, defective
  sentence. `validation_runs=1` runs the same structure with threshold 1; there is
  no separate single-run code path.
- **A designer's own sentence is judged, never rewritten (`allow_repair`).** `PUT
  /plos/{id}` with a changed statement sets `designer_edited_at`; `POST
  /plos/{id}/revalidate` passes `allow_repair=match.designer_edited_at is None`, so
  the voted loop judges such a PLO and stores its verdicts without a repair, and
  copies the stored marker onto the rebuilt row (`validate_and_build` returns a
  fresh PLO that would otherwise drop it). The marker is not `smart_validated_by=
  "stale"`: a revalidate overwrites that, and send-back must still leave the
  sentence alone. Nothing clears it except replacing the outcome.
- **Immutable rule 4 is enforced on `action_verb_th`, and a statement scan is
  what does not work.** `hard_failures` tested `action_verb_th in statement_th`
  and nothing else about verbs, so the rule was prompt text with no code behind
  it — and it broke at the field that declares the verb rather than in the
  sentence. Six of the nine stored PLOs declared a *phrase*
  ("ออกแบบและดำเนินการ", "ออกแบบและดำเนินการตรวจสอบ", "ตีความและอธิบาย"), and every
  one passed S, because synthesis writes the whole phrase into the sentence it is
  checked against. Scanning the statement instead is the obvious fix and the
  wrong one: Thai packs means and purpose into the same sentence, so
  `scan_statement_verbs` reports "โดยใช้เทคโนโลยี", "เพื่อสร้างคอนเทนต์" and the
  noun "แนวปฏิบัติ" beside the outcome verb — it flags six of the nine, four of
  them sound. The declared phrase has no subordinate clauses to mistake, and on
  it the check flags three, all genuine. **A phrase the table does not recognise
  passes**: `bloom_verbs` is a judgement call with no specialist review, its
  header says so, and a gap in a vocabulary this repo wrote alone must not
  escalate an outcome (stored OPT4 declares "ประพฤติตน"). Two verbs pass when
  *some* pair of their levels is adjacent, not every pair, because
  `levels_for_verb` returns a list exactly where the rubric says the object
  settles the level. `declares_too_many_verbs` is the only caller allowed to gate
  on that table; everything else it feeds stays advisory, and adding a verb to it
  now widens what this check rejects.
- **S checks that the statement *opens* with the declared verb, not that the verb
  appears somewhere in it.** The presence test passed a PLO that declared
  "ประยุกต์ใช้" while its outcome was "แปลและตรวจสอบเอกสาร…": the declared verb
  sat in the means clause ("โดยประยุกต์ใช้เทคโนโลยี AI"), the same Thai clause
  structure that makes a statement scan useless above. The opening is the one
  position a subordinate clause cannot take, so it is read after
  `strip_outcome_prefix` removes a "บัณฑิตสามารถ…" subject — on the stored set
  that check failed exactly the one PLO it should. The prefix itself is wording
  removed in code, not a failure: `plo_synthesis._adopt` strips it from every
  draft and repair, because it is the one door every shippable statement comes
  through, and spending one of three agent repairs on deleting a subject would
  take budget from the hard failures.
- **The opening-verb check cannot see the "ประยุกต์ใช้" wrapper, and that is
  handled in the two prompts, not in code.** "ประยุกต์ใช้"/"ใช้" is always
  apply-level, so "ประยุกต์ใช้ <resource> ในการ <real task>" opens with a verb
  that is genuinely the declared one — S passes — while the real task
  (พัฒนา/แปล/ล่าม, at another Bloom level or another profession's work) sits
  inside the "ในการ..." clause, invisible to a check that only reads the
  opening word. Stored PLOs 3, 6, and 7 all had this shape, passed every soft
  criterion on nine validator runs, and one diagnosis said a repair had
  *deliberately* moved a create-level verb into that clause to make
  "ประยุกต์ใช้" the main verb and pass `A_level` — the wrapper is how a repair
  games the level check. The fix is in `build_plo_from_need_prompt` (don't
  write the wrapper; the real task's verb is `action_verb_th` and opens the
  sentence, the resource goes in a "โดยใช้..." means clause, and this holds
  even when the Need sentence itself is wrapped) and in the SMART rubric
  (`specific_object_ok`, `scope_ok`, and `achievable_ok` all read through the
  wrapper to the real task). Not a code gate: a statement scan for "ในการ"
  would also flag legitimate means/purpose clauses, the same reason a
  sentence-level verb scan doesn't work for `S_multi_verb` above.
- **The forbidden-word check is about words *used*, not substrings.** Thai has
  no word boundaries, so `word in statement` flagged `รักษา` (holds รัก),
  `จำแนก`/`จำลอง` (จำ) and `ความรู้`/`เรียนรู้` (รู้). Each hard-failed M, burned
  all three repairs against a hint about a word the sentence never used, and
  escalated a sound outcome. `smart_vocabulary.forbidden_words_in` masks a
  curated compound list first, and both callers — `hard_failures` and
  `PLO.check_no_forbidden_words` — share it, because two independent scans of
  one rule is how they came to disagree. Don't reintroduce either the substring
  test or the second copy.
- **A verdict field is the validator's output, never a client's input.** `PUT
  /plos/{id}` used to accept a whole `PLO`, so a caller with the API key could
  set `smart_escalated=False` with an all-true `smart_check` on a statement no
  validator had ever passed. It now takes `PLOStatementUpdate` — text only —
  and marks an edited statement `stale` (and stamps `designer_edited_at`) rather than letting it inherit the old
  verdict; `POST /plos/{id}/revalidate` is the way back to a real one. The next
  person who wants a quick edit path will be tempted to widen this again.
- **`PUT` still has to run the pure-code gate, because `model_copy` skips
  validators.** Marking an edited statement `stale` is not enough on its own:
  the row is written with whatever `smart_escalated` it already had, and every
  later read goes through `PLO.model_validate`, where the forbidden-word check
  stands down only for an escalated row. So one `PUT` of a statement containing
  `เข้าใจ` wrote the row, failed FastAPI's own response validation, returned
  500, and made `GET /plos/` raise for the whole program — `revalidate`
  included, since the way back was behind the same read that was failing.
  `hard_failures` is pure code and free, so the route runs it and stores a
  verdict the model will accept on the way back in. The invariant is not "PUT
  does not judge" — it is that whatever any route stores must be readable.
- **`soft_flags` stays `list[str]`.** Narrowing it to `SmartFindingCode` makes
  any row carrying a code this build no longer knows raise on read — and
  `R_alignment` was emitted for months — so one stale string would take out a
  whole program's PLO list on `GET /plos/` rather than one field. The typed
  detail lives in `smart_check.findings`, which rides inside the existing JSONB
  column and needed no migration for exactly this reason.
