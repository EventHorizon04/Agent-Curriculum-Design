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
PLO
  ↓ plo_id
YLO (one per year per PLO)
```

Never break the chain. If a model doesn't have a `source_ids` or equivalent field, you can't trace its provenance.

## Stage 0: Program metadata

```python
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime

class ProgramMetadata(BaseModel):
    """Set in Stage 0 (Intake). The fixed context all later stages reference."""
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

## Stage 1: Stakeholder evidence

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
    """Raw evidence collected in Stage 1. The 'source of truth' for traceability."""
    evidence_id: str  # uuid
    program_id: str
    stakeholder_type: StakeholderType
    source_name: str  # e.g. "JobThai posting #12345" or "TPQI subject benchmark"
    source_url: str | None = None
    raw_text_th: str  # original Thai text
    raw_text_en: str | None = None  # English original if available
    collected_at: datetime
    # need vs want classification, set by Stage 1 LLM
    classification: Literal["need", "requirement", "want", "unclassified"] = "unclassified"
    metadata: dict = {}  # job title, salary, location, etc. for job postings
```

Why `classification`: the project knowledge emphasizes distinguishing needs (must-have) from wants (nice-to-have). Stage 1 ends with a classification step before passing to Stage 2.

## Stage 2: Extracted skills and clusters

```python
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

class SkillCluster(BaseModel):
    """Output of Stage 2 — grouped skills representing a coherent capability."""
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
    demand_score: float = Field(ge=0, le=1)  # weighted frequency × recency × stakeholder breadth
    is_common_need: bool = False  # appears in multiple stakeholder groups → likely PLO
    sample_quotes_th: list[str] = []  # 2-3 illustrative excerpts
```

`demand_score` is the data-science output that the agent uses to decide which clusters are PLO-worthy. Tune the weighting in Stage 2 config.

## Stage 3: PLO

```python
class BloomLevel(str, Enum):
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"

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
    krathwohl_level: KrathwohlLevel | None = None  # for affective
    is_subject_specific: bool
    action_verb_th: str  # the single Bloom verb extracted
    smart_check: SMARTCheck
    source_cluster_ids: list[str]  # SkillCluster IDs that justify this PLO
    source_evidence_ids: list[str]  # rolled up from clusters
    rationale_th: str  # why this PLO exists, for designer review
    version: int = 1
```

Validation rules for PLO (enforce in code):
- `statement_th` must not contain forbidden words (รู้, จำ, เข้าใจ, ซาบซึ้ง, ตระหนัก, ศรัทธา, รัก) — see `obe-principles.md`
- Exactly one of `bloom_level` / `krathwohl_level` must be set, depending on domain
- `source_cluster_ids` must be non-empty (no PLO without evidence)
- `smart_check` all five fields must be `True` to mark the PLO ready

## Stage 4: YLO

```python
class YLO(BaseModel):
    """A Year Learning Outcome — what a learner can do at end of year N."""
    ylo_id: str  # e.g. "YLO1.2" = PLO1, Year 2
    program_id: str
    parent_plo_id: str
    year: int = Field(ge=1, le=8)
    statement_th: str
    statement_en: str | None = None
    bloom_level: BloomLevel | None = None
    krathwohl_level: KrathwohlLevel | None = None
    action_verb_th: str
    smart_check: SMARTCheck
    rationale_th: str  # why this is the right level for this year
    version: int = 1

class YLOMatrix(BaseModel):
    """The full PLO × Year matrix that Stage 4 produces."""
    program_id: str
    plos: list[PLO]
    ylos: list[YLO]
    coverage_check: dict[str, list[int]]  # plo_id -> [years it appears in]

    def validate_coverage(self) -> list[str]:
        """Return list of issues. Empty list means valid."""
        issues = []
        for plo in self.plos:
            covered_years = self.coverage_check.get(plo.plo_id, [])
            if len(covered_years) < 1:
                issues.append(f"{plo.plo_id} has no YLO in any year")
            # Check Bloom monotonicity within a PLO across years
            ylos_for_plo = sorted(
                [y for y in self.ylos if y.parent_plo_id == plo.plo_id],
                key=lambda y: y.year
            )
            levels = [y.bloom_level for y in ylos_for_plo if y.bloom_level]
            level_order = list(BloomLevel)
            for i in range(1, len(levels)):
                if level_order.index(levels[i]) < level_order.index(levels[i-1]):
                    issues.append(
                        f"{plo.plo_id} Bloom decreases between year "
                        f"{ylos_for_plo[i-1].year} and {ylos_for_plo[i].year}"
                    )
        return issues
```

## Cross-stage: human-in-the-loop checkpoint

```python
class StageCheckpoint(BaseModel):
    """Saved at every stage boundary for human review."""
    checkpoint_id: str
    program_id: str
    stage: Literal["intake", "stakeholder_needs", "skill_extraction", "plo_synthesis", "ylo_derivation"]
    artifacts: dict  # serialized output of the stage
    created_at: datetime
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    status: Literal["pending", "approved", "needs_revision", "rejected"] = "pending"
    designer_notes_th: str | None = None
    edits: dict = {}  # any edits the designer made
```

LangGraph's interrupt mechanism saves a `StageCheckpoint` and waits. The Streamlit UI fetches pending checkpoints, lets the designer edit, then signals approval. The graph resumes with the (possibly edited) artifacts.

## Versioning

PLOs and YLOs are mutable objects under designer review. Use this versioning approach:

- `version: int` on PLO and YLO, starts at 1
- On every edit, increment version and write a new row (don't update in place)
- Keep a `current_version_id` on the program for the active set
- This preserves audit trail for accreditation

## Database mapping

These Pydantic models map to Postgres tables 1:1 with these adjustments:
- `list[str]` fields → JSON column or junction table depending on access pattern
- `dict` metadata → JSONB column
- `datetime` → `timestamptz`
- Enums → Postgres enum types or text with check constraint

Use SQLAlchemy 2.0 with Pydantic for the ORM layer, or SQLModel which combines both. Either is fine.

## Export formats

For CHECO and มคอ.2 export, derive the document from these models. Don't store CHECO-specific fields on the core models — keep the core clean and transform at export time.

Mapping summary:
- `PLO.statement_th` → CHECO 1.6.2 (ผลลัพธ์การเรียนรู้ของหลักสูตร)
- `YLO.statement_th` grouped by year → CHECO 1.6.3 (ความคาดหวังของผลลัพธ์การเรียนรู้เมื่อสิ้นปีการศึกษา)
- `ProgramMetadata.program_objectives_th` → CHECO 1.5
