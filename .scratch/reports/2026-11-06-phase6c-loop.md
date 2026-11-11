# Phase 6c: the review loop in shadow and apply mode, against the baseline and 6b (2026-11-06)

All runs used the copy DB `curriculum_phase1` and the backend on :8011. Every slot ran on OpenRouter `z-ai/glm-5.3-flash`. Each run started from a fresh full copy of `program`, then called `POST /plos/run` (which chains the review job). Usage figures come from `llm_usage`.

| run | program | code | loop mode |
|---|---|---|---|
| baseline | program-run-7 | phase 5 | phase 4 single send-back |
| 6b | program-run-8 | 25da730 | phase 4 single send-back |
| shadow | program-run-9 | 48e7be5 (before review early stop) | `shadow` (default) |
| apply | program-run-10 | a156d7a (with review early stop) | `PLO_REVIEW_LOOP_MODE=apply` (process env only) |

The final-review fixes (I1-I5, M1-M7) landed after these runs.
- **What they could have changed:** I2, the merge memory, could not have changed this run, because no PLO was merged twice. M3 changes the stop reason only. The other fixes guard rare races.

## 1. Cost and time

| run | synthesis wall s | review job wall s | total wall s | calls (failed) | prompt tokens |
|---|---|---|---|---|---|
| baseline | 164 | 76 | 240 | 65 (3) | 413,767 |
| 6b | 415 | 483 | 898 | 267 (19) | 1,892,483 |
| shadow | 647 | 67 | 714 | 197 (19) | 1,516,907 |
| apply | 469 | 1,505 | 1,974 | 432 (40) | 3,088,439 |

- **Apply, all slots: about 33 min, 7.5× the baseline prompt tokens and 8.2× its wall time.**
  - Validation: 355 calls and 2.61M prompt tokens, 85% of the total.
  - Review: 37 calls.
  - Synthesis: 40 calls, of which 15 failed (37%, instructor retries). That rate is again high.
- **Shadow is cheap after synthesis.** One review, no redraft: 67 s.
- **Synthesis varies from run to run** (415 / 647 / 469 s on the same Needs) with the voted SMART loop.
- **The review early stop never fired in the apply run.** Each of the 5 reviews logged "running 2 more (split)", so on this set early stop saves nothing for the review.

## 2. Shadow run (program-run-9): what the loop would do

- **Planned:** redundancy PLO3+PLO6 (agreed 4/5), the same pair 6b merged.
- **Skipped:**
  - The alignment findings on PLO3 and PLO6, because "PLO นี้ถูกแทนที่ไปแล้วในรอบนี้": the planned merge would replace both, and the dry run books that.
  - Two unused Needs voted `consider`, because "Need นี้ยังไม่มีประโยคหรืออยู่นอกขอบเขตหลักสูตร".
- **Stopped:** "โหมดทดลอง — ยังไม่แก้ PLO". The PLOs were unchanged, and the review is current for the set.

## 3. Apply run (program-run-10): five send-back rounds

**Round 1:**
- Alignment PLO5 and PLO6: applied.
- Bloom PLO1 → create (verb "ผลิต"): applied.
- Bloom PLO5: skipped, already replaced this round.

**Round 2:**
- Redundancy PLO2+PLO6: merged into PLO2. The set went from 9 to 8 PLOs.
- Alignment PLO3: applied.
- Bloom PLO5: applied.

**Round 3:** alignment PLO3 and PLO5 applied again.

**Round 4:** alignment PLO3 applied again.

**Round 5:** nothing agreed was actionable. The two unwritten or out-of-scope unused Needs were skipped, as in every round. Stop: "รอบนี้แก้อะไรไม่ได้ — หยุด" (with the M3 fix this reads as a pass).

**Final set:** 8 PLOs, none escalated, PLO5 still `A_scope`. The final review agreed on nothing (the best finding had 2/5) beyond the unwritable unused Needs.

**PLO5 traced through the loop.** Its Need asks for business management in a translation program.

| step | statement |
|---|---|
| synthesis | "ปฏิบัติงานล่ามและแปลเอกสารธุรกิจ… โดยใช้การบริหารจัดการ…" |
| after round 1 (alignment) | "จัดทำแผนการดำเนินงานด้านการแปลและการสื่อสาร…" |
| after round 2 (Bloom) | "ออกแบบแผนการดำเนินงานด้านการแปลและการสื่อสาร…" |
| after round 3 (alignment) | "ปฏิบัติงานในภารกิจธุรกิจไทย-จีนจริง โดยนำหลักการบริหารจัดการและการคิดเชิงกลยุทธ์ทางธุรกิจ…", A_scope flagged again |

- **This is the oscillation risk the spec named.**
  - The alignment check pulls the statement toward the Need: business management.
  - The scope check flags business management as another profession's work.
  - Rewording cannot satisfy both, because the Need itself is out of scope.
  - The loop stopped only because a later round had no agreed finding left on PLO5.
- **PLO3 was redrafted by alignment three times**, each time to cover a different part of its multi-part Need (translation, adapting to technology, responsibility).

## 4. What this means

- **The loop works mechanically.**
  - Every change has a trail row, and every replaced PLO is in `superseded_plos` (`cause=review`).
  - The cap was not reached; the loop stopped on its own after 5 rounds.
  - The session succeeded.
- **The repair loop does not converge on two kinds of PLO:**
  1. A PLO whose Need is out of scope (PLO5). The fix belongs at the Need stage (exclude the Need), which is what the comment says.
  2. A PLO whose Need asks for several things at once (PLO3). Each round's reviewers pick a different missing part.

  In both, a redraft spends a voted SMART loop (about 30-60k prompt tokens) on a change a later round undoes or redoes.
- **Cost:** apply roughly doubles 6b's tail and is 7.5× the baseline in tokens.

**Recommendation:** keep `plo_review_loop_mode=shadow` as the default (no change made). Before using `apply` for research, the designer should decide on two guards:
- (a) Do not send an alignment finding back for a PLO whose Need is flagged `A_scope` by majority. Make it a comment, as decision 19 does for SMART repair.
- (b) Allow at most one alignment redraft per PLO per loop, with later findings as comments, mirroring the merge-drift guard.

Both would have stopped this run after round 2.

## 5. Apply re-run with the alignment guard (decision 28, 2026-11-11)

`program-run-11` was run at commit 00adac6. That is phase 6, plus the final-review fixes, plus the one-alignment-redraft-per-PLO guard, plus the version-checked PUT. It used `PLO_REVIEW_LOOP_MODE=apply` and the same corpus and model.

| run | synthesis s | review job s | total s | calls (failed) | prompt tokens | send-back rounds |
|---|---|---|---|---|---|---|
| apply, no guard (§3) | 469 | 1,505 | 1,974 | 432 (40) | 3,088,439 | 5 |
| apply, with guard | 550 | 997 | 1,547 | 336 (34) | 2,398,004 | 3 (2 applied) |

**Round 1:**
- Redundancy PLO3+PLO6 was merged.
- Alignment was applied to 3 PLOs.
- Alignment on PLO3 and PLO6 was skipped, because the merge had already replaced both.
- Bloom PLO7 was applied.

**Round 2:** alignment was applied to the merged PLO3. This was its first alignment redraft, since it has a new Need set.

**Round 3:** the only finding left was the two unwritable unused Needs. Stop: "รอบนี้แก้อะไรไม่ได้ — หยุด".

**Outcome:**
- No PLO received a second alignment redraft, so the PLO3 and PLO5 oscillation of §3 did not recur.
- The final set has 8 PLOs, none escalated and none flagged.
- The A_scope outcome of earlier runs was redrafted in round 1. It came out as business communication and document work in Thai-Chinese ("ปฏิบัติการสื่อสารทางธุรกิจและจัดทำเอกสารธุรกิจในภาษาไทย-จีน…"), and the vote no longer flags it.

**Cost:**
- About 5.8× the baseline prompt tokens and 6.4× its wall time.
- That is 22% fewer tokens and 22% less time than apply without the guard.
- Synthesis-slot instructor retries are still high (10 of 32 calls).
- The review early stop again never fired (3 of 3 first batches split).

**Recommendation:** the default stays `shadow`. Whether to switch the research runs to `apply` is now a cost decision, not a stability one.
