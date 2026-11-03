# Phase 5: extraction output bound, measured (2026-11-03/04)

Copy DB `curriculum_phase1`, backend on :8011, branch `feat/four-agent-pipeline` at caece5e.
Every slot on OpenRouter `z-ai/glm-5.3-flash` (branch pipeline pair). Corpus: program
`program` (14 evidence items), copied in full for each run (`POST /programs/program/copy`),
then `POST /needs/skills/run` (Agent 1 only: extraction + grouping, no chain).
Cold: `llm_cache` rows of kind `extraction` and `clustering` deleted on the copy DB before
each run. Token and latency figures are from the new `llm_usage` table (every provider
response, instructor retries included).

"Bounded" = `EXTRACTION_REASONING_MAX_TOKENS=1024`, `EXTRACTION_MAX_TOKENS=4096`.
On this endpoint a reasoning bound turns GLM's hidden reasoning off.

| run | wall s | skills | groups | K/S/E/C | extr calls (failed) | prompt tok | completion tok | of which reasoning | extr span s | clustering calls / span s / summed latency s | ungrounded dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A unbounded | 261.6 | 92 | 16 | 9/71/6/6 | 16 (2) | 65,420 | 153,189 | 136,431 | 245.7 | 6 / 1.5 / 13.4 | 0 |
| A2 unbounded | 251.6 | 89 | 13 | 9/65/6/9 | 15 (1) | 56,892 | 139,969 | 124,073 | 234.6 | 5 / 3.0 / 13.5 | 0 |
| B bounded | 51.1 | 81 | 13 | 6/58/5/12 | 15 (1) | 57,734 | 18,184 | 3,974 | 33.9 | 4 / 3.7 / 12.3 | 3 |
| B2 bounded | 50.3 | 81 | 13 | 6/58/7/10 | 15 (1) | 57,482 | 17,366 | 3,572 | 41.0 | 5 / 3.6 / 11.5 | 1 |
| B3 bounded | 40.4 | 85 | 15 | 7/65/6/7 | 15 (1) | 55,219 | 15,783 | 1,343 | 30.7 | 4 / 2.4 / 8.8 | 0 |

Earlier unbounded cold runs on the same corpus: 86 skills (phase-1 timing report), 89.

## Reading

- **Time:** Agent 1 goes from ~255 s to ~47 s (5.4×). Extraction is the whole difference:
  89% of unbounded extraction output is hidden reasoning (124-136k of 140-153k tokens).
- **Skills:** bounded mean 82.3 vs unbounded mean 90.5 → −9.1%. Every bounded run is
  below the unbounded range (86-92). The loss is in S (58-65 vs 65-71); K is slightly lower,
  E/C equal or higher.
- **Grounding:** bounded dropped 0-3 invented spans per run (mean 1.3 of ~84, 1.6%);
  unbounded dropped none. `is_grounded` removes them, so they never reach a Need.
- **Name overlap** between runs is not a usable measure: the same skill is paraphrased
  differently from run to run (e.g. "การคิดวิเคราะห์ในงานล่ามและการแปล" vs
  "การคิดวิเคราะห์ในการแปลและล่าม"), so exact-name Jaccard was 0.08 between A and B and
  would be low between two unbounded runs too.
- **Grouping concurrency** (Task 4): the 4-6 bucket calls now finish within 1.5-3.7 s of
  each other while their summed latency is 9-13 s.
- One instructor retry per run (failed=1-2) in both modes; every call succeeded in the end.

## Decision (spec decision 7 rule: bound unless it loses >10% of skills or grounding)

-9.1% skills and -1.6% grounding are both under the 10% line, so the default becomes
**bounded** (`extraction_reasoning_max_tokens=1024`, `extraction_max_tokens=4096`), with
`0` meaning "no bound" for a research run that wants the unbounded behaviour.

Not measured: whether the ~8 fewer S skills change the Needs and PLOs downstream. The
skills lost are the long tail of S (the bucket that had 65-71); a full-pipeline comparison
(Needs, PLOs, review) is the next check if the designer wants one.

Side effect: the bound is part of the extraction cache key, so existing unbounded cache
rows are not hit by the new default; the first run of each program re-extracts once.
Sweep the unreachable rows with `uv run python -m curriculum_agent.data.prune_cache --older-than DAYS`.
