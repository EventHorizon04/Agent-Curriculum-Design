"""
Curriculum Design Agent — core Pydantic data models.

These match the schemas described in references/data-schemas.md.
Drop this into src/curriculum_agent/models.py to start.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ----------------------------- Enums -----------------------------

class StakeholderType(str, Enum):
    EMPLOYER = "employer"
    ALUMNI = "alumni"
    PROFESSIONAL_COUNCIL = "professional_council"
    ACCREDITATION_BODY = "accreditation_body"
    UNIVERSITY = "university"
    COMMUNITY = "community"
    SUBJECT_BENCHMARK = "subject_benchmark"
    PEER_PROGRAM = "peer_program"


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


class SkillType(str, Enum):
    KNOWLEDGE = "knowledge"
    PSYCHOMOTOR = "psychomotor"
    AFFECTIVE = "affective"
    MIXED = "mixed"


class Domain(str, Enum):
    COGNITIVE = "cognitive"
    PSYCHOMOTOR = "psychomotor"
    AFFECTIVE = "affective"


# Words forbidden in PLO/YLO statements (Thai). Cause SMART measurable to fail.
FORBIDDEN_WORDS_TH = {"รู้", "จำ", "เข้าใจ", "ซาบซึ้ง", "ตระหนัก", "ศรัทธา", "รัก"}


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
        return all([
            self.specific, self.measurable, self.achievable,
            self.relevant, self.timely
        ])


class PLO(BaseModel):
    plo_id: str
    program_id: str
    statement_th: str
    statement_en: str | None = None
    domain: Domain
    bloom_level: BloomLevel | None = None
    krathwohl_level: KrathwohlLevel | None = None
    is_subject_specific: bool
    action_verb_th: str
    smart_check: SMARTCheck
    source_cluster_ids: list[str]
    source_evidence_ids: list[str] = Field(default_factory=list)
    rationale_th: str
    distinctive_feature_th: str | None = None
    version: int = 1

    @model_validator(mode="after")
    def check_no_forbidden_words(self):
        for word in FORBIDDEN_WORDS_TH:
            if word in self.statement_th:
                raise ValueError(
                    f"PLO {self.plo_id} contains forbidden word '{word}' — "
                    f"unmeasurable. Rewrite with an observable Bloom verb."
                )
        return self

    @model_validator(mode="after")
    def check_evidence(self):
        if not self.source_cluster_ids:
            raise ValueError(
                f"PLO {self.plo_id} has no source clusters — "
                f"every PLO must trace to evidence."
            )
        return self

    @model_validator(mode="after")
    def check_domain_level_match(self):
        if self.domain == Domain.AFFECTIVE:
            if self.krathwohl_level is None:
                raise ValueError(
                    f"PLO {self.plo_id} is affective but missing krathwohl_level"
                )
        else:
            if self.bloom_level is None:
                raise ValueError(
                    f"PLO {self.plo_id} is {self.domain} but missing bloom_level"
                )
        return self


# --------------------------- Stage 4 -----------------------------

# Bloom levels in order, used for monotonicity check
BLOOM_ORDER = [
    BloomLevel.REMEMBER, BloomLevel.UNDERSTAND, BloomLevel.APPLY,
    BloomLevel.ANALYZE, BloomLevel.EVALUATE, BloomLevel.CREATE,
]
KRATHWOHL_ORDER = [
    KrathwohlLevel.RECEIVING, KrathwohlLevel.RESPONDING, KrathwohlLevel.VALUING,
    KrathwohlLevel.ORGANIZATION, KrathwohlLevel.CHARACTERIZATION,
]


class YLO(BaseModel):
    ylo_id: str
    program_id: str
    parent_plo_id: str
    year: int = Field(ge=1, le=8)
    statement_th: str
    statement_en: str | None = None
    bloom_level: BloomLevel | None = None
    krathwohl_level: KrathwohlLevel | None = None
    action_verb_th: str
    smart_check: SMARTCheck
    rationale_th: str
    version: int = 1

    @model_validator(mode="after")
    def check_no_forbidden_words(self):
        for word in FORBIDDEN_WORDS_TH:
            if word in self.statement_th:
                raise ValueError(
                    f"YLO {self.ylo_id} contains forbidden word '{word}'"
                )
        return self


class YLOMatrix(BaseModel):
    program_id: str
    plos: list[PLO]
    ylos: list[YLO]

    def validate_coverage(self) -> list[str]:
        """Return list of issues. Empty list = matrix is valid."""
        issues: list[str] = []
        plo_ids = {p.plo_id for p in self.plos}

        # Every YLO must reference an existing PLO
        for ylo in self.ylos:
            if ylo.parent_plo_id not in plo_ids:
                issues.append(f"{ylo.ylo_id} references unknown PLO {ylo.parent_plo_id}")

        # Every PLO must have at least one YLO per year
        for plo in self.plos:
            ylos_for_plo = [y for y in self.ylos if y.parent_plo_id == plo.plo_id]
            covered_years = {y.year for y in ylos_for_plo}
            if not covered_years:
                issues.append(f"{plo.plo_id} has no YLO in any year")
                continue

            # Bloom monotonicity check (cognitive only)
            if plo.domain == Domain.COGNITIVE:
                sorted_ylos = sorted(ylos_for_plo, key=lambda y: y.year)
                levels = [y.bloom_level for y in sorted_ylos if y.bloom_level]
                for i in range(1, len(levels)):
                    prev_idx = BLOOM_ORDER.index(levels[i - 1])
                    curr_idx = BLOOM_ORDER.index(levels[i])
                    if curr_idx < prev_idx:
                        issues.append(
                            f"{plo.plo_id} Bloom decreases between year "
                            f"{sorted_ylos[i-1].year} ({levels[i-1].value}) and "
                            f"year {sorted_ylos[i].year} ({levels[i].value})"
                        )

            # Affective: Krathwohl monotonicity
            elif plo.domain == Domain.AFFECTIVE:
                sorted_ylos = sorted(ylos_for_plo, key=lambda y: y.year)
                levels = [y.krathwohl_level for y in sorted_ylos if y.krathwohl_level]
                for i in range(1, len(levels)):
                    prev_idx = KRATHWOHL_ORDER.index(levels[i - 1])
                    curr_idx = KRATHWOHL_ORDER.index(levels[i])
                    if curr_idx < prev_idx:
                        issues.append(
                            f"{plo.plo_id} Krathwohl decreases between year "
                            f"{sorted_ylos[i-1].year} and year {sorted_ylos[i].year}"
                        )

        return issues


# ----------------------- Stage checkpoint ------------------------

class StageCheckpoint(BaseModel):
    checkpoint_id: str
    program_id: str
    stage: Literal[
        "intake", "stakeholder_needs", "skill_extraction",
        "plo_synthesis", "ylo_derivation"
    ]
    artifacts: dict
    created_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    status: Literal["pending", "approved", "needs_revision", "rejected"] = "pending"
    designer_notes_th: str | None = None
    edits: dict = Field(default_factory=dict)
