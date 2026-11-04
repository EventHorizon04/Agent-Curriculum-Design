# Phase 6 baseline: today's PLO tail and SMART verdict stability (2026-11-04)

Copy DB `curriculum_phase1`, backend on :8011, branch `feat/four-agent-pipeline` at 776ab09
(phase 5 code; spec edits only since). Every slot on OpenRouter `z-ai/glm-5.3-flash`.
Program `program-run-7` = full copy of `program` (stored Needs), then
`/plos/run` → `/plos/report/run` → `/plos/review/run` (phase 4 send-back on).
Token and latency figures from `llm_usage`.

## 1. Today's tail

| job | wall s | slot | calls (failed) | prompt tok | completion tok | summed latency s |
|---|---|---|---|---|---|---|
| plo_synthesis | 164.0 | plo_synthesis | 11 (1) | 29,564 | 6,807 | 92.5 |
| | | validation | 37 (2) | 267,274 | 45,079 | 295.7 |
| plo_report | 0.0 | — | 0 | — | — | — |
| plo_review (+ send-back) | 76.4 | plo_review | 5 (0) | 34,305 | 23,227 | 109.3 |
| | | plo_synthesis | 2 (0) | 6,302 | 1,656 | 6.9 |
| | | validation | 10 (0) | 76,322 | 6,587 | 45.0 |
| **total** | 240.4 | | 65 (3) | 413,767 | 83,356 | 549.4 |

- 9 PLOs after synthesis, all `agent`-validated, none escalated, no soft flag; 1 repair (PLO9).
- Validation is 72% of the tail's prompt tokens (343k of 414k). One SMART judgment of one PLO
  ≈ 4 calls, ≈ 30k prompt tokens.
- Review: 5/5 runs usable, threshold 3. Agreed: redundancy PLO3+PLO6 (5/5), Bloom PLO1 →
  create (5/5), unused Need `consider` (4/5, skipped: unwritten/out of scope). Two more
  redundancy pairs had 1/5 and did not act. Send-back applied 2 actions → 8 PLOs.

## 2. SMART verdict stability (today's agent, repairs off)

Each of the 8 final PLOs judged 5 times by today's SMART agent (`validation_max_repairs=0`,
siblings = the other 7 final PLOs), nothing written to the PLO table.
Script: scratchpad `smart_stability.py`.

| PLO | runs judged | distinct verdict sets | soft criteria failed (of 5 runs) |
|---|---|---|---|
| PLO1, 2, 3, 4, 7, 8, 9 | 5 each | 1 (all pass, unanimous) | none |
| PLO5 | 5 | 3 | A_scope 5/5, S_object 4/5, M_assessable 2/5 |

- **7 of 8 PLOs: all 5 runs agree** (pass).
- **PLO5 shows why a vote matters.** The single run inside synthesis passed it on every
  criterion. Five runs fail scope 5/5 and object 4/5. It reads
  "ปฏิบัติงานในบริบทธุรกิจไทย-จีน โดยใช้การบริหารจัดการและการคิดเชิงกลยุทธ์ทางธุรกิจ", a
  business-management outcome in a translation/interpreting program.
- **Caveat on the comparison.** The contexts differ: synthesis judged it with repairs
  available and draft siblings. The probe judged it with repairs off and final siblings. The
  5/5 result is still far from "passes everything".
- **Under the phase 6 rule, PLO5 would be repaired.** S_object would enter the repair
  instruction. A_scope would not: it is Need-level, which spec decision 19 sends to comments.
  M_assessable (2/5) would not count.
- **Cost of the probe.** 40 judgments took 186 calls (23 failed, 12% — instructor retries),
  1,442,698 prompt and 239,157 completion tokens, 389 s wall at concurrency 5. That is
  ≈ 4.7 calls and ≈ 36k prompt tokens per judgment.

## 3. What this means for phase 6

- **Voting finds what one run misses.** PLO5 is the case.
- **Early-stop voting pays off here.** 7 of 8 PLOs are unanimous, so with "3 first, 2 more
  only if split" they stop at 3 runs. Estimate for this set: ≈ 26 judgments instead of 40
  for the first round (−35%).
- **Rough cost of the first SMART round of a 9-PLO set.**
  - Today: ≈ 37 calls and 267k prompt tokens.
  - With voting and early stop: ≈ 27 judgments × 4.5 ≈ 120 calls and ≈ 0.9M prompt tokens,
    about 3.3× today.
  - Repair rounds add more only for PLOs that fail.
  - Wall time for synthesis: ≈ 2.7 min today, an estimated 5-7 min with voting at the
    current concurrency.
- **The review vote is already in place.** It cost 5 calls (34k prompt) per round. A loop of
  up to 6 reviews costs little next to SMART; the redrafts it triggers cost more, because each
  redraft runs a voted SMART loop.
- **Instructor retries are not small.** 12% of validation calls failed in the probe, against
  5% in the synthesis job. The retry rate is a cost factor to watch in the 6b measurement.

Not measured: review stability across repeated reviews of the same set (one review only),
and how many rounds the loop would take.
