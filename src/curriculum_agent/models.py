from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# ----------------------------- Enums -----------------------------


class StakeholderType(StrEnum):
    EMPLOYER = "employer"
    ALUMNI = "alumni"
    PROFESSIONAL_COUNCIL = "professional_council"
    ACCREDITATION_BODY = "accreditation_body"
    UNIVERSITY = "university"
    COMMUNITY = "community"
    SUBJECT_BENCHMARK = "subject_benchmark"
    PEER_PROGRAM = "peer_program"


# Bloom's Taxonomy spans three learning domains, each with its own level scale:
#   Cognitive (Knowledge/Thinking)  -> BloomLevel
#   Psychomotor (Skill/Doing)       -> PsychomotorLevel (Dave's taxonomy)
#   Affective (Attitude/Feeling)    -> KrathwohlLevel


class BloomLevel(StrEnum):
    # Cognitive domain levels, in order of increasing complexity
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


class PsychomotorLevel(StrEnum):
    # Psychomotor domain levels (Dave), in order of increasing mastery
    IMITATE = "imitate"
    MANIPULATE = "manipulate"
    PRECISE = "precise"
    ARTICULATE = "articulate"
    NATURALIZE = "naturalize"


class KrathwohlLevel(StrEnum):
    # Affective domain levels (Krathwohl), in order of increasing internalization
    RECEIVING = "receiving"
    RESPONDING = "responding"
    VALUING = "valuing"
    ORGANIZATION = "organization"
    CHARACTERIZATION = "characterization"


class SkillType(StrEnum):
    KNOWLEDGE = "knowledge"
    PSYCHOMOTOR = "psychomotor"
    AFFECTIVE = "affective"
    MIXED = "mixed"


class Domain(StrEnum):
    COGNITIVE = "cognitive"
    PSYCHOMOTOR = "psychomotor"
    AFFECTIVE = "affective"


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
PSYCHOMOTOR_ORDER = [
    PsychomotorLevel.IMITATE,
    PsychomotorLevel.MANIPULATE,
    PsychomotorLevel.PRECISE,
    PsychomotorLevel.ARTICULATE,
    PsychomotorLevel.NATURALIZE,
]
KRATHWOHL_ORDER = [
    KrathwohlLevel.RECEIVING,
    KrathwohlLevel.RESPONDING,
    KrathwohlLevel.VALUING,
    KrathwohlLevel.ORGANIZATION,
    KrathwohlLevel.CHARACTERIZATION,
]


# --------------------------- Stage 0 -----------------------------


class ProgramMetadata(BaseModel):
    program_id: str
    name_th: str
    name_en: str
    field: str
    degree_level: Literal["bachelor", "master", "doctoral"]
    duration_years: int = Field(ge=1, le=8)
    faculty: str
    university: str
    vision_th: str
    student_identity_th: str | None = None
    professional_council: str | None = None
    accreditation_body: str | None = None
    subject_benchmark_ref: str | None = None
    program_objectives_th: list[str]
    created_at: datetime = Field(default_factory=datetime.utcnow)


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
    metadata: dict = Field(default_factory=dict)


# --------------------------- Stage 2 -----------------------------


class ExtractedSkill(BaseModel):
    skill_id: str
    program_id: str
    skill_name_th: str
    skill_name_en: str | None = None
    skill_type: SkillType
    is_subject_specific: bool
    source_evidence_id: str
    extraction_method: Literal["keybert", "llm", "manual", "ner"]
    confidence: float = Field(ge=0, le=1)


class SkillCluster(BaseModel):
    cluster_id: str
    program_id: str
    canonical_name_th: str
    canonical_name_en: str | None = None
    description_th: str
    skill_type: SkillType
    is_subject_specific: bool
    member_skill_ids: list[str]
    source_evidence_ids: list[str]
    stakeholder_coverage: dict[StakeholderType, int] = Field(default_factory=dict)
    demand_score: float = Field(ge=0, le=1)
    is_common_need: bool = False
    sample_quotes_th: list[str] = Field(default_factory=list, max_length=5)
    bloom_level: BloomLevel | None = None
    psychomotor_level: PsychomotorLevel | None = None
    krathwohl_level: KrathwohlLevel | None = None
    is_optional: bool = False
    classification_coverage: dict[str, int] = Field(default_factory=dict)


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
    domain: Domain
    bloom_level: BloomLevel | None = None
    psychomotor_level: PsychomotorLevel | None = None
    krathwohl_level: KrathwohlLevel | None = None
    is_subject_specific: bool
    action_verb_th: str
    smart_check: SMARTCheck
    source_cluster_ids: list[str]
    source_evidence_ids: list[str] = Field(default_factory=list)
    rationale_th: str
    distinctive_feature_th: str | None = None
    version: int = 1
    classification: Literal["generic", "specific"] | None = None
    classification_method: Literal["skill_type", "llm", "manual"] | None = None
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
        if not self.source_cluster_ids:
            raise ValueError(
                f"PLO {self.plo_id} has no source clusters — every PLO must trace to evidence."
            )
        if not self.source_evidence_ids:
            raise ValueError(
                f"PLO {self.plo_id} has empty source_evidence_ids — "
                "every PLO must trace to evidence."
            )
        return self

    @model_validator(mode="after")
    def check_domain_level_match(self) -> PLO:
        if self.domain == Domain.AFFECTIVE:
            if self.krathwohl_level is None:
                raise ValueError(f"PLO {self.plo_id} is affective but missing krathwohl_level")
        elif self.domain == Domain.PSYCHOMOTOR:
            if self.psychomotor_level is None:
                raise ValueError(f"PLO {self.plo_id} is psychomotor but missing psychomotor_level")
        else:
            if self.bloom_level is None:
                raise ValueError(f"PLO {self.plo_id} is cognitive but missing bloom_level")
        return self


# ----------------------- Stage checkpoint ------------------------


class StageCheckpoint(BaseModel):
    checkpoint_id: str
    program_id: str
    stage: Literal["intake", "stakeholder_needs", "skill_extraction", "plo_synthesis", "plo_report"]
    artifacts: dict
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    status: Literal["pending", "approved", "needs_revision", "rejected"] = "pending"
    designer_notes_th: str | None = None
    edits: dict = Field(default_factory=dict)


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
