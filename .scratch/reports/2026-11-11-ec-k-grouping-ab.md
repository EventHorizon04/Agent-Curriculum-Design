# EC/K grouping: control prompt vs a bucket rule (2026-11-11)

This closes open item 3 of `.scratch/reports/2026-10-28-glm-full-pipeline.md`: "the generic EC bucket … a prompt-level change would need its own experiment".

## Setup

- **Inputs:** the graduate-side skills of three cold Agent 1 runs from the extraction-bound measurement: B1 and B2 bounded, U1 unbounded.
- **Targets:** the same bucket split, dedupe and `allocate_cluster_targets` targets the stage uses.
- **Model:** the clustering slot (OpenRouter `z-ai/glm-5.3-flash`), at temperature 0 with the 1024 reasoning bound.
- **Runs:** 3 repeats per arm, with the cache bypassed.
- **Script:** `ecK_ab.py` (scratch). No DB writes besides usage rows, which went to the copy DB.

**Arms:**
- **Control:** `build_cluster_skills_prompt` as shipped.
- **Candidate:** the control prompt plus one bucket rule.
  - **EC rule:** group each trait by *where the graduate shows it*:
    - the quality of, and accountability for, their own work;
    - toward people and cultures;
    - toward change and their own career.
  - **K rule:** group knowledge by what it is about, not by the verb.

## EC (targets 2; 13-16 names)

| input | control sizes (3 runs) | candidate sizes (3 runs) |
|---|---|---|
| B1 (16) | 12+4 · 5+11 · 9+7 | 5+4+7 · 5+4+7 · 5+4+7 |
| B2 (13) | 7+6 · 7+6 · 4+9 | 7+6 · 2+5+6 · 2+5+6 |
| U1 (15) | 3+12 · 4+11 · 4+11 | 4+4+7 · 4+4+7 · 5+10 |

**Control:**
- Returns two groups, as asked. Each run splits differently, and one group is always a grab-bag.
- An example label from that group: "การพัฒนาตนเอง จริยธรรม และการปรับตัวในวิชาชีพ". In it, cultural respect, leadership, self-development, Thai heritage and labour-market readiness all sit together.
- On U1 the 3-4-name group is legal-translation accuracy, and the other 11-12 names are everything else.

**Candidate:**
- Returns the three named dimensions in 7 of 9 runs, with near-identical labels across repeats:
  - "ความรอบคอบและความรับผิดชอบต่อคุณภาพงานแปล";
  - "จริยธรรมและความเข้าใจต่อผู้คนและวัฒนธรรม";
  - "การปรับตัวและพัฒนาตนเองในวิชาชีพ…".
- B1 gave the same 5+4+7 partition 3 times.
- It goes one over the target. That is allowed: the target is a target and `validate_assignments` accepts any partition.

## K (targets 1-2; 4-6 names)

| input | control | candidate |
|---|---|---|
| B1 (6, t=2) | 3+3 ×3 | 3+3 ×3 (cleaner labels) |
| B2 (4, t=1) | 4 · 1+3 · 4 | 4 ×3 |
| U1 (4, t=1) | 4 · 2+2 · 4 | 4 · 4 · 2+1+1 |

The K buckets are too small for the rule to matter. The rule makes B2 steadier and U1 noisier, so it is not worth shipping.

## Decision

- **Ship the EC rule; drop the K rule.**
- The EC rule turns a grab-bag Need into three Needs a designer can read as distinct attitudes. It is also *more* stable than control.
- **Cost:** EC usually yields 3 groups against a target of 2, so one more EC Need competes for the ten PLO slots on `demand_score`.
- **Not fixed by this:** extraction occasionally tags an S skill as E/C, e.g. "การคิดวิเคราะห์ข้อความและบริบทในงานแปล" and "การประเมินคุณภาพคำแปลที่ผลิตโดยเครื่อง…". A clustering rule cannot correct that.
