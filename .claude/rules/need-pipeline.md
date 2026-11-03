---
paths:
  - "src/curriculum_agent/stages/need_*.py"
  - "src/curriculum_agent/stages/demand.py"
  - "src/curriculum_agent/stages/llm_clustering.py"
  - "src/curriculum_agent/stages/skill_extraction.py"
  - "src/curriculum_agent/stages/stakeholder_needs.py"
  - "src/curriculum_agent/prompts/summarize_need.py"
  - "src/curriculum_agent/prompts/cluster_skills.py"
  - "src/curriculum_agent/prompts/need_dedup.py"
  - "src/curriculum_agent/prompts/extract_skills.py"
  - "src/curriculum_agent/prompts/program_context.py"
  - "src/curriculum_agent/prompts/designer_note.py"
  - "tests/**/test_*need*.py"
  - "tests/**/test_demand*.py"
  - "tests/**/test_skill_extraction*.py"
---

# Evidence, skill extraction, and Need combination pitfalls

Moved out of the root CLAUDE.md so it loads only when working on the files above.
These are standing project rules, not suggestions — same weight as CLAUDE.md.

- **Evidence is read in windows, not as a prefix.** `skill_extraction` used to
  pass `raw_text_th[:1200]` to the model and log nothing about the rest, so a
  long สภาวิชาชีพ standard was read down to its first paragraph and could yield
  fewer skills than a short job posting. `chunk_evidence_text` splits an item
  into overlapping windows cut at word boundaries — `evidence_span_th` has to be
  quoted verbatim, and a half-word at a window edge is a span the model cannot
  quote — and every window is extracted under the existing concurrency ceiling.
  The cache is keyed on the window, so lengthening a document still hits on every
  window whose text did not move. `_MAX_CHUNKS` bounds what one pathological
  document costs, and whatever it leaves unread is logged against the evidence
  id; don't reintroduce a cap that says nothing.
- **`Need.rationale_th` is an explanation, not a trail.** The summarize call writes
  it alongside the sentence — why *these* skills are one demand — because that is
  what the model is deciding while it writes, and asked in a second call it would
  be reconstructed from the sentence instead. Traceability is unaffected and must
  stay that way: `source_evidence_ids` is assembled in code and is what immutable
  rule 2 is about, while this is free text nothing can check against the evidence.
  So the prompt forbids citing anything outside the skill names it was handed,
  both Need cards label it "คำอธิบายของโมเดล" and keep it out of the trail panel,
  and the `[ต้องทบทวน]` fallback writes a rationale saying there is none rather
  than a plausible one. `_NeedStatement` bounds it at 20-240 characters and
  rejects an empty answer ("เป็นทักษะที่เกี่ยวข้องกัน") with the same
  `find_vague_phrase` the statement uses — one rule, one scan. The field defaults
  to `""` on the model because a Need also arrives as a plain dict from a
  checkpoint suspended across the deploy; migration `c7e2f81a4b93` backfills a
  self-identifying `[สร้างย้อนหลัง]` sentence built from the row's own member
  count and KSEC tag, and joins nothing — a reason composed out of the member
  skill names would be an explanation no model ever gave, sitting in the field a
  reader takes as the justification.
- **`need_combination` reads the stored skill groups (and the skills they point at) plus the program's own context — never evidence text.** Clustering moved to Agent 1 (`stages/skill_grouping.py`, which persists `SkillGroup` rows); `need_combination` starts from those and never calls the `clustering` slot, so it can be re-run alone (`POST /needs/combine/run`, 422 in Thai when no groups are stored). The sentence for each Need is written from its member
  skill names, and `demand_score` is computed from the evidence ids and
  stakeholder types carried on those skills. `POST /needs/combine/run` therefore does not load the
  evidence table at all and has no evidence precondition. Don't reintroduce
  `classified_evidence` here — extraction already read that evidence, and the raw
  quotes only gave the `need_combination` model longer Thai to drift on. Traceability is
  unaffected: `Need.source_evidence_ids` still comes from the member skills.

  The one thing besides the skills that reaches both LLM calls is
  `build_program_context_th(state["metadata"])` — the field and degree level the
  designer typed at intake, as one Thai line ("หลักสูตรระดับปริญญาตรี สาขาพยาบาลศาสตร์").
  A bare skill name is ambiguous on its own: "การดูแล" groups with clinical work
  in a nursing program and with facility operations in an engineering one, and
  nothing else in either prompt says which program it is. It is metadata, not
  evidence, so it frames the reading and nothing more — the clustering prompt
  states outright that an off-field skill is still market demand and still
  belongs to exactly one group, and the summarize prompt forbids adding a
  capability the skill group never named, since the PLO drafted from that
  sentence has to trace to the evidence behind those skills. A program with no
  `field` gets `None` and the pre-context prompts byte-for-byte. The context is
  in the clustering **cache key** for the same reason `target_clusters` is: it
  reaches the prompt, so two programs whose skill names coincide must not share
  an entry.
- **`demand_score` is three blocks, and the two frequency blocks have separate
  denominators.** `0.20 × (สภาวิชาชีพ named it? 1 : 0) + 0.55 × share of the
  *practitioner* voices that named it + 0.25 × share of everyone else` —
  `stages/demand.py`. Only `PROFESSIONAL_COUNCIL` buys the mandate block, which is
  deliberately narrower than `models.REQUIREMENT_TYPES`: that set still holds
  `INSTITUTIONAL_DIRECTION` and still governs evidence and skill classification,
  but letting the institution's own voice buy the same block would let a faculty
  lift any Need's rank by restating its vision.

  **The mandate block is dead for most Thai programs, which is why it cannot be
  the only thing separating voices.** มคอ.1 was repealed wholesale by กฎกระทรวง
  2565, and the "มาตรฐานคุณวุฒิในสาขาวิชา" series กมอ. issued in its place covers
  the same council-backed fields (แพทยศาสตร์ 2566, เทคนิคการแพทย์/กายภาพบำบัด/
  เภสัชศาสตร์ 2567). A translation or humanities program has no external document
  that can ever buy it. The score was then one pooled frequency block, and pooled
  frequency **inverts** the ranking: a generic capability is one everybody can
  name, a specialist one is named only by the people who employ the graduate. On
  the stored TCISM run the top Need was "การเรียนรู้ตลอดชีวิต" (applicant,
  community, faculty, the faculty's own vision) while every real translation
  competency sat at the bottom on one employer each and was cut.

  `_PRACTITIONER_TYPES` — council, employer, industry, alumni, expert — is the
  line, and **it is not `STAKEHOLDER_GROUP`.** Splitting by external/internal was
  tried first and moved nothing: `APPLICANT` and `COMMUNITY` are external too, so
  an employer naming something alone scored exactly what a community voice naming
  something alone scored. `STAKEHOLDER_GROUP` stays a display label; don't
  "simplify" the scorer onto it. Each block is a share of its own audience, so
  adding applicant interviews cannot dilute what the employers said, and a block
  whose audience is absent contributes zero rather than redistributing its weight
  (same ordering, no branch that varies with corpus composition — and those two
  guards are also what answers an empty corpus, so there is no early return for
  it). An unknown stakeholder type is not a practitioner, so stored-data noise
  falls to the smaller block.

  This is a table mapping types to classes, and the rule it replaced said not to
  add one. What that rule forbids is still forbidden: the old 1.0/0.8/0.6/0.4
  *gradation*, per-type multipliers whose individual values nobody could defend
  and which moved every stored score when one was retuned. Two categorical
  classes with one stated question between them ("has this voice done the work?")
  is a different object — a type's class follows from the question, not from a
  number someone picked. If a new `StakeholderType` seems to need a *third*
  weight, the answer is a better question, not a third tier.
- **`is_optional` counts evidence items, not member classifications.** A Need is
  optional when nothing mandates it and exactly one evidence item asked for it
  (`is_optional_group` in `stages/demand.py`). The rule it replaced read
  `want > requirement + need` over the members, and that proxy never fired: a
  member is `need` only when its own skill *name* was extracted from more than one
  evidence item, and on the stored run all 91 normalised names came from exactly
  one each, so `need` was zero. The only remaining way to be core was to carry a
  `requirement`, which for any programme without a professional council comes from
  `INSTITUTIONAL_DIRECTION` alone — and the scope guard then drops those for not
  being graduate capabilities. Core finished at 1 against a floor of 6, while the
  groups those members formed drew on 7, 9 and 10 evidence items: clustering knows
  two phrasings are one capability and matching normalised strings cannot, so the
  old rule counted phrasings to answer a question about stakeholders. This is the
  second half of the bug `POST /evidence/` fixed the first half of, and that
  route's docstring is the other end of the story. `requirement` still wins
  outright — one mandated member makes a group core however small, because a
  mandate is not a matter of how many people repeated it — and `need` is subsumed
  rather than dropped, since a name in several evidence items means a group in
  several. `classification` is unchanged everywhere else; this rule simply stopped
  reading the group's answer out of it. One clause does still read it: a group
  whose members are **all** `unclassified` is optional. That class counts toward
  neither side, and under any rule of the shape "optional unless X" a neutral
  position is a core slot by default — the old rule gave one because `0 > 0` is
  false, and this one would give one to any such group drawn from two evidence
  items. The scope guard drops every one of them before synthesis, which is what
  makes it look free; it is not, because the band is a property of the stored set
  and `POST /plos/from-needs` checks against it, so the padding lands in a number
  the designer is judged against and cannot reach.
- **`supporting_indices` is self-report, and only its low end means anything.**
  The summarize call numbers the member names and asks which ones the sentence
  speaks for; `need_grouping.supporting_coverage` weighs the answer by mentions
  and `need_combination` logs it. It exists because a Need's trail claims every
  member's evidence whatever its sentence says — ticket 18 found a fifteen-name
  group whose sentence spoke for three — and the names used to arrive as one
  comma-joined string, so the sentence could not say what it covered at all.
  Measured against the stored Needs by eye, the model does discriminate (that
  fifteen-name group reported the lowest figure, 27%) but it **over-claims**,
  often by 1.5–3×: a ten-name group reporting 50% had a sentence covering one or
  two. So a low figure is a real alarm and a high one proves nothing, and any
  flag built on it must fire on low values with the inflation in mind. It also
  does not see the other large-group failure: a sentence that crams three
  capabilities together covers much of its group and scores high. The field is a
  measurement and must never cost a Need — no validator raises on it, and a
  `mode="before"` validator reduces a malformed answer to its integers or to
  `None` because pydantic's own `list[int]` check would otherwise fail the call
  and push a well-written sentence into a `[ต้องทบทวน]` fallback. `None` (no list)
  stays distinct from `0.0` (covers nothing). No threshold, column, or checkpoint
  flag yet: ticket 18 asks for the distribution before a number.
  `not_covered_indices` (which shown member the sentence excludes, and why) and
  `designer_input_used` (whether the optional designer note changed a word
  choice) follow the same discipline: never-fail `mode="before"` validators
  that drop a malformed entry instead of raising, logged by `_log_coverage` and
  a per-run summary line, and never stored.
- **A Need's Bloom level is what most of its group asks for, not its top
  member.** `need_grouping.group_bloom` is the lower mention-weighted median of
  the members' levels; it replaced `merge_bloom`, the maximum, at the one call
  that combines *different* skills. On the stored run 21% of extracted skills
  were Create and 69% of Needs were — OPT2 was Create from 2 Create members of
  18, 9 of them Apply — and the level travels: it reaches the summarize prompt
  as "สร้างและออกแบบสิ่งใหม่ได้" and `plo_synthesis` as the level to write to,
  so five Needs and the five PLOs drafted from them all opened with ออกแบบ, for
  a bachelor's programme whose evidence is mostly Apply. The lower median means
  a level wins only with more than half the group behind it, which is the
  ceiling on Create the pipeline review asked for without a constant of its own.
  `merge_bloom` stays where its reason holds — two rows of *one* skill name, at
  extraction and at dedupe, where the lower level is implied by the higher.
  Stored Needs are not migrated: the level is written into the Need's sentence
  as well as its field, so only re-running need_combination changes what a PLO
  is drafted from.
- **A Need has to be usable as a PLO on its own.** `plo_synthesis` drafts exactly
  one PLO per Need and is handed nothing but `statement_th`, so a placeholder
  ("ทักษะที่จำเป็น") or a joined skill list makes the synthesis model invent the
  capability with no evidence behind it. `need_combination._NeedStatement` enforces
  a length floor, the no-list rule, and `find_vague_phrase` on top of the
  code-token guard; Instructor retries with the offending phrase quoted. A group
  that still fails ships a `[ต้องทบทวน]`-marked fallback for the designer to rewrite —
  never a quietly-degraded Need. **Both guards are counted in two shapes, because
  Thai writes each one differently from English.** `looks_like_a_skill_list` counts
  commas *and* list boundaries that open a นาม phrase (`การ`/`ความ` after a space or
  a spaced `และ`) — a comma count alone saw nothing in "ต้องการการใช้ AI การแปล
  และการตรวจแก้คำแปล", which is a joined list by any reading; it was only ever
  catching the model writing the list the English way. `find_vague_phrase` likewise
  matches a generic head fused to a generic domain word ("ความสามารถทางวิชาชีพ",
  "ทักษะการทำงาน") as well as the head-plus-`ที่`-modifier pairs. That second pattern
  carries a right-boundary lookahead the first does not need: "ที่จำเป็น" says nothing
  wherever it sits, but "ทักษะการทำงานเป็นทีม" names a real capability, and
  over-rejecting costs a retry and then a hand-written Need. **The prompt also carries the
  only rule that pushes the other way.** Everything above bounds how *vague* a Need
  may be and nothing bounded how *narrow* it may be, so "แปลสัญญาซื้อขายสินค้า" — one
  task inside a profession's work — satisfied every one of them. A Need becomes
  exactly one PLO against ten core slots, so one worth less than a tenth of the
  program spends a slot anyway. The bound is written as a property of the
  sentence's **object** (a class of work the graduate repeats, not one instance)
  rather than of its wording, and says outright that it does not license writing
  vaguely — a model told "too narrow" otherwise reaches for "ทักษะการสื่อสาร",
  which is what the dilution rule exists to stop. The two are tested together;
  removing either leaves the other unopposed. **A Need states a requirement; it must not be a
  finished PLO.** The opening is free — "ต้องการ...", "ต้องการบัณฑิตที่...",
  "ต้องการหลักสูตรที่..." and "บัณฑิตต้องมี..." are all fine, and the mandatory
  "ตลาดแรงงานต้องการ..." prefix is gone: it carried nothing the rest of the sentence
  did not and spent characters against the 40-character floor. What is still
  forbidden is the finished outcome form ("บัณฑิตวิเคราะห์...ได้"), because
  `plo_synthesis` receives only this sentence — a Need already written as a PLO
  leaves that stage nothing to do but copy, and the report can no longer show the
  step from what was asked for to what a graduate must therefore be able to do.
  The rule lives in `build_summarize_need_prompt` and is pinned by
  `test_summarize_need.py`; `_CIRCULAR_PHRASES_TH` is unaffected, since a trailing
  "ตามที่ตลาดต้องการ" says nothing whatever the sentence opened with.
  **The sentence's three parts are no longer unconditional.** Task and object
  are still required, but the work-context part is written in only when most
  of the group — weighted by `skill_frequencies`, not a bare count — shares
  that context; a context one or two low-frequency members happen to mention
  must not become the whole sentence's setting either, for the same reason the
  dilution rule exists. This replaced an unconditional "ต้องมีครบ 3 ส่วน" that
  asked every group for a context it might not actually share. The same pass
  fixed the apply Bloom label for the same underlying reason: every stored
  apply-level Need came out wrapped as "ประยุกต์ใช้ <resource> ในการ <task>"
  because `_BLOOM_LABEL_TH["apply"]` ("ประยุกต์ใช้ในงานจริงได้") handed the
  model a verb to copy; the label was reworded to "นำไปลงมือทำงานจริงได้" and a
  dedicated wrapper rule now forbids that sentence shape directly, moving the
  resource into a "โดยใช้..." clause. Two more rules read straight off the
  stored corpus: an actor rule rejects institutional/administrative work
  ("การสร้างความร่วมมือกับมหาวิทยาลัย") in favour of what one new graduate
  does, and an off-profession rule keeps another profession's work (building a
  tool, in a translation program) out of the sentence's main task — using that
  tool to do this profession's work still stays in. Both routes a member out
  through `not_covered_indices` instead of dropping it silently.
  **A fallback marker is not a Need either, and nothing downstream used to
  check for one.** On the tourism program a `[ต้องทบทวน]` fallback — a marker
  plus the comma-joined skill names, written when the sentence call was
  rejected or never reached the model — was drafted straight into PLO2, a
  capability invented from skill names rather than traced to any stakeholder
  demand. `need_grouping.is_unwritten_need` is the one predicate (`REVIEW_MARKER_TH` /
  `PROVIDER_MARKER_TH` are public there; `need_combination` re-exports both under
  their old underscore names): `plo_synthesis._run` drops a marked Need the same
  way as an out-of-scope one, right after the scope filter — stored and
  traceable, not drafted, not offered to the duplicate check, no slot spent — and
  `POST /plos/from-needs` answers 422 if the designer selects one, since unlike
  scope this is not an override a human gets to make by picking it anyway.
- **Two Needs sharing evidence are not two Needs asking for one thing, and the
  duplicate check now runs at Agent 2, not in `plo_synthesis`.** It reads the
  Need *sentences* through a model (`stages/need_dedup.py`, the `need_dedup`
  slot), because the free signal measured useless: on the stored run a marketing
  Need and an ethics Need shared 55% of their evidence while a true duplicate
  pair shared under 20% — a small corpus puts every Need on the same few
  documents. Input is the Needs that are written (`not is_unwritten_need`) and
  in scope, in demand order: an out-of-scope or marker Need is never merged,
  since merging one into an in-scope Need would smuggle it past the scope
  filter. The model's answer is judged in `accept_groups`, not by pydantic
  validators (a validator failure fails the whole call and loses every good
  group with the bad one), and a group that breaks a rule — fewer than two
  known members, more than `MAX_GROUP_SIZE` (5), a Need already taken, first
  group wins — is dropped whole, never trimmed, since which member to cut is
  the judgement the model was asked for. The old "members span more than one
  KSEC tag" rejection is gone (designer's decision of 2026-10-26): a merge may
  cross buckets, and it is the only thing that produces a multi-tag Need.
  `need_merge.enforce_merge_floor` keeps `MIN_CORE_AFTER_MERGE` (4) at this
  stage, unfolding the lowest-demand groups first.
- **A merged Need is built in code from its members, and only its sentence is
  written by a model** (`stages/need_merge.py`). Pooled skills are the union of
  the members' `member_skill_ids`, rows sharing a normalised name collapse to
  the highest `importance_score` (a guard: today `_compute_skill_importance`
  works per normalised name, so those rows already agree), and the top
  `TOP_SKILL_CAP` (7) by `importance_score`, ties by name, become
  `top_skill_ids` — the Need's skill tags. The sentence is one
  `need_combination`-slot call from those names plus the dedup `reason_th`.
  `demand_score`, `is_optional`, coverage, `freq` and the classification counts
  are **recomputed** from the pooled skills with `skill_grouping.score_members`
  — the same functions an unmerged group goes through — not taken as the max of
  the originals, because a capability asked for by more voices should rank
  higher. `member_skill_ids` and `source_evidence_ids` are the **union** over
  all originals, so the trail is never smaller than theirs; `ksec_categories` is
  the sorted union in K, S, E, C order; `merged_from` holds the original ids in
  demand order and `merge_reason_th` the dedup reason. If the sentence call
  fails, that group is **left unmerged**: the originals stay active and the
  failure is logged, because the step can only merge — a failure never costs a
  Need and never ships a `[ต้องทบทวน]` merged Need. Switched off, failing, or
  given one Need, the whole step returns nothing.
- **Active vs merged: originals are stored, never deleted.** Merging sets
  `merged_into` on each original instead of deleting it, and every downstream
  reader (`plo_synthesis`, `plo_report`, `plo_review` facts, `POST
  /plos/from-needs`, the Excel exporter, the SMART agent's tools,
  `cited_need_ids`, the checkpoint's core/optional counts) reads
  `NeedRepository.list_active_by_program`. No call site filters by hand; add a
  reader and it uses that method. `GET /needs/` still returns all of them so the
  UI can nest originals under their merged Need. **Split**
  (`POST /programs/{id}/needs/{need_id}/split`) deletes the merged Need and
  clears `merged_into` on the originals in one transaction
  (`NeedRepository.split`): 404 unknown, 422 not a merged Need, 409 when a
  stored PLO cites it or the program is busy. There is no re-merge; re-running
  Agent 2 is how the designer gets fresh merges. The checkpoint node reloads
  `state["needs"]` from the active read on resume, so a split made while a
  session is paused takes effect.
