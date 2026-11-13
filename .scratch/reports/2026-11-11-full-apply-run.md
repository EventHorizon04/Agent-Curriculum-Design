# Full pipeline run with `apply` as the default, after the EC rule (2026-11-11)

## Setup

- **Program:** `program-run-5`, an evidence-only copy of `program`, on the copy DB `curriculum_phase1` and backend :8011.
- **Code:** commit 8a508b4, with the defaults:
  - `plo_review_loop_mode=apply`;
  - the extraction bound;
  - the graduate-side EC clustering rule;
  - every slot on OpenRouter `z-ai/glm-5.3-flash`.
- **Calls:** `POST /needs/run` (Agent 1 → Agent 2), then `POST /plos/run` (synthesis → review loop).
- **Cache:** extraction was cold. Clustering was cold too, because the contract changed with the EC rule.

## Time and cost

| step | wall s |
|---|---|
| Agent 1 (extraction + grouping) | 61 |
| Agent 2 (need combination + dedup) | 69 |
| PLO synthesis (voted SMART) | 457 |
| review loop (apply) | 747 |
| **total** | **1,334 (≈22 min)** |

**Totals:**
- 261 calls, 24 of them failed (instructor retries).
- **1.78M prompt tokens.** That is 4.3× the phase-5 baseline (414k), and lower than the earlier guarded apply run (2.40M, `2026-11-06-phase6c-loop.md` §5).

**Per slot:**
- Validation: 173 calls, 1.28M prompt tokens (72%).
- Review: 30 calls, 250k.
- `need_combination`: 20 calls, 5 failed.
- Synthesis: 13 calls, 1 failed. That is a lower retry rate than in the earlier runs (31-37%).

## The two checks from the final review

### 1. Did `need_dedup` fold the EC Needs back together?

Partly.
- Grouping produced three EC-family groups along the rule's dimensions:
  - work quality and accountability, `[EC]`, 4 names;
  - ethics, culture and people. Its members were all E, so `resolve_need_ksec` tagged it `[E]`, 4 names;
  - adapting, lifelong learning and entrepreneurship, `[EC]`, 10 names.
- The dedup vote then merged the first two into one Need, `[E+EC]`: "ประเมินความถูกต้องของงานแปลและงานล่ามร่วมกับความเหมาะสมทางวัฒนธรรม…".
- The review loop's redundancy merge (round 1) folded that PLO together with the legal and technical-accuracy S outcome. The result is PLO2 `[E+EC+S]`.

**Net:** the attitudes reach the final set as two outcomes:
- PLO2, accuracy plus cultural appropriateness of the work;
- PLO3, adapting to technological and social change.

Without the rule there would be one grab-bag. Two of the three dimensions were folded downstream.
- Folding work quality with cultural ethics is a defensible call for a translator: both are about the quality of the rendering.
- Folding PLO2 into a legal-accuracy S outcome is the same kind of judgement.

Both folds are recorded (merged Need originals, `superseded_plos`, the trail), so the designer can split them.

### 2. Did an extra EC Need push an S Need out of the top 10?

No.
- After the merges there were 10 active core Needs and synthesis drafted 8 PLOs.
- The two Needs left out are an S Need (0.11, language services and partner networks) and an EC Need (0.08, building cooperation networks). They were left out on scope ("Need นี้ยังไม่มีประโยคหรืออยู่นอกขอบเขตหลักสูตร"), not on the ceiling.
- Every in-scope S Need got a PLO.

## Review loop (apply)

| round | actions |
|---|---|
| 1 | Redundancy PLO2+PLO4 merged into PLO2. The alignment finding on PLO4 was skipped, since that PLO was already replaced this round. |
| 2 | Alignment applied to PLO2, its first. Bloom applied to PLO8 ("บริหารจัดการ" → "จัดการ", renumbered PLO4). The unused Need was skipped (out of scope). |
| 3 | The alignment finding on PLO2 was skipped by the decision-28 guard ("แก้ความสอดคล้องไปแล้วในรอบก่อน"). The unused Need was skipped. Stop: "รอบนี้แก้อะไรไม่ได้ — หยุด". |

**Final set:**
- 7 core PLOs, inside the 6-10 band.
- 0 escalated, 0 soft flags, all judged by the agent.
- The guard fired as designed in round 3, so no second alignment redraft happened.

## Final PLOs (opening words)

1. `[K+S]` แปลและตรวจแก้คำแปลไทย-จีน… โดยใช้เครื่องมือ AI
2. `[E+EC+S]` ประเมินความถูกต้องและความเหมาะสมทางวัฒนธรรมของงานแปลและงานล่ามไทย-จีน…
3. `[EC]` ปรับตัวต่อความเปลี่ยนแปลงของเทคโนโลยีและสังคม…
4. `[S]` จัดการงานแปลและงานด้านภาษา โดยใช้ทักษะดิจิทัล…
5. `[S]` ล่ามบทสนทนาในสถานการณ์เจรจาไทย-จีน…
6. `[S]` ปฏิบัติงานธุรกิจไทย-จีน…
7. `[S]` ออกแบบและสร้างสรรค์คอนเทนต์และผลงานสื่อสารสองภาษา…

## Reading

- The pipeline runs end to end on the new defaults in about 22 min, and costs less than the earlier guarded apply run.
- The EC rule survives to the PLOs only in part. The dedup vote and the review's redundancy merge each fold one EC dimension into a neighbour.
  - That is the merge machinery working as designed, not a defect.
  - If the designer wants the three attitude dimensions kept apart, the lever is the dedup or review merge criteria, not the clustering prompt.
- One run only. Run-to-run variance at every stage is large (see the 2026-11-11 extraction note), so none of these counts is a stable estimate.
