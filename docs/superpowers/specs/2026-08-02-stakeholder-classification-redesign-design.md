# Stakeholder Classification Redesign

**Date:** 2026-08-02
**Status:** Approved design, not yet implemented

## Problem

Three things are wrong with how the pipeline classifies stakeholder input today.

**Classification sits at the wrong level.** `StakeholderEvidence.classification` labels a
whole evidence item `need` / `requirement` / `want` / `unclassified`, decided by an LLM call
in `stakeholder_needs`. But "how many sources asked for this" is a property of a *skill*
across evidence items, not of one evidence item. A job posting is not "a need" — it
mentions capabilities, some of which many sources also mention and some of which only it
mentions.

**The stakeholder taxonomy does not match Thai practice.** `StakeholderType` carries nine
values chosen ad hoc (`accreditation_body`, `subject_benchmark`, `peer_program`) and is
missing the groups a Thai curriculum committee actually consults: ภาคอุตสาหกรรม,
ผู้ทรงคุณวุฒิ, สถาบันคู่ความร่วมมือ, ผู้สมัครเรียน, and the entire internal side
(ผู้บริหาร, คณะกรรมการหลักสูตร, อาจารย์, ผู้เรียน, บุคลากรสายสนับสนุน). Nothing marks a
group as external or internal, which is the distinction that decides how much weight its
input carries.

**The institution's own direction never enters the evidence trail.** `vision_th`,
`mission_th`, `philosophy_th`, and the two identity fields are collected at intake and used
only as prompt context. They are mandatory inputs to a Thai program's PLOs, yet no PLO can
trace to them because they are not evidence.

Two smaller defects fall out of the same area:

- `demand.py` computes `breadth = len(stakeholder_coverage) / len(StakeholderType)` —
  dividing by the total number of enum members rather than by the groups the program
  actually collected from. A program with 3 stakeholder groups whose skill is named by all
  3 scores 3/9 = 0.33, and growing the enum silently rescales every stored score.
- `KSECCategory` splits skills into `SS` (subject-specific) and `GS` (generic) purely to
  feed `PLO.is_subject_specific`. That split is a judgement the extraction LLM is asked to
  make per skill mention, where it has the least context to make it.

## Design

### 1. StakeholderType: external / internal

```python
class StakeholderGroup(StrEnum):
    EXTERNAL = "external"
    INTERNAL = "internal"


class StakeholderType(StrEnum):
    # --- external ---
    PROFESSIONAL_COUNCIL = "professional_council"   # สภาวิชาชีพ
    EMPLOYER = "employer"                           # ผู้ใช้บัณฑิต / ผู้ประกอบการ
    INDUSTRY = "industry"                           # ภาคอุตสาหกรรม
    ALUMNI = "alumni"                               # ศิษย์เก่า
    EXPERT = "expert"                               # ผู้ทรงคุณวุฒิ
    COMMUNITY = "community"                         # ชุมชนและสังคม
    PARTNER_INSTITUTION = "partner_institution"     # สถาบันคู่ความร่วมมือ
    APPLICANT = "applicant"                         # ผู้สมัครเรียน
    PARENT = "parent"                               # ผู้ปกครอง
    # --- internal ---
    INSTITUTIONAL_DIRECTION = "institutional_direction"  # vision/mission/identity
    ADMINISTRATOR = "administrator"                 # ผู้บริหาร
    PROGRAM_COMMITTEE = "program_committee"         # คณะกรรมการหลักสูตร
    FACULTY = "faculty"                             # อาจารย์
    STUDENT = "student"                             # ผู้เรียน
    SUPPORT_STAFF = "support_staff"                 # บุคลากรสายสนับสนุน


_EXTERNAL = {
    StakeholderType.PROFESSIONAL_COUNCIL, StakeholderType.EMPLOYER,
    StakeholderType.INDUSTRY, StakeholderType.ALUMNI, StakeholderType.EXPERT,
    StakeholderType.COMMUNITY, StakeholderType.PARTNER_INSTITUTION,
    StakeholderType.APPLICANT, StakeholderType.PARENT,
}
STAKEHOLDER_GROUP: dict[StakeholderType, StakeholderGroup] = {
    t: (StakeholderGroup.EXTERNAL if t in _EXTERNAL else StakeholderGroup.INTERNAL)
    for t in StakeholderType
}
```

`INSTITUTIONAL_DIRECTION` is one type covering the vision, mission, philosophy, and
identity statements of มหาวิทยาลัย / คณะวิชา / หลักสูตร. They are not separate
stakeholders — they are one voice (the institution's) expressed in several documents, and
`source_name` already distinguishes which document a given evidence item came from.

Deleted: `ACCREDITATION_BODY`, `UNIVERSITY`, `SUBJECT_BENCHMARK`, `PEER_PROGRAM`. Note that
`ProgramContext.professional_council`, `.accreditation_body`, and `.subject_benchmark_ref`
are unrelated fields on the program metadata and are **not** touched.

`STAKEHOLDER_GROUP` is the single mapping from type to group. Nothing else may hardcode the
external/internal split — the weight table and any UI grouping read from it.

### 2. Classification moves to skill level

| Level | Field | Values | Decided by |
|---|---|---|---|
| Evidence | `StakeholderEvidence.classification` | `requirement` \| `general` | pure code, from `stakeholder_type` |
| Skill | `ExtractedSkill.classification` (new) | `requirement` \| `need` \| `want` \| `unclassified` | pure code, after all evidence is extracted |

Both vocabularies are `Literal` aliases in `models.py`, so a typo is a type error:

```python
EvidenceClassification = Literal["requirement", "general"]
SkillClassification = Literal["requirement", "need", "want", "unclassified"]
```

**Evidence classification** is a lookup, not a judgement:

```python
REQUIREMENT_TYPES = frozenset({
    StakeholderType.PROFESSIONAL_COUNCIL,
    StakeholderType.INSTITUTIONAL_DIRECTION,
})
```

สภาวิชาชีพ sets legal practice requirements and the institution sets its own mandatory
direction; both are ข้อกำหนดที่ต้องมี. Every other type is `general` — its input still
matters, but as demand signal rather than mandate.

This deletes the entire LLM classification path in `stakeholder_needs`: `_ClassifyResult`,
`classify_single`, `WANT_ONLY_TYPES`, `_WANT_RATIONALE_TH`, and
`prompts/classify_evidence.py`. `StakeholderEvidence.classification_rationale_th` stays as a
field (the API allows manual override) but the stage no longer writes an LLM rationale into
it.

**Skill classification** is computed once, after every evidence item has been extracted,
because it depends on cross-evidence counts. The rules, in precedence order:

1. The skill came from an evidence item whose `classification == "requirement"` →
   `requirement`.
2. Its normalised name matches a skill already classified `requirement` in rule 1 →
   `requirement`. *(requirement wins — see below)*
3. `is_field_relevant == False` → `unclassified`.
4. Distinct `source_evidence_id` count across the program > 1 → `need`.
5. Otherwise → `want`.

**Requirement wins.** A skill named by สภาวิชาชีพ and also by a single employer is a
`requirement`, not a `want` — a legal or institutional mandate does not become optional
because few people repeated it. Rule 2 is what makes this hold across sources, and rule 1
precedes rule 3 for the same reason: a mandated skill stays in the pipeline even if the
extraction model judged it off-field.

Name matching in rule 2 uses `need_grouping.normalize_need_name` (trim, collapse internal
whitespace, lowercase) — the same normaliser `dedupe_with_bloom_max` uses, so two spellings
that later collapse into one Need also merge here. Semantic matching is deliberately *not*
added: that is exactly what LLM clustering does in `need_combination`, one stage later.

**`unclassified`** is decided by the extraction LLM itself. `_SkillItem` gains
`is_field_relevant: bool`, judged in the same call that extracts the skill — no extra call
and no extra latency.

This requires fixing an existing defect: `build_extract_skills_prompt(evidence_text,
classification)` instructs the model that "ทักษะที่ไม่เกี่ยวข้องกับสาขาวิชาของหลักสูตร
ห้ามเสนอ" without ever telling it which field the program is in. The builder gains
`field_th` and `program_name_th` parameters, both sourced from `state["metadata"]`, so the
instruction becomes answerable. A skill the model
judges unrelated to the field of study (a job posting asking for a driving licence in a
Computer Science program) is kept but marked, not silently dropped: the designer sees it at
the checkpoint and can promote it.

### 3. Intake converts institutional direction into evidence

After `ProgramRepository.upsert()` in `intake.run()`, the stage writes one
`StakeholderEvidence` row per non-empty institutional-direction field:

| Field | `source_name` |
|---|---|
| `vision_th` | วิสัยทัศน์ |
| `mission_th` | พันธกิจ |
| `philosophy_th` | ปรัชญาหลักสูตร |
| `institutional_identity_th` | อัตลักษณ์สถาบัน |
| `student_identity_th` | อัตลักษณ์บัณฑิต |

Each carries `stakeholder_type=INSTITUTIONAL_DIRECTION`, `classification="requirement"`,
`raw_text_th` = the field value, and a deterministic id `f"{program_id}-vision"`,
`f"{program_id}-mission"`, and so on. Deterministic ids matter: the repository upserts by
primary key, so re-running intake after the designer edits the vision replaces that one row
instead of accumulating a second copy.

The two optional identity fields produce no row when absent. `vision_th`, `mission_th`, and
`philosophy_th` are already required and non-empty at the model level.

This is what makes "every PLO traces to evidence" true for a PLO that exists because the
faculty's vision demands it — previously such a PLO had no evidence to point at.

### 4. demand_score: weighted frequency

`compute_demand_score` is replaced. Breadth is removed entirely; frequency is weighted by
who said it.

```python
EVIDENCE_WEIGHT: dict[StakeholderType, float] = {
    StakeholderType.PROFESSIONAL_COUNCIL: 1.0,      # external requirement
    StakeholderType.INSTITUTIONAL_DIRECTION: 0.8,   # internal requirement
    # every other external type: 0.6
    # every other internal type:  0.4
}
```

Resolution goes through `STAKEHOLDER_GROUP`, so a type added later gets 0.6 or 0.4 without
touching the table.

```
                Σ weight(evidence items mentioning this skill)
demand_score = ───────────────────────────────────────────────
                Σ weight(all evidence items in the program)
```

Both sums are over distinct evidence ids. The result is in [0, 1] by construction, and a
skill named by every source scores exactly 1.0. Adding a stakeholder type to the enum no
longer rescales stored scores, because `len(StakeholderType)` no longer appears in the
formula.

`is_optional` on a Need is derived from its member skills: optional when
`count(want) > count(requirement) + count(need)`. Same shape as the old rule, now reading
skill-level classification instead of evidence-level.

`WEIGHTED_CLASSES` and `total_req_need_evidence` disappear — the denominator is now every
evidence item, weighted, so there is nothing to filter.

`Need.classification_coverage` keeps its shape (`dict[str, int]`) but is now counted over
member *skills* rather than source evidence items, since that is where classification lives.
It is what `is_optional` reads, and the report shows it as "3 requirement / 2 need / 1 want"
under each Need.

### 5. KSEC: collapse SS/GS, merge E and C

```python
class KSECCategory(StrEnum):
    K = "K"    # ความรู้
    S = "S"    # ทักษะ            — SS and GS collapsed
    EC = "EC"  # คุณธรรมจริยธรรมและคุณลักษณะบุคคล, displayed "E|C"
    E = "E"    # คุณธรรมจริยธรรม — standalone when a Need is distinctly ethical
    C = "C"    # คุณลักษณะบุคคล  — standalone when a Need is distinctly about character
```

**A skill carries one of `K | S | E | C`.** The extraction prompt still distinguishes
ethics from character at the mention level, where the quoted span makes the difference
visible. It no longer distinguishes subject-specific from generic skill, which it was never
positioned to judge from one evidence item.

**A Need carries one of `K | S | EC | E | C`.** `bucket_by_ksec` maps `E → EC` and `C → EC`
*before* bucketing, so clustering runs over three buckets — `K`, `S`, `EC` — and still never
crosses one. After a group forms, its tag is decided from the raw tags of its members:

```
all members E  → E
all members C  → C
mixed          → EC
```

The KSEC bucketing invariant survives intact: clustering never crosses a bucket, and a Need
still holds exactly one tag. `E` and `C` remain reachable as standalone tags for a Need
whose evidence is unambiguously one or the other, which is what a มคอ.2 table needs when a
program has a distinct ethics outcome.

`orm.py` stores `ksec_category` as `String(2)`, so `"EC"` fits with no schema change. Rows
holding `SS` or `GS` are backfilled to `S`.

### 6. plo_report: summary and export only

Collapsing `SS`/`GS` removes the input that `plo_report` classified on
(`plo_report.py:34` counted source Needs tagged `SS`), and the generic/specific split is no
longer part of the design. The stage stops classifying.

Deleted: `_classify_one`, `_ClassificationResult`, `_SPECIFIC_HI`, `_SPECIFIC_LO`,
`_need_summary`, `prompts/plo_classify.py`, and the four PLO fields
`is_subject_specific`, `classification`, `classification_method`,
`classification_rationale_th`.

`plo_report.run()` keeps its place in the graph and its checkpoint (immutable rule 7), but
becomes a pure assembly step with no LLM call: it loads the program's PLOs and their source
Needs, resolves the evidence trail, and puts the assembled report into state. The page shows
every PLO with its Bloom level, KSEC tag, SMART soft flags, escalation status, and evidence
drill-down, plus the มคอ.2 and CHECO export buttons.

This does not collapse `plo_synthesis` into `plo_report` — the two stages and their two
checkpoints remain distinct, which is what the CLAUDE.md pitfall protects.

### 7. Provenance carried through to the UI

`ExtractedSkill` already receives `stakeholder_type` in the raw dict at
`skill_extraction.py:213` and discards it when the model is constructed. Both the source
evidence id and the stakeholder type are kept from now on, so a designer looking at a
grouped Need can see which stakeholders it came from without a query:

```python
class ExtractedSkill(BaseModel):
    source_evidence_id: str                       # unchanged
    source_stakeholder_type: StakeholderType      # new
    classification: SkillClassification           # new (§2)
    is_field_relevant: bool = True                # new (§2)


class Need(BaseModel):
    source_stakeholder_types: list[StakeholderType]  # new — distinct, from member skills
```

`Need.stakeholder_coverage` (counts per type) stays — it feeds nothing but the report and is
cheap to keep. `source_stakeholder_types` is the display list, ordered by the enum's
declaration order so external groups appear before internal ones.

## Schema and migration

Both `stakeholder_type` and `classification` are plain `VARCHAR` columns
(`orm.py:45` `String(50)`, `orm.py:51` `String(20)`) — not native PostgreSQL enums. No
`CREATE TYPE` exists anywhere in `migrations/` or `src/`. Changing the enum members
therefore needs **no type migration**, only a data backfill plus the new columns.

One Alembic revision does all of it:

1. `extracted_skills`: add `classification VARCHAR(20) NOT NULL DEFAULT 'unclassified'`,
   `is_field_relevant BOOLEAN NOT NULL DEFAULT true`,
   `source_stakeholder_type VARCHAR(50) NOT NULL DEFAULT 'employer'`.
2. `needs`: add `source_stakeholder_types JSONB NOT NULL DEFAULT '[]'`.
3. `plos`: drop `is_subject_specific`, `classification`, `classification_method`,
   `classification_rationale_th`.
4. Backfill `stakeholder_evidence.stakeholder_type`: `accreditation_body` →
   `professional_council`, `university` → `institutional_direction`, `subject_benchmark` →
   `expert`, `peer_program` → `partner_institution`.
5. Backfill `stakeholder_evidence.classification`: anything not `requirement` → `general`.
6. Backfill `extracted_skills.ksec_category` and `needs.ksec_category`: `SS` → `S`,
   `GS` → `S`.

Step 4 is not cosmetic. `Need.stakeholder_coverage` is typed
`dict[StakeholderType, int]`, so Pydantic validates its keys — a surviving row holding a
deleted value raises `ValidationError` inside `repositories.py:172` and breaks
`GET /evidence/` for the *entire program*, not just that row.

The extraction cache needs no manual invalidation. `_extraction_contract_fingerprint()`
hashes the response schema and the system prompt, both of which change here, so every stale
entry misses on its own. The per-item cache key at `skill_extraction.py:158` currently mixes
in `evidence.classification`; it keeps doing so, now with the two-value vocabulary.

## Frontend

Five files hardcode their own stakeholder label map today and none of them agree:
`StakeholderNeeds.tsx` omits `parent` (unreachable in the only dropdown that creates
evidence), `PloSynthesis.tsx` references `student` and `faculty` which do not exist in the
Python enum, and the `need` / `requirement` badge colours are swapped between two files.

All five are replaced by one module, `frontend/src/constants/stakeholder.ts`, exporting the
type list with Thai labels, the external/internal grouping, and the classification badge
colours. Every page imports from it. `SkillTable.tsx:167` indexes a colour map with no
fallback — the shared module's lookup returns a neutral default instead.

Page changes:

- **StakeholderNeeds** — the type dropdown becomes two `<optgroup>`s (ภายนอก / ภายใน)
  covering all 15 types. The classification column shows `requirement` / `general`.
- **SkillExtraction** — `SkillTable` gains a "ที่มา" column showing the stakeholder label
  and a classification badge (`requirement` / `need` / `want` / `unclassified`).
- **NeedCard** — shows the Need's `source_stakeholder_types` as badges, external first.
- **PloReport** — rewritten around §6: one list, no Generic/Specific columns, no flip
  action, no `ClassBadge`.
- **PloSynthesis** — drops the `subject-specific` badge at line 417.

## Testing

Unit tests, following the existing per-concern file convention:

- `test_models.py` — `STAKEHOLDER_GROUP` covers every `StakeholderType` member exactly once
  (a new type with no group entry must fail loudly, not default silently); `KSECCategory`
  holds the five new values and neither `SS` nor `GS`.
- `test_evidence_classification.py` (new) — the two requirement types map to `requirement`,
  every other type to `general`; the function is exhaustive over the enum.
- `test_skill_classification.py` (new) — one case per rule and one per precedence pair:
  requirement beats a `want` frequency of 1; requirement beats `is_field_relevant=False`;
  a name matching a requirement skill from a different evidence item is promoted; 2 distinct
  evidence ids → `need`; 1 → `want`; `is_field_relevant=False` on a non-requirement →
  `unclassified`.
- `test_demand.py` — a skill named by สภาวิชาชีพ scores above the same skill named by one
  employer; a skill named by every evidence item scores 1.0; adding a stakeholder type to
  the enum does not change an existing score (the regression the old `len(StakeholderType)`
  divisor caused).
- `test_intake_evidence.py` (new) — five populated fields produce five evidence rows, all
  `requirement`; absent optional identity fields produce none; re-running with an edited
  vision replaces the row rather than adding one (deterministic id).
- `test_need_grouping.py` — `bucket_by_ksec` puts `E` and `C` skills in one `EC` bucket and
  never mixes `K`, `S`, `EC`; Need tag resolution returns `E` for an all-`E` group, `C` for
  an all-`C` group, `EC` for a mixed one.
- `test_plo_report.py` — rewritten: `run()` assembles the report without any LLM call, and
  a PLO model rejects the four deleted fields.

Integration: `test_end_to_end.py` and `test_stage_3_plo.py` updated for the new enums and
the removed `is_subject_specific`. Stage-level repository mocks must stub every persistence
call a stage makes — `intake` now writes evidence as well as program metadata.

Migration: an Alembic upgrade/downgrade round-trip on a database seeded with one row per
deleted stakeholder type, asserting `GET /evidence/` returns 200 afterwards.

## Documentation

`CLAUDE.md`, `.claude/skills/curriculum-design-agent/SKILL.md`, and the three reference
files (`obe-principles.md`, `prompts.md`, `data-schemas.md`) all describe the old
classification model, the SS/GS split, and `plo_report`'s generic/specific job. Each is
updated with this design. The skill remains the canonical source for OBE rules; this spec is
the record of why they changed.

## Out of scope

- Semantic (LLM) matching between a `need`/`want` skill and a `requirement` skill.
  Normalised-name matching is the rule; semantic grouping stays in `need_combination`.
- Weighting individual evidence items within a stakeholder type. The weight comes from the
  type alone.
- Re-adding YLO/CLO, changing the SMART gate, or changing the `MIN_NEEDS = 6` floor.
