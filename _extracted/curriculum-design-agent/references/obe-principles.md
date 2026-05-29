# OBE Principles Reference

This file encodes the rules from the MHESI / AUN-QA / Backward Curriculum Design tradition that the agent must respect. When writing prompts, validating outputs, or reviewing what the LLM generated, check against this file.

## The OBE flow (fixed, do not deviate)

```
Stakeholder needs → PLO → YLO → CLO → Learning activities → Assessment
                    ↑_____ Backward Curriculum Design _____↓
```

The agent is responsible for everything up to YLO. CLO and below are handed off to course instructors. This is intentional: CLO requires faculty knowledge of specific course content, which the agent does not have.

## Hierarchy of learning outcomes

- **PLO (Program Learning Outcome)** — what every graduate of the program can do at graduation. Typically 4–6 statements. Covers both subject-specific and generic competencies.
- **YLO (Year Learning Outcome)** — what a learner can do at the end of each academic year. PLO = Σ YLO over years. Every YLO must contribute to at least one PLO.
- **CLO (Course Learning Outcome)** — what a learner can do at the end of a specific course. Multiple CLOs roll up into one or more YLOs.
- **LLO (Lesson Learning Outcome)** — single-class-session level. Out of scope for this agent.

## SMART criteria

Every PLO and YLO must be:

- **S — Specific:** clear, unambiguous behavior. Not "understands data" but "applies regression analysis to business problems."
- **M — Measurable:** can be observed and assessed. If you can't write an assessment for it, rewrite it.
- **A — Achievable:** within the student's capability given the program's resources and time.
- **R — Relevant:** aligned with the program's vision and stakeholder needs. Trace back to evidence.
- **T — Timely:** achievable within the program's duration (4 years for bachelor, etc.).

## Bloom Taxonomy — cognitive domain action verbs

Use ONE action verb per outcome. If two are needed, they must be in adjacent levels (e.g. apply + analyze).

| Level | Action verbs (use these, not others) |
|-------|--------------------------------------|
| Remember | define, identify, state, label, list, match, locate, repeat, name, recognize |
| Understand | describe, explain, summarize, compare, classify, give example, translate, interpret, paraphrase |
| Apply | implement, solve, compute, modify, operate, use, prepare, demonstrate, predict, show, organize |
| Analyze | analyze, break down, compare, contrast, deconstruct, differentiate, distinguish, examine, experiment, test |
| Evaluate | appraise, rank, rate, assess, verify, argue, debate, monitor, judge, critique, conclude, justify |
| Create | generate, plan, compose, develop, create, invent, construct, produce, design, devise, reorganize, revise |

The same verb can appear at different levels depending on context — "design a flowchart from given specs" is Apply, "design a new system architecture for an unsolved problem" is Create. The verb alone doesn't determine level; the cognitive demand does.

## Forbidden words in PLO/YLO statements (Thai context)

These words CANNOT be observed or measured. Reject any PLO/YLO that uses them:

- **รู้** (know)
- **จำ** (memorize, in the passive sense)
- **เข้าใจ** (understand) — too vague, replace with "describe", "explain", "summarize"
- **ซาบซึ้ง** (appreciate deeply) — affective but unobservable
- **ตระหนัก** (be aware) — replace with observable behavior
- **ศรัทธา** (have faith)
- **รัก** (love)

If translating from English: "have knowledge of" → use "explain"; "understand" → "describe" or "interpret"; "appreciate" → "demonstrate" or "exhibit through behavior."

## Affective domain (Krathwohl) — for attitude/values PLOs

When a PLO targets attitude rather than cognition, use the Krathwohl progression instead:

1. **Receiving** — pays attention, listens
2. **Responding** — participates, complies
3. **Valuing** — accepts, prefers, commits (e.g. cites sources without being told to)
4. **Organization** — ranks values, resolves conflicts between them
5. **Characterization** — internalizes; the value becomes part of the person's behavior pattern

Example progression for "ผู้เรียนปฏิบัติงานได้ตามจรรยาบรรณวิชาชีพ":
- Year 1 (Responding): "อธิบายข้อกำหนดทางจรรยาบรรณวิชาชีพได้"
- Year 2 (Valuing): "ปฏิบัติตามจรรยาบรรณวิชาชีพในงานที่ได้รับมอบหมาย"
- Year 3 (Organization): "ตัดสินใจในสถานการณ์ที่มีข้อขัดแย้งทางจรรยาบรรณโดยใช้หลักการทางวิชาชีพได้"
- Year 4 (Characterization): "ดำเนินงานทางวิชาชีพโดยยึดถือจรรยาบรรณเป็นแนวปฏิบัติประจำได้อย่างสม่ำเสมอ"

## Subject-specific vs generic outcomes

Every program needs BOTH:

- **Subject-specific outcomes** — competencies unique to the field (e.g. "design a packaging system that respects intellectual property rights" for a packaging design program)
- **Generic / transferable outcomes** — competencies any graduate should have (problem-solving, communication, collaboration, lifelong learning, ethical practice, digital literacy)

A program with only subject-specific PLOs fails AUN-QA review. A program with only generic PLOs fails to differentiate from other fields. Aim for roughly 60–70% subject-specific, 30–40% generic.

## YLO Bloom progression rules

When deriving YLO from PLO across years 1–4 of a bachelor's program:

- **Year 1**: typically Remember + Understand level. Foundational concepts, terminology, basic principles.
- **Year 2**: Apply level. Use principles in standard situations.
- **Year 3**: Analyze + Evaluate. Break down complex problems, judge alternatives.
- **Year 4**: Evaluate + Create. Capstone work — design, propose, integrate across domains.

Adjust per program (5- or 6-year programs spread the progression more gradually). The principle is monotonic non-decrease: a Year-3 YLO should not be at a lower Bloom level than its Year-2 counterpart for the same PLO.

If a PLO is in the affective domain, use Krathwohl progression instead.

## Pre-BCD checklist

Before sending PLOs to the BCD step (course design), verify:

1. PLOs trace back to stakeholder needs (evidence trail intact)
2. Each PLO is SMART
3. Mix of subject-specific and generic outcomes
4. PLOs align with the program's stated objectives and the university/faculty vision
5. PLOs differentiate this program from peer programs in the same field

If any check fails, return to PLO synthesis (Stage 3) — do not proceed.

## Curriculum mapping checklist

When the agent or user produces a YLO matrix:

- Every required core course must contribute to at least one PLO (via its YLO)
- Every PLO must be addressed across multiple years (not just one course in year 4)
- Bloom level should increase or hold across years for a given PLO — never decrease
- Year 4 should reach Apply or higher for every subject-specific PLO

## References

- AUN-QA Programme Assessment, Version 4.0
- ประกาศกระทรวงการอุดมศึกษาฯ เรื่องเกณฑ์มาตรฐานหลักสูตรระดับปริญญาตรี/บัณฑิตศึกษา พ.ศ. 2565
- มคอ.1 (subject-area benchmark) for the relevant field
- CHECO format requirements (ความคาดหวังของผลลัพธ์การเรียนรู้เมื่อสิ้นปีการศึกษา section)
- Anuwong, K. — workshop materials on Backward Curriculum Design (cited in project knowledge)
