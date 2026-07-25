# Data Schemas Reference

These are the Pydantic models that flow between agent stages. Use them to type LLM outputs (via Instructor), persist to Postgres, and validate user uploads. When asked to add a field or create a new model, follow the patterns here.

All models use Pydantic v2.

## Core principle: evidence trail

Every artifact derived from another must carry the IDs of its sources. This is non-negotiable — it's how the agent answers "where did this PLO come from?" during accreditation review.

```
StakeholderEvidence (raw)
  ↓ source_ids
ExtractedSkill (per evidence item)
  ↓ source_ids: list[str]
SkillCluster (grouped skills)
  ↓ source_ids: list[str]
PLO (final artifact — agent scope ends here)
```

Never break the chain. If a model doesn't have a `source_ids` or equivalent field, you can't trace its provenance.

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
    # need vs want classification, set by Stage 2 LLM
    classification: Literal["need", "requirement", "want", "unclassified"] = "unclassified"
    metadata: dict = {}  # job title, salary, location, etc. for job postings
```

Why `classification`: distinguishing needs (must-have) from wants (nice-to-have) is central to the pipeline. Stage 2 ends with a classification step before passing to Stage 3.

## Stage 3: Extracted skills and clusters

```python
class KSECCategory(str, Enum):
    """TQF 4-domain collapse (มคอ. domains 1-5 rolled into 4 tags)."""
    KNOWLEDGE = "K"  # ความรู้
    SKILL = "S"      # ทักษะทางปัญญา + ปฏิบัติ + ความสัมพันธ์ระหว่างบุคคล + วิเคราะห์ตัวเลข/สื่อสาร/IT
    ETHICS = "E"      # คุณธรรมจริยธรรม
    CHARACTER = "C"   # คุณลักษณะบุคคล

class ExtractedSkill(BaseModel):
    """A single skill mention extracted from one evidence item. High-volume."""
    skill_id: str
    program_id: str
    skill_name_th: str
    skill_name_en: str | None = None
    skill_type: Literal["knowledge", "psychomotor", "affective", "mixed"]
    is_subject_specific: bool  # vs generic transferable
    source_evidence_id: str  # FK to StakeholderEvidence
    extraction_method: Literal["keybert", "llm", "manual", "ner"]
    confidence: float = Field(ge=0, le=1)
    # Cognitive-only Bloom tag — no psychomotor/krathwohl scale at extraction
    # level; those get assigned later at cluster level once domain settles.
    # None for KeyBERT-only fallback mentions (no LLM tagging pass).
    bloom_level: BloomLevel | None = None
    # TQF K/S/E/C category. Always set — defaults to K for KeyBERT fallback.
    ksec_category: KSECCategory
    # Per-skill-name demand, computed pre-clustering with the SAME weighting as
    # SkillCluster.demand_score (requirement+need evidence only, want=0 weight),
    # grouped by skill_name_th instead of cluster membership. Every mention of
    # the same skill name across evidence carries the same importance_score.
    importance_score: float = Field(ge=0, le=1)

class SkillCluster(BaseModel):
    """Output of Stage 3 — grouped skills representing a coherent capability."""
    cluster_id: str
    program_id: str
    canonical_name_th: str  # cluster's representative name
    canonical_name_en: str | None = None
    description_th: str
    skill_type: Literal["knowledge", "psychomotor", "affective", "mixed"]
    is_subject_specific: bool
    member_skill_ids: list[str]  # ExtractedSkill IDs in this cluster
    source_evidence_ids: list[str]  # all evidence behind this cluster
    stakeholder_coverage: dict[StakeholderType, int]  # which groups mentioned it, how often
    demand_score: float = Field(ge=0, le=1)  # weighted frequency × stakeholder breadth
    is_common_need: bool = False  # appears in multiple stakeholder groups → likely PLO
    sample_quotes_th: list[str] = []  # 2-3 illustrative excerpts
    bloom_level: BloomLevel | None = None  # tagged by light model (knowledge/mixed clusters)
    psychomotor_level: PsychomotorLevel | None = None  # tagged for psychomotor clusters
    krathwohl_level: KrathwohlLevel | None = None  # tagged for affective clusters
    is_optional: bool = False  # majority-want cluster → supplementary, not core
    classification_coverage: dict[str, int] = {}  # evidence count per classification, e.g. {"need": 3, "want": 1}
```

`demand_score` is the data-science output that the agent uses to decide which clusters are PLO-worthy. The weighting rule (implemented in `_compute_demand_score` in `stages/skill_extraction.py`):

- Only **requirement + need** evidence carries weight (unclassified counts as need); **want evidence contributes zero**.
- `score = min(freq * 0.6 + breadth * 0.4, 1.0)` where `freq` = weighted-evidence count / total requirement+need evidence, `breadth` = stakeholder-group coverage ratio.
- A cluster whose want-evidence count exceeds its requirement+need count gets `is_optional=True` — it feeds the optional PLO pass, not the main 6–10 set.
- `classification_coverage` records the per-classification evidence counts for checkpoint display.

## Stage 4: PLO

```python
# Bloom's Taxonomy — one level scale per learning domain:
#   Cognitive (Knowledge/Thinking) → BloomLevel
#   Psychomotor (Skill/Doing)      → PsychomotorLevel (Dave)
#   Affective (Attitude/Feeling)   → KrathwohlLevel

class BloomLevel(str, Enum):
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"

class PsychomotorLevel(str, Enum):
    IMITATE = "imitate"
    MANIPULATE = "manipulate"
    PRECISE = "precise"
    ARTICULATE = "articulate"
    NATURALIZE = "naturalize"

class KrathwohlLevel(str, Enum):
    RECEIVING = "receiving"
    RESPONDING = "responding"
    VALUING = "valuing"
    ORGANIZATION = "organization"
    CHARACTERIZATION = "characterization"

class SMARTCheck(BaseModel):
    specific: bool
    measurable: bool
    achievable: bool
    relevant: bool
    timely: bool
    notes_th: str | None = None  # rationale or what fails

class PLO(BaseModel):
    """A Program Learning Outcome — what every graduate can do at graduation."""
    plo_id: str  # e.g. "PLO1"
    program_id: str
    statement_th: str  # the actual outcome text in Thai
    statement_en: str | None = None
    domain: Literal["cognitive", "psychomotor", "affective"]
    bloom_level: BloomLevel | None = None  # for cognitive
    psychomotor_level: PsychomotorLevel | None = None  # for psychomotor
    krathwohl_level: KrathwohlLevel | None = None  # for affective
    is_subject_specific: bool
    action_verb_th: str  # the single Bloom verb extracted
    smart_check: SMARTCheck
    source_cluster_ids: list[str]  # SkillCluster IDs that justify this PLO
    source_evidence_ids: list[str]  # rolled up from clusters
    rationale_th: str  # why this PLO exists, for designer review
    version: int = 1
    smart_retry_count: int = 0  # SMART hard-fail fix attempts consumed (max 3)
    smart_escalated: bool = False  # still hard-failing after retries → human repair
    soft_flags: list[str] = []  # non-blocking review flags: "S_object", "A_level", "R_alignment"
    is_optional: bool = False  # supplementary PLO from want-clusters, exempt from 6-10 count
```

Validation rules for PLO (enforce in code):
- `statement_th` must not contain forbidden words (รู้, จำ, เข้าใจ, ซาบซึ้ง, ตระหนัก, ศรัทธา, รัก) — see `obe-principles.md`. Exception: a PLO with `smart_escalated=True` may carry them — it exists precisely so a human can repair it, and the SMART gate already failed it loudly.
- The level field matching `domain` must be set: cognitive → `bloom_level`, psychomotor → `psychomotor_level`, affective → `krathwohl_level`
- `source_cluster_ids` must be non-empty (no PLO without evidence)
- `smart_check` all five fields must be `True` to mark the PLO ready
- Hard vs soft failure handling: S-verb / M-forbidden / R-evidence failures (pure code, `stages/smart_rules.py`) trigger the automated SMART retry loop (max 3, criterion named in the retry prompt; unfixed → `smart_escalated=True`). S-object / A-level / R-alignment concerns come from one light-model judge call and land in `soft_flags` without blocking. Implement per the SMART validation checklist in `obe-principles.md`.

## Cross-stage: human-in-the-loop checkpoint

```python
class StageCheckpoint(BaseModel):
    """Saved at every stage boundary for human review."""
    checkpoint_id: str
    program_id: str
    stage: Literal["intake", "stakeholder_needs", "skill_extraction", "plo_synthesis", "plo_report"]
    artifacts: dict  # serialized output of the stage
    created_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    status: Literal["pending", "approved", "needs_revision", "rejected"] = "pending"
    designer_notes_th: str | None = None
    edits: dict = {}  # any edits the designer made
```

LangGraph's interrupt mechanism saves a `StageCheckpoint` and waits. The React UI fetches pending checkpoints via the FastAPI routes, lets the designer edit, then signals approval. The graph resumes with the (possibly edited) artifacts.

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
