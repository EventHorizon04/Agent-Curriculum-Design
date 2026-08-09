# Data Schemas Reference

These are the Pydantic models that flow between agent stages. Use them to type LLM outputs (via Instructor), persist to Postgres, and validate user uploads. When asked to add a field or create a new model, follow the patterns here.

All models use Pydantic v2.

## Core principle: evidence trail

Every artifact derived from another must carry the IDs of its sources. This is non-negotiable — it's how the agent answers "where did this PLO come from?" during accreditation review.

```
StakeholderEvidence (raw)
  ↓ source_evidence_id + evidence_span_th (verified in code)
ExtractedSkill (per evidence item)
  ↓ member_skill_ids
Need (grouped skills, one KSEC tag, one sentence)
  ↓ source_need_ids
PLO (final artifact — agent scope ends here)
```

Never break the chain. If a model doesn't have a source-tracing field (or equivalent), you can't trace its provenance. Two of these links are enforced in pure code, not just by convention: `ExtractedSkill.evidence_span_th` must actually occur in its source evidence (`is_grounded()` in `stages/skill_extraction.py`), and `PLO.source_need_ids` / `PLO.source_evidence_ids` are rejected as empty by a Pydantic validator.

## Stage 1: Program metadata

```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class ProgramMetadata(BaseModel):
    """Set in Stage 1 (Intake). The fixed context all later stages reference."""
    program_id: str
    # A program is identified by university/faculty/field. The names remain for
    # rows created before intake dropped them, and default to "" otherwise.
    name_th: str = ""
    name_en: str = ""
    field: str  # e.g. "Computer Science", "ความสัมพันธ์ระหว่างประเทศ"
    isced_code: str | None = None  # ISCED-F 2013 detailed code, validated against the taxonomy
    degree_level: Literal["bachelor", "master", "doctoral"]
    duration_years: int = Field(ge=1, le=8)
    faculty: str
    university: str
    professional_council: str | None = None  # e.g. "สภาวิศวกร"
    accreditation_body: str | None = None  # e.g. "AUN-QA", "ABET" — program metadata only, unrelated to StakeholderType
    subject_benchmark_ref: str | None = None  # มคอ.1 reference — program metadata only, unrelated to StakeholderType
    # Both default to []: intake stopped collecting them. Persisted rows keep
    # whatever they already hold, and CHECO 1.5 still reads program_objectives_th.
    program_objectives_th: list[str] = []
    program_goals_th: list[str] = []
    created_at: datetime
```

**The institution's own direction is not metadata.** `vision_th`, `mission_th`, `philosophy_th`, `institutional_identity_th`, and `student_identity_th` were fields here and are gone — along with `build_institutional_evidence`, which converted them into evidence rows at intake. The designer now records those statements directly at stage 2 as `StakeholderEvidence` with `stakeholder_type=INSTITUTIONAL_DIRECTION` (`classification="requirement"`, derived in code like every other type). One home for a statement, not two, and the evidence trail works the same way for the institution's voice as for any other stakeholder's. Whether the program covered it at all is a program-level check in `plo_synthesis.run`, not a field's presence.

`isced_code` is validated against the ISCED-F 2013 taxonomy (`data/isced.py`) on `ProgramCreateRequest` only — `ProgramMetadata` overrides that validator to a no-op so a persisted row whose code later left the taxonomy still deserializes. Intake has no input for it, no LLM suggestion, and no document upload.

**`program_id` comes from `field`.** With no program name to slug, `_generate_program_id` slugs the field of study and appends `-2`, `-3`, … on collision. `_slugify` keeps ASCII only, so a Thai field yields `program`, `program-2`, … — readable ids are a nice-to-have, uniqueness is not. Anything showing a program to a human should fall back through name → field → id; `ProgramSummary` carries `field` and `faculty` for exactly that.

## Stage 2: Stakeholder evidence

```python
class StakeholderGroup(str, Enum):
    """Whether a stakeholder speaks from outside the institution or inside it."""
    EXTERNAL = "external"
    INTERNAL = "internal"

class StakeholderType(str, Enum):
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
    INSTITUTIONAL_DIRECTION = "institutional_direction"  # vision/mission/philosophy/identity — one voice, several documents
    ADMINISTRATOR = "administrator"                 # ผู้บริหาร
    PROGRAM_COMMITTEE = "program_committee"          # คณะกรรมการหลักสูตร
    FACULTY = "faculty"                              # อาจารย์
    STUDENT = "student"                              # ผู้เรียน
    SUPPORT_STAFF = "support_staff"                   # บุคลากรสายสนับสนุน

# The single mapping from type to group. Nothing else may hardcode the split —
# the demand weight table (stages/demand.py) and any UI grouping read from it.
STAKEHOLDER_GROUP: dict[StakeholderType, StakeholderGroup] = {...}

# สภาวิชาชีพ sets legal practice requirements; the institution's own vision/
# mission/identity is a mandate it committed to. Every other type is `general`.
REQUIREMENT_TYPES = frozenset(
    {StakeholderType.PROFESSIONAL_COUNCIL, StakeholderType.INSTITUTIONAL_DIRECTION}
)

class StakeholderEvidence(BaseModel):
    """Raw evidence collected in Stage 2. The 'source of truth' for traceability."""
    evidence_id: str  # uuid
    program_id: str
    stakeholder_type: StakeholderType
    source_name: str  # e.g. "JobThai posting #12345" or "วิสัยทัศน์" for institutional-direction rows
    source_url: str | None = None
    raw_text_th: str  # original Thai text
    raw_text_en: str | None = None  # English original if available
    collected_at: datetime
    # requirement vs general — a two-value vocabulary, decided in code
    classification: Literal["requirement", "general"] = "general"
    classification_rationale_th: str | None = None  # manual-override field; the stage no longer writes an LLM rationale into it
    metadata: dict = {}  # job title, salary, location, etc. for job postings
```

**Deleted:** `ACCREDITATION_BODY`, `UNIVERSITY`, `SUBJECT_BENCHMARK`, `PEER_PROGRAM`. `ProgramMetadata.professional_council`, `.accreditation_body`, and `.subject_benchmark_ref` are unrelated program-metadata fields and are untouched.

Why `classification` moved to two values: "how many sources asked for this" is a property of a *skill* across evidence items, not of one evidence item — a job posting is not "a need", it mentions capabilities, some rare and some common. Evidence-level `classification` is now a pure lookup (`classify_evidence_type` in `stages/stakeholder_needs.py`) from `stakeholder_type` — no LLM call, no judgement: `PROFESSIONAL_COUNCIL` and `INSTITUTIONAL_DIRECTION` are `requirement`, every other type is `general`. The `need`/`want`/`unclassified` vocabulary lives one level down, on `ExtractedSkill` — see Stage 3.

## Stage 3: Extracted skills, and Needs (Stage 3b: need_combination)

```python
class KSECCategory(str, Enum):
    """TQF/มคอ. competency domains, pre-tagging every ExtractedSkill for eventual
    มคอ.2/CHECO mapping. NOT a Bloom domain — it is orthogonal to bloom_level.
    A skill carries one of K/S/E/C; a Need carries one of K/S/EC/E/C — EC is a
    Need-level umbrella tag produced when a group mixes E and C members."""
    K = "K"    # ความรู้
    S = "S"    # ทักษะ — SS and GS collapsed into one tag
    EC = "EC"  # คุณธรรมจริยธรรมและคุณลักษณะบุคคล — Need-level only, displayed "E|C"
    E = "E"    # คุณธรรมจริยธรรม — standalone when a Need is distinctly ethical
    C = "C"    # คุณลักษณะบุคคล — standalone when a Need is distinctly about character

# The tags an ExtractedSkill may carry. EC is Need-level only.
SKILL_KSEC = frozenset({KSECCategory.K, KSECCategory.S, KSECCategory.E, KSECCategory.C})

class ExtractedSkill(BaseModel):
    """A single skill mention extracted from one evidence item. High-volume."""
    skill_id: str
    program_id: str
    skill_name_th: str = Field(min_length=1)  # a phrase, never a bare word
    skill_name_en: str | None = None
    ksec_category: KSECCategory  # one of K/S/E/C — never EC at skill level
    # Cognitive scale only, and required. Psychomotor/affective are not
    # modelled anywhere in the agent — it stops at PLO and every PLO it
    # produces is cognitive.
    bloom_level: BloomLevel
    # Verbatim quote from the source evidence that justifies this skill.
    # Verified against the evidence text in pure code, not trusted from the
    # LLM — see `is_grounded()` below.
    evidence_span_th: str = Field(min_length=1)
    source_evidence_id: str  # FK to StakeholderEvidence
    source_stakeholder_type: StakeholderType  # provenance kept for the UI — which stakeholder named this skill
    # need/want/unclassified/requirement — decided in code by classify_skills,
    # once every evidence item in the program has been extracted (see below).
    classification: Literal["requirement", "need", "want", "unclassified"] = "unclassified"
    # Set by the extraction model in the same call as the rest of the skill:
    # does this belong to the program's field at all? False yields
    # `unclassified` unless the skill is mandated (see precedence below).
    is_field_relevant: bool = True
    extraction_method: Literal["llm", "manual"]
    confidence: float = Field(ge=0, le=1)
    # Per-skill-name demand, computed pre-grouping with the SAME weighting as
    # Need.demand_score, grouped by normalized skill_name_th instead of Need
    # membership. Every mention of the same skill name across evidence carries
    # the same importance_score.
    importance_score: float = Field(ge=0, le=1)

class Need(BaseModel):
    """Output of need_combination — a market-side demand distilled from a
    group of extracted skills. One sentence stating what the labour market
    asks for; PLO synthesis restates it from the graduate's side."""
    need_id: str
    program_id: str
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None
    ksec_category: KSECCategory  # single-valued by construction — see below; one of K/S/EC/E/C
    bloom_level: BloomLevel  # highest Bloom level among member skills
    member_skill_ids: list[str] = Field(min_length=1)  # ExtractedSkill IDs
    source_evidence_ids: list[str] = Field(min_length=1)
    stakeholder_coverage: dict[StakeholderType, int] = {}  # which groups, how often
    source_stakeholder_types: list[StakeholderType] = []  # distinct types, external first (enum order) — the display list
    freq: int = Field(ge=1)  # = len(member_skill_ids), a raw mention count
    demand_score: float = Field(ge=0, le=1)  # weighted frequency over evidence weights
    is_optional: bool = False  # majority-want group → supplementary, not core
    classification_coverage: dict[str, int] = {}  # member-skill count per classification
    sample_quotes_th: list[str] = []  # up to 3-5 illustrative excerpts
```

**Groundedness (`ExtractedSkill.evidence_span_th`):** verified by `is_grounded()` in `stages/skill_extraction.py`. A span passes only if, after whitespace-normalisation, it is at least `_MIN_SPAN_CHARS` (12) characters long *and* occurs verbatim in the source evidence text. Skills whose quote is too short to prove anything, or whose quote isn't actually in the evidence (a fabrication), are dropped before persistence; the stage counts and logs both drop reasons separately (`dropped_too_short` / `dropped_not_found`) and the total dropped count travels in `AgentState["dropped_ungrounded_count"]` for checkpoint display.

**Skill classification (`ExtractedSkill.classification`):** computed once, in `skill_extraction.classify_skills`, after every evidence item in the program has been extracted — need vs want is a cross-evidence frequency property and cannot be known per-item. Precedence, highest first:

1. Named by evidence whose `classification == "requirement"` → `requirement`.
2. Its normalized name (`need_grouping.normalize_need_name`) matches a skill already classified `requirement` by rule 1 → `requirement`. **Requirement wins**: a สภาวิชาชีพ mandate or the faculty's own vision stays in the pipeline whatever the extraction model thought of its field fit.
3. `is_field_relevant == False` → `unclassified`.
4. Named by more than one distinct `source_evidence_id` → `need`.
5. Otherwise → `want`.

Rules 1–2 outrank 3 on purpose — a mandated skill is never dropped for being judged off-field. Semantic matching is deliberately not used in rule 2 (that is what LLM clustering does one stage later, in `need_combination`); only normalized-name matching.

**Single-tag guarantee (`Need.ksec_category`):** `need_combination` buckets `ExtractedSkill`s by `ksec_category` (`bucket_by_ksec` in `stages/need_grouping.py`) *before* clustering — `E` and `C` share one `EC` bucket, everything else buckets by its own tag — and clustering never fuses groups across buckets. A Need mixing two of `K`/`S`/`EC` is therefore structurally impossible. After a group forms, `resolve_need_ksec` decides its tag from its raw member tags: all-`E` → `E`, all-`C` → `C`, mixed → `EC`.

`demand_score` is the signal the agent uses to decide which Needs are core vs optional. The weighting rule (`compute_demand_score` / `evidence_weight` in `stages/demand.py`, shared by skill-level `importance_score` and Need-level `demand_score`):

- Pure weighted frequency, no breadth term: `demand_score = Σ weight(evidence items naming this skill/Need) / Σ weight(all evidence items in the program)`, both sums over distinct evidence ids.
- Weight comes from who said it, resolved through `STAKEHOLDER_GROUP`: `PROFESSIONAL_COUNCIL` = 1.0, `INSTITUTIONAL_DIRECTION` = 0.8, every other external type = 0.6, every other internal type = 0.4. A type added to the enum later gets 0.6/0.4 automatically.
- `is_optional` on a Need is derived from its member skills' classifications: `want` count > `requirement` count + `need` count.
- `classification_coverage` records the per-classification count over member *skills* (not source evidence items, since that is where classification now lives) — the report shows it as e.g. "3 requirement / 2 need / 1 want" under each Need.

**Floor, no cap:** `need_combination` no longer merges core groups down to a quota — every core group clustering finds within a KSEC bucket becomes its own Need. `MIN_NEEDS=6` in `stages/need_grouping.py` is a floor only: if the program ends with fewer than 6 core Needs, `need_combination` logs a policy warning (and `plo_synthesis` logs its own if the resulting core PLO count is still short) for the designer to address at the checkpoint. PLO synthesis then maps one Need to one PLO (see below), so whatever core count `need_combination` produces carries through unchanged. Optional (want-dominant) Needs are exempt from the floor, same as optional PLOs.

## Stage 4: PLO (plo_synthesis) — cognitive-only, one Need → one PLO

```python
# Bloom's Taxonomy has three learning-domain scales in the OBE tradition
# (see obe-principles.md for the full three-domain picture), but PLO is
# cognitive-only: the agent's scope ends at PLO, and the other two domains'
# level scales are YLO/CLO-era faculty work, not modelled here. This
# codebase has no second or third level-scale class alongside BloomLevel.

class BloomLevel(str, Enum):
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"

class SMARTCheck(BaseModel):
    # Each field combines its hard check (pure code) with the matching soft
    # verdict from the light-model judge — none of these are hardcoded True.
    specific: bool   # S_VERB not failed AND judge.specific_object_ok
    measurable: bool # M_FORBIDDEN not failed AND judge.measurable_ok
    achievable: bool # judge.achievable_ok (no hard counterpart)
    relevant: bool   # R_EVIDENCE not failed AND judge.relevant_needs_ok
    timely: bool     # judge.time_bound_ok (no hard counterpart, defaults true)
    notes_th: str | None = None  # rationale or what fails

class PLO(BaseModel):
    """A Program Learning Outcome — what every graduate can do at graduation."""
    # Assigned by code, never by the model — see the note below the class.
    plo_id: str  # "PLO1".."PLOn" for the main set, "OPT1".."OPTn" for supplementary
    program_id: str
    statement_th: str  # the actual outcome text in Thai
    statement_en: str | None = None
    bloom_level: BloomLevel  # cognitive only — no domain field, no other scale
    action_verb_th: str  # the single Bloom verb extracted
    smart_check: SMARTCheck
    source_need_ids: list[str]  # Need IDs that justify this PLO (1+ — see below)
    source_evidence_ids: list[str] = []  # rolled up from those Needs
    rationale_th: str  # why this PLO exists, for designer review
    distinctive_feature_th: str | None = None  # what differentiates this PLO
    version: int = 1
    smart_retry_count: int = 0  # SMART hard-fail fix attempts consumed (max 3)
    smart_escalated: bool = False  # still hard-failing after retries → human repair
    soft_flags: list[str] = []  # non-blocking: "S_object", "M_assessable", "A_level", "R_needs", "T_horizon"
    is_optional: bool = False  # PLO from want-dominant Need(s), exempt from the core-Need count
```

**One Need → one PLO, with a designer escape hatch.** `stages/plo_synthesis.run()` drafts exactly one PLO per Need — a single focused LLM call each, not a batch call over all Needs. A designer can also merge several Needs into one PLO via `POST /programs/{id}/plos/from-needs`, which calls the same `synthesize_from_needs()` function with more than one Need; that function is shared by both paths so both get identical SMART enforcement and evidence handling. When multiple Needs feed one PLO, `is_optional` is true only if *every* contributing Need is optional. `plo_report` no longer classifies the result generic vs specific — that split (and the `SS`/`GS` KSEC tags it read) no longer exists; the report shows each PLO's actual KSEC tag (`K`/`S`/`EC`/`E`/`C`) instead.

**`plo_id` is assigned by code, never requested from the model.** `PLO1`..`PLOn` for the main set, ordered by descending `Need.demand_score` with `need_id` breaking ties, so `PLO1` is the capability the labour market asked for most and the numbering reproduces across re-runs on the same Needs. Supplementary outcomes from want-dominant Needs get their own `OPT1`..`OPTn` series. Helpers live in `stages/plo_synthesis.py`: `format_plo_id`, `next_plo_id` (for the designer-driven merge endpoint, which creates one outcome at a time), and `synthesis_order`.

This is not a style preference. Synthesis issues one LLM call per Need with no knowledge of the other calls, so a model asked to name its own outcome returns `PLO1` every time; `plo_id` is the table's primary key and `PLORepository.bulk_insert` upserts, so a duplicate silently overwrites instead of failing — a whole set collapsing into one row while the run reports success. A Need whose synthesis fails leaves its number unused rather than renumbering the rest, because designers cite these ids and renumbering would change what `PLO4` refers to between runs.

Validation rules for PLO (enforce in code):
- `statement_th` must not contain forbidden words (รู้, จำ, เข้าใจ, ซาบซึ้ง, ตระหนัก, ศรัทธา, รัก) — see `obe-principles.md`. Exception: a PLO with `smart_escalated=True` may carry them — it exists precisely so a human can repair it, and the SMART gate already failed it loudly.
- `source_need_ids` must be non-empty (no PLO without a Need behind it), and `source_evidence_ids` must be non-empty (no PLO without an evidence trail) — two separate validators, both hard rejects.
- `smart_check` all five fields must be `True` to mark the PLO ready
- Hard vs soft failure handling: S-verb / M-forbidden / R-evidence failures (pure code, `stages/smart_rules.py`) trigger the automated SMART retry loop (max 3, criterion named in the retry prompt; unfixed → `smart_escalated=True`). S-object / A-level / R-alignment concerns come from one light-model judge call and land in `soft_flags` without blocking. Implement per the SMART validation checklist in `obe-principles.md`.

## Cross-stage: human-in-the-loop checkpoint

```python
class StageCheckpoint(BaseModel):
    """Saved at every stage boundary for human review."""
    checkpoint_id: str
    program_id: str
    stage: Literal[
        "intake", "stakeholder_needs", "skill_extraction",
        "need_combination", "plo_synthesis", "plo_report",
    ]
    artifacts: dict  # serialized output of the stage
    created_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    status: Literal["pending", "approved", "needs_revision", "rejected"] = "pending"
    designer_notes_th: str | None = None
    edits: dict = {}  # any edits the designer made
```

LangGraph's interrupt mechanism saves a `StageCheckpoint` and waits. The React UI fetches pending checkpoints via the FastAPI routes, lets the designer edit, then signals approval. The graph resumes with the (possibly edited) artifacts.

Note: `skill_extraction` and `need_combination` are separate graph nodes but share one checkpoint, placed after `need_combination` — the designer reviews raw extracted skills and the distilled Needs together in one review, not at two separate boundaries. Every other stage boundary gets its own checkpoint.

## Versioning

PLOs are mutable objects under designer review. Use this versioning approach:

- `version: int` on PLO, starts at 1
- On every edit, increment version and write a new row (don't update in place)
- Keep a `current_version_id` on the program for the active set
- This preserves audit trail for accreditation

## Database mapping

These Pydantic models map to Postgres tables 1:1 with these adjustments:
- `list[str]` fields → JSON column or junction table depending on access pattern
- `dict` metadata → JSONB column
- `datetime` → `timestamptz`
- Enums → Postgres enum types or text with check constraint

Use SQLAlchemy 2.0 with Pydantic for the ORM layer. Schema changes go through Alembic migrations.

## Export formats

For CHECO and มคอ.2 export, derive the document from these models. Don't store CHECO-specific fields on the core models — keep the core clean and transform at export time.

Mapping summary:
- `PLO.statement_th` → CHECO 1.6.2 (ผลลัพธ์การเรียนรู้ของหลักสูตร)
- `ProgramMetadata.program_objectives_th` → CHECO 1.5
