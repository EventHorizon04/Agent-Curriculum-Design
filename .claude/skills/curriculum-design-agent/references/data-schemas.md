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
    name_th: str
    name_en: str
    field: str  # e.g. "Computer Science", "Packaging Design"
    degree_level: Literal["bachelor", "master", "doctoral"]
    duration_years: int = Field(ge=1, le=8)
    faculty: str
    university: str
    vision_th: str  # university/faculty vision
    student_identity_th: str | None = None  # อัตลักษณ์นิสิต if defined
    professional_council: str | None = None  # e.g. "สภาวิศวกร"
    accreditation_body: str | None = None  # e.g. "AUN-QA", "ABET"
    subject_benchmark_ref: str | None = None  # มคอ.1 reference
    program_objectives_th: list[str]  # วัตถุประสงค์ของหลักสูตร
    created_at: datetime
```

## Stage 2: Stakeholder evidence

```python
class StakeholderType(str, Enum):
    EMPLOYER = "employer"
    ALUMNI = "alumni"
    PROFESSIONAL_COUNCIL = "professional_council"
    ACCREDITATION_BODY = "accreditation_body"
    UNIVERSITY = "university"
    COMMUNITY = "community"
    PARENT = "parent"
    SUBJECT_BENCHMARK = "subject_benchmark"  # มคอ.1
    PEER_PROGRAM = "peer_program"

class StakeholderEvidence(BaseModel):
    """Raw evidence collected in Stage 2. The 'source of truth' for traceability."""
    evidence_id: str  # uuid
    program_id: str
    stakeholder_type: StakeholderType
    source_name: str  # e.g. "JobThai posting #12345" or "TPQI subject benchmark"
    source_url: str | None = None
    raw_text_th: str  # original Thai text
    raw_text_en: str | None = None  # English original if available
    collected_at: datetime
    # need vs requirement vs want classification, set in Stage 2
    classification: Literal["need", "requirement", "want", "unclassified"] = "unclassified"
    metadata: dict = {}  # job title, salary, location, etc. for job postings
```

Why `classification`: distinguishing needs (must-have) from wants (nice-to-have) is central to the pipeline. `want` is never chosen by the LLM: `COMMUNITY` and `PARENT` evidence is always classified `want` in pure code (deterministic, no LLM call — `WANT_ONLY_TYPES` in `stages/stakeholder_needs.py`); every other stakeholder type goes to the LLM, whose schema only offers `need` / `requirement` / `unclassified`. This binds in both directions — those two types are never anything but `want`, and no other type is ever `want`.

## Stage 3: Extracted skills, and Needs (Stage 3b: need_combination)

```python
class KSECCategory(str, Enum):
    """TQF/มคอ. competency domains collapsed to five tags, pre-tagging every
    ExtractedSkill for eventual มคอ.2/CHECO mapping. NOT a Bloom domain — it is
    orthogonal to bloom_level. One skill has exactly one tag; "mixed" is
    unrepresentable by construction."""
    K = "K"    # ความรู้
    GS = "GS"  # ทักษะทั่วไป (generic/transferable)
    SS = "SS"  # ทักษะเฉพาะสาขา (subject-specific)
    C = "C"    # คุณลักษณะบุคคล
    E = "E"    # คุณธรรมจริยธรรม

class ExtractedSkill(BaseModel):
    """A single skill mention extracted from one evidence item. High-volume."""
    skill_id: str
    program_id: str
    skill_name_th: str = Field(min_length=1)  # a phrase, never a bare word
    skill_name_en: str | None = None
    ksec_category: KSECCategory  # always set — replaces the old separate type tag + specificity flag
    # Cognitive scale only, and required. Psychomotor/affective are not
    # modelled anywhere in the agent — it stops at PLO and every PLO it
    # produces is cognitive.
    bloom_level: BloomLevel
    # Verbatim quote from the source evidence that justifies this skill.
    # Verified against the evidence text in pure code, not trusted from the
    # LLM — see `is_grounded()` below.
    evidence_span_th: str = Field(min_length=1)
    source_evidence_id: str  # FK to StakeholderEvidence
    extraction_method: Literal["llm", "manual"]
    confidence: float = Field(ge=0, le=1)
    # Per-skill-name demand, computed pre-grouping with the SAME weighting as
    # Need.demand_score (requirement+need evidence only, want=0 weight),
    # grouped by skill_name_th instead of Need membership. Every mention of
    # the same skill name across evidence carries the same importance_score.
    importance_score: float = Field(ge=0, le=1)

class Need(BaseModel):
    """Output of need_combination — a market-side demand distilled from a
    group of extracted skills. One sentence stating what the labour market
    asks for; PLO synthesis restates it from the graduate's side."""
    need_id: str
    program_id: str
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None
    ksec_category: KSECCategory  # single-valued by construction — see below
    bloom_level: BloomLevel  # highest Bloom level among member skills
    member_skill_ids: list[str] = Field(min_length=1)  # ExtractedSkill IDs
    source_evidence_ids: list[str] = Field(min_length=1)
    stakeholder_coverage: dict[StakeholderType, int] = {}  # which groups, how often
    freq: int = Field(ge=1)  # = len(member_skill_ids), a raw mention count
    demand_score: float = Field(ge=0, le=1)  # weighted frequency × stakeholder breadth
    is_optional: bool = False  # majority-want group → supplementary, not core
    classification_coverage: dict[str, int] = {}  # evidence count per classification
    sample_quotes_th: list[str] = []  # up to 3-5 illustrative excerpts
```

**Groundedness (`ExtractedSkill.evidence_span_th`):** verified by `is_grounded()` in `stages/skill_extraction.py`. A span passes only if, after whitespace-normalisation, it is at least `_MIN_SPAN_CHARS` (12) characters long *and* occurs verbatim in the source evidence text. Skills whose quote is too short to prove anything, or whose quote isn't actually in the evidence (a fabrication), are dropped before persistence; the stage counts and logs both drop reasons separately (`dropped_too_short` / `dropped_not_found`) and the total dropped count travels in `AgentState["dropped_ungrounded_count"]` for checkpoint display.

**Single-tag guarantee (`Need.ksec_category`):** `need_combination` buckets `ExtractedSkill`s by `ksec_category` (`bucket_by_ksec` in `stages/need_grouping.py`) *before* clustering, and both the semantic merge and the demand-ranked fallback merge only ever fuse groups within one bucket. A Need mixing two KSEC tags is therefore structurally impossible, not just a convention.

`demand_score` is the signal the agent uses to decide which Needs are core vs optional. The weighting rule (`compute_demand_score` in `stages/demand.py`, shared by skill-level `importance_score` and Need-level `demand_score`):

- Only **requirement + need** evidence carries weight (unclassified counts as need); **want evidence contributes zero**.
- `score = min(freq * 0.6 + breadth * 0.4, 1.0)` where `freq` = weighted-evidence count / total requirement+need evidence, `breadth` = stakeholder-group coverage ratio.
- A group whose want-evidence count exceeds its requirement+need count gets `is_optional=True` — it feeds the optional PLO pass, not the main core set.
- `classification_coverage` records the per-classification evidence counts for checkpoint display.

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
    specific: bool
    measurable: bool
    achievable: bool
    relevant: bool
    timely: bool
    notes_th: str | None = None  # rationale or what fails

class PLO(BaseModel):
    """A Program Learning Outcome — what every graduate can do at graduation."""
    # Assigned by code, never by the model — see the note below the class.
    plo_id: str  # "PLO1".."PLOn" for the main set, "OPT1".."OPTn" for supplementary
    program_id: str
    statement_th: str  # the actual outcome text in Thai
    statement_en: str | None = None
    bloom_level: BloomLevel  # cognitive only — no domain field, no other scale
    is_subject_specific: bool
    action_verb_th: str  # the single Bloom verb extracted
    smart_check: SMARTCheck
    source_need_ids: list[str]  # Need IDs that justify this PLO (1+ — see below)
    source_evidence_ids: list[str] = []  # rolled up from those Needs
    rationale_th: str  # why this PLO exists, for designer review
    distinctive_feature_th: str | None = None  # what differentiates this PLO
    version: int = 1
    classification: Literal["generic", "specific"] | None = None  # set in plo_report
    classification_method: Literal["ksec", "llm", "manual"] | None = None
    classification_rationale_th: str | None = None
    smart_retry_count: int = 0  # SMART hard-fail fix attempts consumed (max 3)
    smart_escalated: bool = False  # still hard-failing after retries → human repair
    soft_flags: list[str] = []  # non-blocking review flags: "S_object", "A_level", "R_alignment"
    is_optional: bool = False  # PLO from want-dominant Need(s), exempt from the core-Need count
```

**One Need → one PLO, with a designer escape hatch.** `stages/plo_synthesis.run()` drafts exactly one PLO per Need — a single focused LLM call each, not a batch call over all Needs. A designer can also merge several Needs into one PLO via `POST /programs/{id}/plos/from-needs`, which calls the same `synthesize_from_needs()` function with more than one Need; that function is shared by both paths so both get identical SMART enforcement and evidence handling. When multiple Needs feed one PLO, `is_subject_specific` is true if *any* contributing Need is SS, and `is_optional` is true only if *every* contributing Need is optional.

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
