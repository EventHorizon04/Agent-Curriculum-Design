# OBE Principles Reference

Rules from the MHESI / AUN-QA / Backward Curriculum Design tradition that the agent must respect. When writing prompts, validating outputs, or reviewing what the LLM generated, check against this file.

## The OBE flow (fixed, do not deviate)

```
Stakeholder needs → PLO → [YLO → CLO → Learning activities → Assessment]
                    ↑ agent scope ends here — YLO onward is faculty work
```

This agent is responsible for everything up to and including PLO. YLO/CLO require faculty knowledge of course sequencing and content, which the agent does not have. Never skip levels in the chain (PLO → CLO directly breaks CHECO compliance) — and never generate YLO/CLO without surfacing the scope boundary first.

## Hierarchy of learning outcomes (context)

- **PLO (Program Learning Outcome)** — what every graduate can do at graduation. 6-10 statements (per project policy — see SKILL.md). Spans more than one KSEC domain (`K`/`S`/`EC`/`E`/`C`), not clustered in just one.
- **YLO (Year Learning Outcome)** — end of each academic year. PLO = Σ YLO over years. *Out of agent scope.*
- **CLO (Course Learning Outcome)** — end of a specific course. *Out of agent scope.*
- **LLO (Lesson Learning Outcome)** — single-class-session level. *Out of agent scope.*

## SMART criteria — full validation rubric

Every PLO must satisfy all five SMART dimensions **before it leaves the PLO synthesis stage**. This rubric is the specification for the SMART retry loop and for any Pydantic validator (`SMARTValidator` or equivalent) that checks LLM-generated PLOs before they're accepted. Each dimension has a definition, a concrete validation rule an automated checker can apply, and pass/fail examples. Implement validators against this file — don't re-derive the rules from memory.

### S — Specific (มีความเฉพาะเจาะจง)

**คำนิยาม:** ข้อความ PLO ต้องระบุพฤติกรรม ทักษะ หรือสมรรถนะที่คาดหวังให้ผู้เรียนแสดงออกอย่างชัดเจนและเจาะจง ไม่ใช้คำที่มีความหมายกว้างเกินไป โดยมักอาศัย "คำกริยาแสดงพฤติกรรม (Action Verbs)" ตามอนุกรมวิธานของบลูม (Bloom's Taxonomy) มาเป็นตัวกำหนดทิศทาง

**Validation rule:**
- Exactly one Bloom action verb from the table below (see [Bloom Taxonomy](#bloom-taxonomy--cognitive-domain-action-verbs)) is present, applied to a named object (a skill, artifact, standard, or domain) — not a vague noun phrase.
- Reject if the object of the verb is an unqualified generic term such as "ความรู้" (knowledge in general), "ทักษะที่จำเป็น" (necessary skills), "ความสามารถโดยรวม" (overall ability) with no domain, tool, standard, or context attached.
- Reject if the statement could apply equally to almost any program in any field (fails the "does this differentiate the program" test).

**ไม่ผ่าน:** "มีความรู้และทักษะที่จำเป็นสำหรับการทำงาน" — ไม่มีกริยาพฤติกรรมชัดเจน วัตถุของประโยคกว้างเกินไป
**ผ่าน:** "พัฒนาโปรแกรมประยุกต์บนเว็บโดยใช้สถาปัตยกรรมแบบ RESTful API ได้" — กริยา "พัฒนา" ชัดเจน วัตถุเจาะจง (โปรแกรมประยุกต์บนเว็บ, RESTful API)

### M — Measurable (สามารถวัดและประเมินผลได้)

**คำนิยาม:** ผลลัพธ์ที่ระบุจะต้องสามารถสังเกตเห็นได้ (Observable) และสามารถประเมินผลเชิงประจักษ์ได้จริงด้วยเครื่องมือการประเมินทางการศึกษา ทั้งในเชิงปริมาณหรือเชิงคุณภาพ

**Validation rule:**
- **[hard]** Automatically reject any PLO that *uses* a forbidden unmeasurable word (รู้, จำ, เข้าใจ, ซาบซึ้ง, ตระหนัก, ศรัทธา, รัก — see [Forbidden words](#forbidden-words-in-plo-statements-thai-context)), since these describe internal mental states rather than observable output.
  - **Uses, not contains.** Thai has no word boundaries, so a substring scan flags every compound that happens to hold one: `รักษา` (treat//care for) holds รัก, `จำแนก` (classify — itself a sound Understand verb) and `จำลอง` (model/simulate) hold จำ, `ความรู้` and `เรียนรู้` hold รู้. Each of those hard-failed M, spent all three repair rounds against a hint about a word the statement never used, and escalated. `smart_vocabulary.forbidden_words_in` masks a curated list of such compounds before matching, and is the one place a real tokenizer would go. Do not re-implement this as `word in statement`.
  - Note the consequence, which is correct: `ความรู้` as the *object* of a verb ("บูรณาการความรู้ทางวิศวกรรม…") is a soft `specific_object_ok` finding per S above, not a hard Measurable failure.
- **[soft]** The action verb must map to an assessable behavior — ask "could a rubric, exam, project, or portfolio review actually score this?" The absence of a forbidden word is *not* evidence of this; a statement can clear the word list and still name nothing a real instrument could observe.
- Prefer statements where the assessment method is implicit in the verb itself (e.g. "ออกแบบ" → design review; "วิเคราะห์" → case analysis; "นำเสนอ" → presentation rubric).

**ไม่ผ่าน:** "เข้าใจหลักการเขียนโปรแกรมเชิงวัตถุ" — "เข้าใจ" ประเมินไม่ได้โดยตรง
**ผ่าน:** "เขียนโปรแกรมเชิงวัตถุเพื่อแก้ปัญหาที่กำหนดให้ได้" — ประเมินได้ด้วยการตรวจโค้ดหรือทดสอบผลลัพธ์

### A — Achievable (สามารถบรรลุผลได้จริง)

**คำนิยาม:** เป้าหมายหรือสมรรถนะที่กำหนดขึ้นต้องอยู่บนพื้นฐานของความเป็นจริง สอดคล้องกับระดับคุณวุฒิของผู้เรียน ทรัพยากรสนับสนุนของหลักสูตร และมีความเป็นไปได้ที่จะบรรลุผลภายในระยะเวลาของการศึกษา

**Validation rule:**
- Cross-check the Bloom level implied by the verb against the qualification level (bachelor's vs. master's vs. doctoral) — a bachelor's PLO should not require Evaluate/Create-level mastery of research-frontier content that normally needs graduate training.
- Cross-check against the tech-stack/resources on record for the program (staff expertise, lab equipment, industry partners). If a PLO requires infrastructure the program doesn't have and has no plan to acquire, flag it — this is a human-review flag, not an auto-reject, since resources can change.
- This dimension is the hardest to check automatically; treat it as a flag for human review in the PLO synthesis checkpoint rather than a hard validator failure.

**ไม่ผ่าน (ตัวอย่างความเสี่ยง):** PLO ระดับปริญญาตรีที่กำหนดให้ผู้เรียน "คิดค้นสถาปัตยกรรมคอมพิวเตอร์ควอนตัมแบบใหม่" โดยหลักสูตรไม่มีห้องปฏิบัติการหรือคณาจารย์ด้านนี้
**ผ่าน:** PLO ที่สอดคล้องกับทรัพยากรและระยะเวลาของหลักสูตรจริง

### R — Relevant (มีความสอดคล้องและตรงประเด็น)

**คำนิยาม:** ผลลัพธ์การเรียนรู้ต้องมีความเชื่อมโยงและตอบสนองต่อความต้องการของผู้มีส่วนได้ส่วนเสีย (Stakeholder Needs) สะท้อนสมรรถนะทางวิชาชีพที่ตลาดแรงงานต้องการ รวมถึงสอดคล้องกับวิสัยทัศน์และพันธกิจของสถาบัน

R has **three components**, checked three different ways:

**Validation rule:**
- **[hard] Evidence trail.** Every PLO must carry a non-empty `source_need_ids`/`source_evidence_ids` evidence trail pointing back to at least one `Need` and one `StakeholderEvidence` record (per `references/data-schemas.md`). A PLO with an empty evidence trail is a hard reject — this is the same rule as "Every PLO carries evidence" in SKILL.md.
- **[soft] Answers the Needs it cites.** The judge reads the PLO statement against the Needs' own statements (`need_statements_th`) and asks whether it actually responds to them — a trail that resolves is not the same as a statement that answers.
- **[structural] Institutional direction.** The institution's vision/mission is *evidence*, not metadata: it enters at stage 2 as `stakeholder_type=institutional_direction`. Coverage is therefore settled by looking at `Need.source_stakeholder_types` across the synthesized set, not by comparing the PLO text to a vision string. `plo_synthesis.run` logs one program-level warning when no Need behind any PLO carries that type. Do not reintroduce a per-PLO text-similarity check against `vision_th` — it fired on every PLO in a set and said nothing actionable.

**ไม่ผ่าน:** PLO ที่ไม่มี `source_need_ids` อ้างอิงถึงหลักฐานผู้มีส่วนได้ส่วนเสียใด ๆ (ถือเป็น fabricated PLO)
**ผ่าน:** PLO ที่ตรวจสอบย้อนกลับได้ถึง job posting, มคอ.1, หรือ feedback จากศิษย์เก่าที่บันทึกไว้

### T — Time-bound (มีกรอบเวลาที่ชัดเจน)

**คำนิยาม:** มีการกำหนดเงื่อนไขของเวลาไว้อย่างชัดเจนว่าผู้เรียนจะสามารถบรรลุผลลัพธ์หรือแสดงสมรรถนะเหล่านี้ได้เมื่อใด ซึ่งในบริบทของ PLO หมายถึง "เมื่อสิ้นสุดกระบวนการศึกษาในหลักสูตร"

**Validation rule:**
- **[soft, defaults to pass]** A PLO's implicit time frame is always "at graduation", so silence about time is *correct* — never flag a statement for omitting a horizon. The verdict fails only when the statement commits to a conflicting one ("ภายในปีที่ 2").
- The Bloom level chosen must still be reachable by graduation given the program's duration (4 years bachelor, 2 years master's, etc.) — that part is a cross-check with Achievable and lives there.
- (Year-tagged time frames and Bloom monotonicity across years apply to YLO, which is out of this agent's scope — relevant only if faculty ask for guidance during hand-off.)

**ผ่าน:** PLO ที่ระดับ Bloom บรรลุได้จริงภายในระยะเวลาหลักสูตร

### SMART validation checklist (automatable, for the synthesis retry loop)

Three hard checks are pure code (`stages/smart_rules.py`), and they are the **floor**: `plo_synthesis.validate_and_build` runs them on the final statement whatever else happened, and that call alone sets `smart_escalated`.

1. **[S_VERB, hard]** Exactly one recognized Bloom verb present in the statement.
2. **[M_FORBIDDEN, hard]** No forbidden unmeasurable word present (รู้ / จำ / เข้าใจ / ซาบซึ้ง / ตระหนัก / ศรัทธา / รัก).
3. **[R_EVIDENCE, hard]** `source_need_ids` evidence trail is non-empty and resolves to a real `Need`/`StakeholderEvidence` record.

The **validation agent** (`stages/smart_agent.py`, on its own `VALIDATION_*` slot) investigates and instructs: it reads the pure-code verdict through a `check_hard` tool, may read the cited Needs, an excerpt of their evidence, the sibling outcomes and the Thai Bloom table, and when a statement needs repair it emits an *instruction* that `complete_synthesis` executes — then re-checks what came back. It cannot declare a hard failure passed: `Finish` carries no field that clears one, and the code gate above runs afterwards regardless. Its five soft verdicts still never block:

| Verdict | Asks |
|---|---|
| `specific_object_ok` | Is the verb's object specific — not "ความรู้", not "ทักษะที่จำเป็น"? |
| `measurable_ok` | Observable *and* assessable with a real instrument (exam, artefact, performance, portfolio)? |
| `achievable_ok` | Is the Bloom level plausible for `degree_level` and reachable within `duration_years`? |
| `relevant_needs_ok` | Does the statement actually answer the Needs it cites? |
| `time_bound_ok` | Defaults true; fails only on a conflicting horizon. |

Repairs are bounded — max 3 per PLO, plus a turn budget and a per-PLO deadline — then `smart_escalated=True` and the PLO is kept for human repair, never dropped. Soft verdicts land in `soft_flags` (`S_object`, `M_assessable`, `A_level`, `R_needs`, `T_horizon`) **and** in the matching `SMARTCheck` field, so `SMARTCheck.passed` stops reporting success for a flagged outcome. When the validator itself cannot run or cannot finish — a dead endpoint, an exhausted budget, a malformed answer — every soft verdict defaults true, no finding is manufactured, and `smart_validated_by="code_only"` records that the pure checks decided alone. An outage degrades toward "not flagged" rather than falsely flagging sound work, and never toward an escalation nobody judged.

R's institutional component is not in this list: it is checked once per program from `Need.source_stakeholder_types`, as described under R above. It is **not** the agent's job either — do not add a `check_institutional` tool.

### What a verdict records

A verdict is more than pass/fail, because the old gate's surviving hard failures were logged and dropped: a designer could see that a PLO escalated and never which criterion did it.

- `SMARTCheck.findings` — one `SmartFinding` per problem (`criterion`, `severity`, Thai `note_th`), hard and soft in one list. Rides inside the existing `smart_check` JSONB column.
- `soft_flags` — the same soft codes as a flat list, because five readers want it that way. A validator keeps the two in step.
- `smart_validated_by` — `agent` / `code_only` / `stale` / `legacy`. "The validator judged this and it failed", "the validator could not run", "a designer edited the statement and nothing has re-judged it" and "this predates the validator" are four different facts, and the UI must not attribute a diagnosis to something that never ran.
- `smart_diagnosis_th` — the overall reason, in Thai, for the designer to act on.

The tool-call transcript is **not** persisted (it goes to loguru at DEBUG). If it ever must be, it belongs in its own audit table keyed `(program_id, plo_id, run_at)` — not a column on the outcome, which is the response model of five endpoints and is re-upserted on every checkpoint run.

### Sibling context, and why overlap is soft only

`list_sibling_plos` lets the validator see the other outcomes in the set, so "this is indistinguishable from PLO4" becomes checkable — and it is a finding under **S** (`specific_object_ok`), per S's own "could apply equally to almost any program" test. Deliberately not a sixth code.

It can only ever be soft. Redundancy is a property of the *set*, and PLOs are validated concurrently: ten validators asked pairwise can each answer "not a duplicate" while the set holds two near twins, or PLO3 and PLO7 can flag each other, both escalate, both get repaired independently, and converge again. If set-level redundancy needs enforcing, it belongs in `plo_report` as a program-level check — not in ten independent judgements trying to agree.

### The Thai Bloom verb table

`stages/bloom_verbs.py` holds the Thai renderings of the cognitive verb table above, which existed only in English until the validator needed to consult it. It is **advisory**: it feeds `bloom_lookup` and `check_hard`'s verb count, and is wired into no hard check. A PLO using a sound verb the table forgot would otherwise hard-fail Specific and escalate, which is worse than the gap it closes. The table is a judgement call and wants a Thai curriculum specialist's review before it gains any authority.

## K/S/E/C vs Bloom domain — do not conflate

`ExtractedSkill.ksec_category` / `Need.ksec_category` (see `data-schemas.md`) is a **TQF/มคอ. compliance tag**, not a Bloom domain. K=ความรู้, S=ทักษะ, C=คุณลักษณะบุคคล, E=คุณธรรมจริยธรรม — a skill carries exactly one of these four. A Need also carries `EC`, an umbrella tag produced when its member skills mix `E` and `C` (an all-`E` or all-`C` group still resolves to the standalone `E`/`C` tag). There is no "mixed" value for a skill and no separate specificity flag bolted on — a skill or Need has exactly one KSEC tag. It exists to make eventual มคอ.2/CHECO domain mapping traceable back to the skill level, and is orthogonal to `bloom_level` (the cognitive-scale tag below) — a skill can be `ksec_category=S` at any Bloom level, e.g. "วิเคราะห์ข้อมูลเชิงสถิติ" is `analyze` and `S` at the same time. Don't try to derive one field from the other.

## Bloom's Taxonomy — three learning domains (agent models only the first)

Bloom's Taxonomy spans three domains, each with its own level scale:

| Domain | Focus | Scale (low → high) |
|--------|-------|--------------------|
| Cognitive | Knowledge / Thinking | Remember → Understand → Apply → Analyze → Evaluate → Create |
| Psychomotor | Skill / Doing | Imitate → Manipulate → Precise → Articulate → Naturalize (Dave) |
| Affective | Attitude / Feeling | Receiving → Responding → Valuing → Organization → Characterization (Krathwohl) |

**Agent scope note:** this codebase only models the Cognitive scale (`BloomLevel`). Every `ExtractedSkill`, `Need`, and `PLO` the agent produces is cognitive-only — there is no `PsychomotorLevel` or `KrathwohlLevel` class, and no field on any of those models carries a psychomotor or affective tag. The Psychomotor and Affective sections below are kept as **faculty reference for the YLO/CLO hand-off**, not agent behaviour — a faculty member deriving YLOs/CLOs from a psychomotor- or affective-flavoured PLO statement needs these scales; the agent itself never assigns them. Do not re-implement psychomotor/affective tagging in the pipeline on the strength of these sections being present.

## Bloom Taxonomy — cognitive domain action verbs

Use ONE action verb per outcome. If two are needed, they must be in adjacent levels (e.g. apply + analyze) — but prefer one.

| Level | Action verbs (use these, not others) |
|-------|--------------------------------------|
| Remember | define, identify, state, label, list, match, locate, repeat, name, recognize |
| Understand | describe, explain, summarize, compare, classify, give example, translate, interpret, paraphrase |
| Apply | implement, solve, compute, modify, operate, use, prepare, demonstrate, predict, show, organize |
| Analyze | analyze, break down, compare, contrast, deconstruct, differentiate, distinguish, examine, experiment, test |
| Evaluate | appraise, rank, rate, assess, verify, argue, debate, monitor, judge, critique, conclude, justify |
| Create | generate, plan, compose, develop, create, invent, construct, produce, design, devise, reorganize, revise |

The same verb can appear at different levels depending on context — "design a flowchart from given specs" is Apply, "design a new system architecture for an unsolved problem" is Create. The verb alone doesn't determine level; the cognitive demand does.

Bachelor-level PLOs sit mostly at Apply / Analyze / Evaluate / Create.

## Forbidden words in PLO statements (Thai context)

These words CANNOT be observed or measured. Reject any PLO that uses them:

- **รู้** (know)
- **จำ** (memorize, in the passive sense)
- **เข้าใจ** (understand) — too vague, replace with "describe", "explain", "summarize"
- **ซาบซึ้ง** (appreciate deeply) — affective but unobservable
- **ตระหนัก** (be aware) — replace with observable behavior
- **ศรัทธา** (have faith)
- **รัก** (love)

If translating from English: "have knowledge of" → use "explain"; "understand" → "describe" or "interpret"; "appreciate" → "demonstrate" or "exhibit through behavior."

## Psychomotor domain (Dave) — faculty reference for YLO/CLO, not agent behaviour

**This scale is not modelled by the agent.** PLO is cognitive-only (see the scope note above); no code in this repository assigns a psychomotor level to anything. This section exists so that faculty deriving YLOs/CLOs from a hands-on PLO have the progression on hand at hand-off — it is domain knowledge for the next stage of OBE, not a spec to implement here.

When a PLO targets a physical or hands-on skill (lab technique, instrument operation, craft, clinical procedure), faculty use Dave's psychomotor progression instead of the cognitive scale to derive the relevant YLOs/CLOs:

1. **Imitate** — copies an observed action under supervision (ทำตามแบบ)
2. **Manipulate** — performs from instructions or memory without a model (ทำตามคำสั่ง)
3. **Precise** — executes accurately and consistently without guidance (ทำได้แม่นยำ)
4. **Articulate** — combines and adapts skills into coherent sequences in new situations (ทำได้ต่อเนื่อง)
5. **Naturalize** — performs automatically, with mastery, as second nature (ทำได้เป็นธรรมชาติ)

Bachelor-level psychomotor PLOs typically sit at Precise / Articulate. Example verbs: สาธิต, ปฏิบัติ, ประกอบ, ปรับแต่ง, ควบคุมเครื่องมือ.

## Affective domain (Krathwohl) — faculty reference for YLO/CLO, not agent behaviour

**This scale is not modelled by the agent** either, for the same reason as Psychomotor above — kept here as domain reference for the faculty hand-off, not something the pipeline assigns.

When a PLO targets attitude rather than cognition, faculty use the Krathwohl progression instead of Bloom to derive the relevant YLOs/CLOs:

1. **Receiving** — pays attention, listens
2. **Responding** — participates, complies
3. **Valuing** — accepts, prefers, commits (e.g. cites sources without being told to)
4. **Organization** — ranks values, resolves conflicts between them
5. **Characterization** — internalizes; the value becomes part of the person's behavior pattern

Example progression for "ผู้เรียนปฏิบัติงานได้ตามจรรยาบรรณวิชาชีพ":
- Responding: "อธิบายข้อกำหนดทางจรรยาบรรณวิชาชีพได้"
- Valuing: "ปฏิบัติตามจรรยาบรรณวิชาชีพในงานที่ได้รับมอบหมาย"
- Organization: "ตัดสินใจในสถานการณ์ที่มีข้อขัดแย้งทางจรรยาบรรณโดยใช้หลักการทางวิชาชีพได้"
- Characterization: "ดำเนินงานทางวิชาชีพโดยยึดถือจรรยาบรรณเป็นแนวปฏิบัติประจำได้อย่างสม่ำเสมอ"

## Outcome coverage across KSEC domains

Every program needs outcomes spanning more than one competency domain — a PLO set sitting entirely in `K` (knowledge) fails AUN-QA review for lacking breadth, and one that never reaches `EC`/`E`/`C` skips the profession's ethical/character expectations มคอ. requires. There is no longer a computed generic/specific split or a target ratio for it: that classification (and the `SS`/`GS` KSEC tags it depended on) has been removed from the design — see `data-schemas.md`. Checking outcome breadth now means looking at the KSEC tags (`K`/`S`/`EC`/`E`/`C`) of the Needs behind the PLO set, not measuring a percentage.

## PLO readiness checklist

Before marking a PLO set final (hand-off to faculty for YLO/BCD work), verify:

1. PLOs trace back to stakeholder needs (evidence trail intact — every PLO has non-empty `source_need_ids`)
2. Each PLO passes the full SMART validation checklist above (no outstanding hard-fails; soft-flags reviewed by the designer)
3. Between 6 and 10 PLOs, spanning more than one KSEC domain
4. PLOs align with the program's stated objectives and the university/faculty vision
5. PLOs differentiate this program from peer programs in the same field
6. No forbidden words; one action verb per statement

If any check fails, return to PLO synthesis — do not hand off.

## References

- AUN-QA Programme Assessment, Version 4.0
- ประกาศกระทรวงการอุดมศึกษาฯ เรื่องเกณฑ์มาตรฐานหลักสูตรระดับปริญญาตรี/บัณฑิตศึกษา พ.ศ. 2565
- มคอ.1 (subject-area benchmark) for the relevant field
- CHECO format requirements (PLO → CHECO 1.6.2 ผลลัพธ์การเรียนรู้ของหลักสูตร)
- Anuwong, K. — workshop materials on Backward Curriculum Design
