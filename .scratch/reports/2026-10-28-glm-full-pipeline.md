# Full pipeline on GLM (every slot z-ai/glm-5.3-flash): 2026-10-28

- Branch: `feat/four-agent-pipeline` at 6fed282.
- Database: the copy `curriculum_phase1`, program `program`.
- Cache: `llm_cache` was cleared before every run.
- Driver: `full_run.py` in the session scratchpad. It calls `POST /needs/run`, which chains Agent 1 into Agent 2, then `/plos/run`, `/plos/report/run` and `/plos/review/run`.

## Runs

| Run | Change before the run | Result |
|---|---|---|
| 1 | GLM pair made the default (610f5dc) | Agent 1 timed out. Extraction took 240 s. The S-graduate clustering call took 234 s, and the 300 s grouping budget ran out on the third call. |
| 2 | Clustering reasoning bounded to 1024 (52ce022) | Agent 1 timed out in **extraction** at 300 s. Extraction time varies from run to run. |
| 3 | Job step budget raised to 900 s (617bf43) | Completed, but unusable: Need calls ended `finish_reason='length'` ×15 and 4 of 12 Needs fell back; PLO1 lost, see below; 4 core PLOs. |
| 4 | Need/PLO calls capped (6fed282) | **Completed cleanly.** See below. |

PLO1 in run 3: the draft call had no `max_tokens`. GLM looped while writing the JSON and produced 131,072 tokens with no reasoning. Instructor retried twice more (131,078, then 262,150 tokens), so PLO synthesis took 79 min and PLO1 was lost.

The fix in 6fed282:
- **Need sentence and merged Need:** the output cap rises from 2048 to 4096, and reasoning is bounded to 1024.
- **PLO draft and repair:** the output cap is 4096, and reasoning is bounded to 1024.

## Run 4

| Step | Wall time |
|---|---|
| Agent 1: extraction (86 skills) and grouping (15 groups) | 269 s |
| Agent 2: Need sentences, dedup and merge | 66 s |
| PLO synthesis and SMART | 144 s |
| Report | 0 s |
| plo_review (5 runs, 5 succeeded) | 48 s |
| **Total** | **531 s** |

- **Truncations:** zero (`finish_reason='length'` ×0).
- **Dedup:** 5 groups proposed, 5 accepted, 5 merged, 3 of them multi-tag (`core_needs=13->10`). No merged sentence failed.
- **Needs:** 10 active. All of them are real sentences; none fell back.
- **PLOs:** 7 core, inside the 6-10 band. SMART escalations: 0.
- **SMART validation:** 4 of 7 PLOs (PLO1, PLO2, PLO3, PLO7) ended `code_only` because the agent used up its 8-turn budget. It spent the turns on reading tools and never called Finish, so those PLOs carry no soft verdicts.
- **plo_review findings:**
  - Redundancy between PLO2 and PLO3 (both fix translations).
  - Redundancy between PLO4 and PLO5 (the agent notes they differ in role).
  - PLO7 should be Bloom `create`; the set has no `create` outcome at all.
  - PLO4 and PLO5 should be tagged S only, not K+S.
  - Three unused Needs are institution-level and can be left out.

## Open

1. ~~The SMART agent exhausts its 8-turn budget on GLM in 4 of 7 PLOs.~~ Addressed in f7391d6; see "SMART agent after f7391d6" below.
2. Extraction takes 240-430 s per run. That is acceptable for now, since time is not a concern on this branch, but phase 5 still has to deal with it.
3. Grouping quality under the reasoning bound: read group by group below. Group counts were 18 for GLM before the bound, 10 for llama and 15-16 for bounded GLM.
4. One run only. The figures above are a signal, not a statistic.

## Grouping quality, run 4 (bounded GLM): the experimenter's reading

15 groups, of which 11 are graduate groups. The budget was EC=2, K=1, S=7.

Coherent groups (one main task and object):
- **S: AI post-editing** (9). Every member is about controlling or fixing AI translation output.
- **S: legal and contract translation** (5).
- **S: interpreting at the negotiation table** (4).
- **S: translation accuracy and analysis** (5).
- **S: digital-marketing content** (5).
- **Institutional groups** (curriculum management, international networking, AI in teaching) stay separate from the graduate groups, as intended.

Weak groups:
- **EC #1** (10) is a grab-bag of generic attributes: leadership, lifelong learning, internationalisation, labour-market readiness. One member, "การพิจารณาความต้องการของผู้มีส่วนได้ส่วนเสียตามแนวทางของแผนพัฒนาฯ", is institutional work, not a graduate attribute.
- **S: entrepreneurship** (10) mixes entrepreneurship with generic items ("การปฏิบัติงานได้จริง", "การคิดเชิงกลยุทธ์").
- **K** (5) has no single object. Its members are cultural interpretation, knowledge transfer, human-AI work, labour-market awareness and consumer culture.
- **K singletons** (2). Each became a 1-skill group. Agent 2's dedup then merged both into K+S Needs (business negotiation, interpreting), which is the multi-tag merge working as designed.

**Verdict.** Under the bound, GLM groups the core professional skills (S) coherently. The weak groups are the generic EC and K buckets, where there is no single object to group around. These groups were not compared item by item with the llama run or the unbounded GLM run, so this is no evidence for or against a regression caused by the bound.

## SMART agent after f7391d6 (2026-10-29)

**Change.** Each observation now carries a "N turns left" note when 2 or fewer turns remain. When the 8 turns run out with no Finish, the agent gets one more call whose schema allows only `Finish` (reason `finished_at_budget`). If that call fails as well, the old `code_only` fallback still applies.

**Re-runs.** The PLO stage alone was run 3 more times on the run-4 Needs (`plos/run` → report → review):

| Run | PLO synthesis | Finished by the agent | Turns used | Closing call used | Soft flags |
|---|---|---|---|---|---|
| 5 | 254 s | 7/7 | 4-6 | 0 | PLO4 A_scope |
| 6 | 289 s | 7/7 | 2-7 | 0 | none |
| 7 | 235 s | 7/7 | 4-7 | 0 | PLO4 A_scope; PLO7 A_level, A_scope |

- **Outcomes.** Across the three runs, 21 of 21 PLOs ended with the agent's own Finish, with 0 `code_only`, 0 escalations and 0 lost PLOs. Run 4 had 4 of 7 `code_only`.
- **Reasoning runaway.** Three PLO steps reasoned up to the 4096-token step cap without answering. The existing bounded re-ask recovered all three.
- **What is not shown.** The closing call never ran live; it is tested by unit tests only. The Finishes at turn 7 (PLO1 and PLO4 in run 6, PLO4 in run 7) came after the turns-left note appeared. Run 5 finished early without any note, though, so the drop from 4 of 7 `code_only` to 0 of 21 cannot be credited to the change alone. GLM's run-to-run variance explains part of it.
- **Soft verdicts.** PLO4 (A_scope) was flagged in 2 of 3 runs. PLO7 (A_level) agrees with plo_review, which also asks for `create`.
