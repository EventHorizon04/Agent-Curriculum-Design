# Phase 6b: voted SMART loop, measured against the baseline (2026-11-05)

Copy DB `curriculum_phase1`, backend :8011, branch `feat/four-agent-pipeline` at 25da730
(6a + voted SMART loop; review still phase 4's single send-back). Every slot on OpenRouter
`z-ai/glm-5.3-flash`. Program `program-run-8` = fresh full copy of `program`, then
`POST /plos/run` (which now chains the review job). Usage from `llm_usage`.
Baseline: `.scratch/reports/2026-11-04-phase6-baseline.md` (`program-run-7`).

## 1. Cost and time

| job | baseline wall s | 6b wall s | baseline calls (failed) | 6b calls (failed) | baseline prompt tok | 6b prompt tok |
|---|---|---|---|---|---|---|
| plo_synthesis (draft + SMART) | 164.0 | 415.3 | 48 (3) | 179 (11) | 296,838 | 1,266,324 |
| plo_review (+ send-back) | 76.4 | 483.1 | 17 (0) | 88 (8) | 116,929 | 626,159 |
| **total** | 240.4 | 898.4 | 65 (3) | 267 (19) | 413,767 | 1,892,483 |

- **Overall:** 4.6× the prompt tokens and 3.7× the wall time.
- **Synthesis:** 6.9 min, 4.3× the tokens. Both are inside the plan's gate (15 min / 6×), so no knob was changed.
- **Validation slot:** 240 calls (11 failed, 5%), 1.78M prompt tokens.
- **Synthesis slot:** 22 calls, 8 of them failed (36%). These are instructor retries on draft and repair calls. That is high and worth watching in 6c, where every redraft goes through it.
- **Why the review job is now 5.4× the baseline:** the review itself is unchanged (5 calls). The cost is the Bloom redraft of PLO5. It went through 3 voted SMART rounds (5 + 5 + 3 runs, 2 repairs) and was then refused for missing the level. This is the "redrafts cost more than reviews" risk from the baseline report, now measured: one redraft costs about as much as the review it came from.

## 2. What the vote did

Judge rounds per PLO in synthesis:

| PLO | rounds | runs used | majority-failed soft | hard | repairs |
|---|---|---|---|---|---|
| PLO1, 3, 4, 6, 7, 8 | 1 | 3 (early stop) | — | — | 0 |
| PLO2 | 1 | 5 (split) | — | — | 0 |
| PLO5 | 1 | 3 | A_scope | — | 0 (A_scope is not repaired, decision 19) |
| PLO9 | 2 | 5 + 3 | — | M_forbidden | 1 (fixed) |

- **Early stop worked as estimated:** 7 of 9 PLOs stopped at 3 runs.
- **PLO5, the case the baseline used to argue for voting, is now caught.**
  - Stored with `soft_flags=['A_scope']`: "บริหารจัดการและวางแผนกลยุทธ์ทางธุรกิจเพื่อปฏิบัติงานในภาคธุรกิจไทย-จีน", a business-management outcome in a translation program.
  - In the baseline, the single run passed it on every criterion.
  - The flag is a comment for the designer and is not repaired, because the Need itself is outside the profession.
- **PLO9:** a hard M_forbidden failure was repaired in one round and re-judged clean.
- **No PLO escalated.**

## 3. Review and send-back (still phase 4's single round)

- **Review:** 5/5 runs usable, threshold 3.
- **Agreed findings:**
  - Redundancy PLO3+PLO6 (4/5): applied, giving the merged PLO3. The set went from 9 to 8 PLOs.
  - Bloom PLO5 → create (3/5): the redraft ran 3 SMART rounds and did not land on create, so it was skipped ("ร่างใหม่ไม่ได้ระดับ Bloom ที่ขอ — คงข้อเดิมไว้").
  - Two unused Needs marked `consider` (5/5 and 4/5): both skipped as unwritten or out of scope.
- **Same shape as the baseline:** the same pair merged and the same 9 → 8 set.

## 4. Stability of the final set (single-run judgments, 5 each, repairs off)

| PLO | soft failures over 5 single runs |
|---|---|
| PLO1, 3, 4, 7, 8, 9 | none (unanimous pass) |
| PLO2 | A_level 2/5 (below the 3/5 bar, not flagged) |
| PLO5 | A_scope 5/5, A_level 4/5, M_assessable 1/5 |

- **The stored verdicts agree with what a fresh 5-run majority says.** PLO5 is flagged A_scope and the others are clean.
- **PLO2's split** on A_level (2/5) is the same split the review showed (Bloom PLO2 → create, 2/5). Both votes kept it below the bar.
- **Probe cost:** 40 judgments, 408.6 s wall time.

## 5. Going on to 6c

- **No knob changed:** `validation_runs` stays 5, and so do the concurrency settings.
- **Cost risk for 6c is the redrafts.** Each review round that applies a redraft pays a voted SMART loop for it. PLO5's refused Bloom redraft alone cost more than the review. The loop's "applied nothing → stop" rule bounds a set where every redraft is refused.
- **Synthesis-slot retry rate (36%)** is watched in the 6c run.
