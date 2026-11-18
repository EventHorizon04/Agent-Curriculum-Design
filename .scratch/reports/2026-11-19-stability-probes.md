# Phase-1 stability probes (2026-11-18/19)

Two questions were left open after the relock (`docs/research/locks/2026-11-16-phase1-relock.md`):

1. The SMART repair ceiling of 5 was never reached in the relock runs. What happens when a PLO really spends all five?
2. Every run so far used one model (`z-ai/glm-5.3-flash`). Does the locked system keep its shape on the other two research models?

Both probes ran on the copy DB `curriculum_phase1` with `LLM_CACHE_ENABLED=false`, at commit `71331e8`. That commit is the tag's system: nothing after the tag touched a prompt, slot, token cap, temperature or code constant.

## 1. SMART repair ceiling (GLM 5.3 flash)

**Setup.** The script `smart_ceiling_probe.py` (scratchpad) made a full copy of `program-run-17` as `program-probe-smart` and called `validate_and_build` directly on 9 drafts at once. Concurrency was bounded by `validation_max_concurrent_plos` (8), as in a synthesis run.

- **Group A (6 PLOs).** These are the stored PLOs. `M_assessable` was forced into every round's repair list by patching `repairable` per task. Each PLO therefore had to spend all 5 repairs, with real judge and repair calls.
- **Group B (3 drafts).** These were written to fail hard checks, and nothing was forced:
  - `BAD1` and `BAD2` use a forbidden word.
  - `BAD3` declares a verb that does not open the sentence.

**Result.**

| group | PLO | repairs | judged rounds | escalated | wall (s) |
|---|---|---|---|---|---|
| A | PLO1 | 5 | 3 | no | 219 |
| A | PLO2 | 5 | 3 | no | 266 |
| A | PLO3 | 5 | 5 | no | 218 |
| A | PLO4 | 5 | 2 | no | 106 |
| A | PLO6 | 5 | 4 | no | 248 |
| A | PLO7 | 5 | 5 | no | 325 |
| B | BAD1 (`M_forbidden`) | 1 | 2 | no | 210 |
| B | BAD2 (`M_forbidden`) | 1 | 2 | no | 231 |
| B | BAD3 (`S_verb`) | 1 | 2 | no | 145 |

- **Ceiling.** The loop stopped at exactly 5 repairs on every forced PLO. No PLO escalated.
- **Rounds.** Judged rounds are fewer than 6 because a repair that returns the same statement and verb, or that is discarded, is not judged again (`_voted_loop`).
- **Time.** The slowest PLO took 325 s with 9 loops sharing the endpoint. That is 54% of `validation_timeout_seconds` (600). No PLO hit the deadline path.
- **Discard rule.** It fired once: a PLO4 repair introduced `S_verb`, and the previous statement stayed (decision 20).
- **Real hard failures.** Each of the three was fixed by the first repair.
- **Cost.** 532 calls, 63 of them failed (12%, the same rate as the relock runs). 3.79M prompt tokens and 0.44M completion tokens for 9 PLOs. A PLO at the ceiling costs about 0.4M prompt tokens, against about 2.1M for a whole multi relock run.

**Caveat: drift under repeated repair.** Five repairs that each come from a criterion the judges actually passed rewrite the sentence more than one repair does:
- PLO1's verb moved from "เจรจา" (negotiate) to "ล่าม" (interpret).
- PLO7's verb moved from "สื่อสาร" (communicate) to "นำเสนอ" (present).

Every final statement passed the hard check, and the judges flagged nothing. The forcing is artificial, though: in a real run a repair happens only when a majority of judges fail a criterion, and no relock PLO needed more than one repair. What this probe shows is that the ceiling, the deadline margin and the discard rule hold. It does not show that five repairs leave a statement close to its draft.

## 2. Other models (Qwen 3.8 flash, DeepSeek v4.1 flash)

**Setup.** The designer chose M2 = `qwen/qwen3.8-flash` and M3 = `deepseek/deepseek-v4.1-flash-1017` on 2026-11-18. M3 is a dated snapshot, so a later lock names a fixed model.

Each model got its own copy-DB backend with `PIPELINE_PROVIDER=openrouter` and `PIPELINE_MODEL=<model>`. The startup line confirmed that all eight slots resolved to the model under test.

Each run is an `evidence_only` copy of `program`, the same input as the lock runs, run with no designer action through Needs, PLOs and the report (`model_smoke.py`, which reuses `relock_runs.summary`). The pass criteria are the lock's:
- every job succeeded
- 6–10 core PLOs
- every PLO cites Needs and evidence
- no PLO is `smart_escalated`
- in single mode, both halves also stop `finished` with no unread evidence

| model | mode | program | pass | Needs | PLOs (core) | escalated | prompt tokens | calls (failed) | wall |
|---|---|---|---|---|---|---|---|---|---|
| Qwen 3.8 flash | multi | program-run-18 | yes | 10 | 9 (9) | 0 | 1.16M | 314 (9) | 1375 s |
| Qwen 3.8 flash | single | program-run-20 | yes | 6 | 6 (6) | 0 | 0.84M | 61 (1) | 742 s |
| DeepSeek v4.1 flash | multi | program-run-19 | yes | 13 | 7 (7) | 0 | 2.14M | 503 (31) | 1696 s |
| DeepSeek v4.1 flash | single | program-run-21 | yes | 9 | 9 (8) | 0 | 1.36M | 84 (1) | 401 s |

All four runs passed. In every multi run, no PLO needed more than one SMART repair.

**What passing does not cover.** These are differences in quality, which is what phase 2 measures, not breakage:
- **Qwen single.** It finished on exactly 6 core Needs, the `MIN_NEEDS` floor, and only one of them cites requirement evidence (no requirement evidence was left uncited). Two Bloom labels are doubtful: "แปล" is labelled `evaluate`, and so is "สื่อสาร".
- **DeepSeek single.** Several `action_verb_th` values are phrases ("จัดทำโครงงานการแปล", "ดำเนินธุรกิจ"). The verb table does not recognise them, so the hard check passes them by design. "ปรับแก้" and "แปล" are labelled `evaluate`. Single mode has no vote, so nothing second-guesses these labels.
- **Qwen multi.**
  - Four of its nine PLOs are `understand`-level, more than any other run.
  - PLO5 is a seven-word statement ("สื่อสารข้ามวัฒนธรรมในบริบทธุรกิจไทย-จีน") that no judge flagged.
- **DeepSeek multi.** Its review loop ran 1335 s, against 784 s for Qwen and about 330 s for GLM in the 2026-11-15 UI run. It stayed inside `plo_review_loop_timeout_seconds` (5400).

## Conclusion

- **Ceiling.** The repair ceiling of 5 behaves as designed with the real model, with enough time margin to spare.
- **Other models.** The locked system runs end to end on both research models in both modes, with no format failure, no broken trace and no escalation.
- **Not yet shown.** Each model has one run per mode. The lock standard was three in a row, so stability across runs on M2 and M3 is not yet shown.
