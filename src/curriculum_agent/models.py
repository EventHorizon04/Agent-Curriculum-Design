from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from curriculum_agent.data.isced import get_detailed_field

# ----------------------------- Enums -----------------------------


class StakeholderType(StrEnum):
    EMPLOYER = "employer"
    ALUMNI = "alumni"
    PROFESSIONAL_COUNCIL = "professional_council"
    ACCREDITATION_BODY = "accreditation_body"
    UNIVERSITY = "university"
    COMMUNITY = "community"
    PARENT = "parent"
    SUBJECT_BENCHMARK = "subject_benchmark"
    PEER_PROGRAM = "peer_program"


# Bloom's Taxonomy (cognitive domain) is the only learning-domain scale the
# agent models — Needs and PLOs are cognitive-only (the agent stops at PLO).


class BloomLevel(StrEnum):
    # Cognitive domain levels, in order of increasing complexity
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


# TQF/มคอ. competency domains collapsed to five tags, used to pre-tag every
# ExtractedSkill for eventual มคอ.2/CHECO mapping. The skill domain is split by
# specificity so `is_subject_specific` is absorbed here rather than kept as a
# separate field that could disagree with the tag. This is NOT a Bloom domain —
# it is orthogonal to bloom_level, and a skill may be SS at Bloom `analyze`.
class KSECCategory(StrEnum):
    K = "K"  # ความรู้
    GS = "GS"  # ทักษะทั่วไป (generic/transferable)
    SS = "SS"  # ทักษะเฉพาะสาขา (subject-specific)
    C = "C"  # คุณลักษณะบุคคล
    E = "E"  # คุณธรรมจริยธรรม


# Words forbidden in PLO statements (Thai). Cause SMART measurable to fail.
FORBIDDEN_WORDS_TH = {"รู้", "จำ", "เข้าใจ", "ซาบซึ้ง", "ตระหนัก", "ศรัทธา", "รัก"}

# Bloom levels in order, used for monotonicity check
BLOOM_ORDER = [
    BloomLevel.REMEMBER,
    BloomLevel.UNDERSTAND,
    BloomLevel.APPLY,
    BloomLevel.ANALYZE,
    BloomLevel.EVALUATE,
    BloomLevel.CREATE,
]


# --------------------------- Stage 0 -----------------------------


class ProgramCreateRequest(BaseModel):
    name_th: str
    name_en: str
    field: str
    isced_code: str | None = None
    degree_level: Literal["bachelor", "master", "doctoral"]
    duration_years: int = Field(ge=1, le=8)
    faculty: str
    university: str
    vision_th: str
    mission_th: str = Field(min_length=1)
    philosophy_th: str = Field(min_length=1)
    institutional_identity_th: str | None = None
    student_identity_th: str | None = None
    professional_council: str | None = None
    accreditation_body: str | None = None
    subject_benchmark_ref: str | None = None
    program_objectives_th: list[str]
    program_goals_th: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_isced_code(self) -> ProgramCreateRequest:
        if self.isced_code is not None and get_detailed_field(self.isced_code) is None:
            raise ValueError(f"isced_code '{self.isced_code}' ไม่อยู่ใน ISCED-F 2013 taxonomy")
        return self


class ProgramMetadata(ProgramCreateRequest):
    program_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Entity model deserializes persisted rows verbatim, including legacy rows
    # backfilled by migration a845ef6ab4f6 with ""/[]; input-time non-empty
    # enforcement lives on ProgramCreateRequest only.
    mission_th: str
    philosophy_th: str
    program_goals_th: list[str]

    # Entity model deserializes persisted rows verbatim, including any future
    # legacy code no longer in the taxonomy; input-time membership enforcement
    # lives on ProgramCreateRequest only (same boundary rule as F1's mission_th).
    @model_validator(mode="after")
    def _validate_isced_code(self) -> ProgramMetadata:
        return self


class ProgramSummary(BaseModel):
    """List-page row: program metadata + latest-session state.

    current_stage/session_status are None when the program has no session yet.
    """

    program_id: str
    name_th: str
    name_en: str
    degree_level: str
    created_at: datetime
    current_stage: str | None = None
    session_status: str | None = None


class ExtractedMetadata(BaseModel):
    """LLM-extracted university metadata from an uploaded document.

    Every field is None when the document does not state it — the
    extraction prompt forbids fabrication.
    """

    vision_th: str | None = None
    mission_th: str | None = None
    institutional_identity_th: str | None = None
    student_identity_th: str | None = None


class MetadataExtractionResult(ExtractedMetadata):
    """What the prefill endpoint returns: the extracted values plus a warning list.

    Separate from `ExtractedMetadata` on purpose. That model is the LLM's response
    contract, and adding a field there would mean asking the model to grade its own
    output — the same mistake that had it inventing PLO ids and evidence trails.
    The grade is computed in code, so it lives on the API model only.

    `low_grounding_fields` names the fields whose text has little character overlap
    with the source document. The extraction prompt permits paraphrase, so weak
    overlap is a prompt for the designer to check rather than proof of invention —
    these are surfaced in the intake form, never dropped.
    """

    low_grounding_fields: list[str] = Field(default_factory=list)


class SuggestedName(BaseModel):
    name_th: str
    name_en: str


class IscedSuggestion(BaseModel):
    isced_code: str
    field_name_en: str
    field_name_th: str
    rationale_th: str
    suggested_names: list[SuggestedName] = Field(min_length=1, max_length=3)


# --------------------------- Stage 1 -----------------------------


class StakeholderEvidence(BaseModel):
    evidence_id: str
    program_id: str
    stakeholder_type: StakeholderType
    source_name: str
    source_url: str | None = None
    raw_text_th: str
    raw_text_en: str | None = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    classification: Literal["need", "requirement", "want", "unclassified"] = "unclassified"
    classification_rationale_th: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# --------------------------- Stage 2 -----------------------------


class ExtractedSkill(BaseModel):
    skill_id: str
    program_id: str
    # A phrase / skill word-group ("วิเคราะห์ข้อมูลขนาดใหญ่"), never a bare word.
    skill_name_th: str = Field(min_length=1)
    skill_name_en: str | None = None
    ksec_category: KSECCategory
    # Cognitive scale only. Psychomotor/affective scales are not modelled: the
    # agent stops at PLO and every PLO it produces is cognitive.
    bloom_level: BloomLevel
    # Verbatim quote from the source evidence that justifies this skill.
    # Verified against the evidence text in pure code — see is_grounded().
    evidence_span_th: str = Field(min_length=1)
    source_evidence_id: str
    extraction_method: Literal["llm", "manual"]
    confidence: float = Field(ge=0, le=1)
    # Per-skill-name demand, computed before grouping. Orders the raw-skill table.
    importance_score: float = Field(ge=0, le=1)


class Need(BaseModel):
    """A market-side demand distilled from a group of extracted skills.

    One sentence stating what the labour market asks for. PLO synthesis restates
    it from the graduate's side; keeping both makes "which demand does this PLO
    answer?" answerable from the data rather than inferred.
    """

    need_id: str
    program_id: str
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None
    # Single-valued by construction: grouping runs inside one KSEC bucket.
    ksec_category: KSECCategory
    # Highest Bloom level among member skills.
    bloom_level: BloomLevel
    member_skill_ids: list[str] = Field(min_length=1)
    source_evidence_ids: list[str] = Field(min_length=1)
    stakeholder_coverage: dict[StakeholderType, int] = Field(default_factory=dict)
    # Raw mention count: len(member_skill_ids). Explainable to a designer in a
    # way the weighted score is not.
    freq: int = Field(ge=1)
    demand_score: float = Field(ge=0, le=1)
    is_optional: bool = False
    classification_coverage: dict[str, int] = Field(default_factory=dict)
    sample_quotes_th: list[str] = Field(default_factory=list, max_length=5)


# --------------------------- Stage 3 -----------------------------


class SMARTCheck(BaseModel):
    specific: bool
    measurable: bool
    achievable: bool
    relevant: bool
    timely: bool
    notes_th: str | None = None

    @property
    def passed(self) -> bool:
        return all([self.specific, self.measurable, self.achievable, self.relevant, self.timely])


class PLO(BaseModel):
    plo_id: str
    program_id: str
    statement_th: str
    statement_en: str | None = None
    # Cognitive only. The agent stops at PLO, and psychomotor/affective level
    # scales belong to the faculty's YLO/CLO work, not here.
    bloom_level: BloomLevel
    is_subject_specific: bool
    action_verb_th: str
    smart_check: SMARTCheck
    source_need_ids: list[str]
    source_evidence_ids: list[str] = Field(default_factory=list)
    rationale_th: str
    distinctive_feature_th: str | None = None
    version: int = 1
    classification: Literal["generic", "specific"] | None = None
    classification_method: Literal["ksec", "llm", "manual", "fallback"] | None = None
    classification_rationale_th: str | None = None
    smart_retry_count: int = 0
    smart_escalated: bool = False
    soft_flags: list[str] = Field(default_factory=list)
    is_optional: bool = False

    @model_validator(mode="after")
    def check_no_forbidden_words(self) -> PLO:
        if self.smart_escalated:
            return self  # kept for human review; SMART gate already failed it loudly
        for word in FORBIDDEN_WORDS_TH:
            if word in self.statement_th:
                raise ValueError(
                    f"PLO {self.plo_id} contains forbidden word '{word}' — "
                    f"unmeasurable. Rewrite with an observable Bloom verb."
                )
        return self

    @model_validator(mode="after")
    def check_evidence(self) -> PLO:
        if not self.source_need_ids:
            raise ValueError(
                f"PLO {self.plo_id} has no source Needs — every PLO must trace to evidence."
            )
        if not self.source_evidence_ids:
            raise ValueError(
                f"PLO {self.plo_id} has empty source_evidence_ids — "
                "every PLO must trace to evidence."
            )
        return self


# ----------------------- Stage checkpoint ------------------------


class StageCheckpoint(BaseModel):
    checkpoint_id: str
    program_id: str
    stage: Literal[
        "intake",
        "stakeholder_needs",
        "skill_extraction",
        "need_combination",
        "plo_synthesis",
        "plo_report",
    ]
    artifacts: dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    status: Literal["pending", "approved", "needs_revision", "rejected"] = "pending"
    designer_notes_th: str | None = None
    edits: dict[str, Any] = Field(default_factory=dict)


# ----------------------- Session info ----------------------------


class SessionInfo(BaseModel):
    session_id: str
    program_id: str
    thread_id: str
    status: Literal["running", "suspended", "completed", "rejected", "failed"]
    current_stage: str | None = None
    suspended_message: str | None = None
    created_at: datetime
    updated_at: datetime


# ------------------ Cross-stage designer note --------------------

NOTE_MAX_CHARS = 500


class DesignerNoteRequest(BaseModel):
    """Optional free-text guidance a designer attaches when triggering a stage.

    Influences wording only. `source_need_ids`, `source_evidence_ids` and
    `plo_id` are computed in code and are not reachable from here — see
    `plo_synthesis.synthesize_from_needs` for where each is pinned. Forbidden
    words stay enforced by `smart_rules.hard_failures` and by
    `PLO.check_no_forbidden_words`, so a note asking for one produces a retry and
    then an escalated PLO, never a silent violation.

    Not persisted: the note is an input to one request, so a re-run needs it typed
    again. That matches how these stateless stage endpoints already behave.
    """

    note_th: str | None = Field(default=None, max_length=NOTE_MAX_CHARS)

    @field_validator("note_th", mode="before")
    @classmethod
    def _blank_is_absent(cls, v: object) -> object:
        """Strip before max_length runs, and treat a whitespace-only note as absent.

        `mode="before"` for the same reason as `_SkillItem._strip_text` in
        skill_extraction: it puts the constraint on the stripped text, so trailing
        whitespace cannot tip an exactly-full note over the limit.
        """
        if isinstance(v, str):
            return v.strip() or None
        return v
