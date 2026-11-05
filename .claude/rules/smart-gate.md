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
  and marks an edited statement `stale` rather than letting it inherit the old
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
