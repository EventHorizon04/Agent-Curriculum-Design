from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from curriculum_agent.data.isced import get_detailed_field

# ----------------------------- Enums -----------------------------


class StakeholderGroup(StrEnum):
    """Whether a stakeholder speaks from outside the institution or inside it.

    External input describes the labour market the graduate enters; internal
    input describes what the institution intends to be. Both matter, and the
    demand weighting treats them differently — external requirement input
    outranks internal, and both outrank ordinary opinion.
    """

    EXTERNAL = "external"
    INTERNAL = "internal"


class StakeholderType(StrEnum):
    # --- external ---
    PROFESSIONAL_COUNCIL = "professional_council"  # สภาวิชาชีพ
    EMPLOYER = "employer"  # ผู้ใช้บัณฑิต / ผู้ประกอบการ
    INDUSTRY = "industry"  # ภาคอุตสาหกรรม
    ALUMNI = "alumni"  # ศิษย์เก่า
    EXPERT = "expert"  # ผู้ทรงคุณวุฒิ
    COMMUNITY = "community"  # ชุมชนและสังคม
    PARTNER_INSTITUTION = "partner_institution"  # สถาบันคู่ความร่วมมือ
    APPLICANT = "applicant"  # ผู้สมัครเรียน
    PARENT = "parent"  # ผู้ปกครอง
    # --- internal ---
    # One voice (the institution's) expressed across several documents; which
    # document a row came from lives in StakeholderEvidence.source_name.
    INSTITUTIONAL_DIRECTION = "institutional_direction"  # vision/mission/identity
    ADMINISTRATOR = "administrator"  # ผู้บริหาร
    PROGRAM_COMMITTEE = "program_committee"  # คณะกรรมการหลักสูตร
    FACULTY = "faculty"  # อาจารย์
    STUDENT = "student"  # ผู้เรียน
    SUPPORT_STAFF = "support_staff"  # บุคลากรสายสนับสนุน


_EXTERNAL_TYPES = frozenset(
    {
        StakeholderType.PROFESSIONAL_COUNCIL,
        StakeholderType.EMPLOYER,
        StakeholderType.INDUSTRY,
        StakeholderType.ALUMNI,
        StakeholderType.EXPERT,
        StakeholderType.COMMUNITY,
        StakeholderType.PARTNER_INSTITUTION,
        StakeholderType.APPLICANT,
        StakeholderType.PARENT,
    }
)

# The only mapping from type to group. Nothing else may hardcode the split —
# the demand weight table and the UI grouping both read from here.
STAKEHOLDER_GROUP: dict[StakeholderType, StakeholderGroup] = {
    t: (StakeholderGroup.EXTERNAL if t in _EXTERNAL_TYPES else StakeholderGroup.INTERNAL)
    for t in StakeholderType
}

# สภาวิชาชีพ sets legally binding practice requirements; the institution's own
# vision/mission/identity is a mandate it has committed to. Both are
# ข้อกำหนดที่ต้องมี. Every other type carries demand signal, not mandate.
REQUIREMENT_TYPES = frozenset(
    {StakeholderType.PROFESSIONAL_COUNCIL, StakeholderType.INSTITUTIONAL_DIRECTION}
)

# Evidence carries a mandate or it does not — a two-value vocabulary, decided in
# code from the stakeholder type. need/want/unclassified moved to the skill,
# where the cross-evidence frequency that decides them is actually visible.
EvidenceClassification = Literal["requirement", "general"]
SkillClassification = Literal["requirement", "need", "want", "unclassified"]


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


# TQF/มคอ. competency domains, used to pre-tag every ExtractedSkill for eventual
# มคอ.2/CHECO mapping. NOT a Bloom domain — orthogonal to bloom_level.
#
# A skill carries K, S, E or C. A Need carries those plus EC, the umbrella tag
# for a group whose members mix ethics and character; grouping produces it, and
# E or C survive as standalone Need tags when a group is unambiguously one.
class KSECCategory(StrEnum):
    K = "K"  # ความรู้
    S = "S"  # ทักษะ
    EC = "EC"  # คุณธรรมจริยธรรมและคุณลักษณะบุคคล — displayed "E|C"
    E = "E"  # คุณธรรมจริยธรรม
    C = "C"  # คุณลักษณะบุคคล


# The tags an ExtractedSkill may carry. EC is Need-level only.
#
# This constant documents the invariant; the actual enforcement is
# `_SkillItem.ksec_category: Literal["K", "S", "E", "C"]` in
# `stages/skill_extraction.py`, which Instructor uses to constrain what the
# extraction LLM can return. That module asserts its Literal against this
# frozenset at import time (mirroring the `_KSEC_LABEL_TH` guard in
# `prompts/summarize_need.py`), so the two cannot silently drift apart.
SKILL_KSEC = frozenset({KSECCategory.K, KSECCategory.S, KSECCategory.E, KSECCategory.C})


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
    # Intake identifies a program by where it sits — university, faculty, field.
    # The names stay for programs created before that change, and for any client
    # that still supplies one; nothing requires them.
    name_th: str = ""
    name_en: str = ""
    field: str
    isced_code: str | None = None
    degree_level: Literal["bachelor", "master", "doctoral"]
    duration_years: int = Field(ge=1, le=8)
    faculty: str
    university: str
    professional_council: str | None = None
    accreditation_body: str | None = None
    subject_benchmark_ref: str | None = None
    # Intake no longer collects either — the form covers the program's place in
    # the institution and nothing else. They stay on the model so persisted rows
    # keep their content and CHECO 1.5 has a field to read, and so a client that
    # does supply them is still accepted.
    program_objectives_th: list[str] = []
    program_goals_th: list[str] = []

    @model_validator(mode="after")
    def _validate_isced_code(self) -> ProgramCreateRequest:
        if self.isced_code is not None and get_detailed_field(self.isced_code) is None:
            raise ValueError(f"isced_code '{self.isced_code}' ไม่อยู่ใน ISCED-F 2013 taxonomy")
        return self


class ProgramMetadata(ProgramCreateRequest):
    program_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Entity model deserializes persisted rows verbatim, including any future
    # legacy code no longer in the taxonomy; input-time membership enforcement
    # lives on ProgramCreateRequest only.
    @model_validator(mode="after")
    def _validate_isced_code(self) -> ProgramMetadata:
        return self


class ProgramSummary(BaseModel):
    """List-page row: program metadata + latest-session state.

    current_stage/session_status are None when the program has no session yet.
    """

    program_id: str
    name_th: str = ""
    name_en: str = ""
    field: str = ""
    faculty: str = ""
    degree_level: str
    created_at: datetime
    current_stage: str | None = None
    session_status: str | None = None


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
    classification: EvidenceClassification = "general"
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
    # Provenance kept for the UI: a designer reviewing a grouped Need can see
    # which stakeholders it came from without another query.
    source_stakeholder_type: StakeholderType
    # Decided in code after every evidence item is extracted — see
    # skill_extraction.classify_skills.
    classification: SkillClassification = "unclassified"
    # Set by the extraction model: does this belong to the program's field at
    # all? A False here yields `unclassified` unless the skill is mandated.
    is_field_relevant: bool = True
    extraction_method: Literal["llm", "manual"]
    confidence: float = Field(ge=0, le=1)
    # Per-skill-name demand, computed before grouping. Orders the raw-skill table.
    importance_score: float = Field(ge=0, le=1)


class Need(BaseModel):
    """A market-side demand distilled from a group of extracted skills.

    One sentence stating what the labour market asks for, written from the member
    skills alone — no evidence text reaches the sentence, and none is stored on
    the Need. `source_evidence_ids` still carries the trail, inherited from those
    skills. PLO synthesis restates the sentence from the graduate's side and is
    given nothing else, so the sentence has to be specific enough to draft one
    PLO from; need_combination._NeedStatement is what enforces that.
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
    # Distinct source stakeholder types, external first (enum declaration order).
    source_stakeholder_types: list[StakeholderType] = Field(default_factory=list)
    # Raw mention count: len(member_skill_ids). Explainable to a designer in a
    # way the weighted score is not.
    freq: int = Field(ge=1)
    demand_score: float = Field(ge=0, le=1)
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
    # Cognitive only. The agent stops at PLO, and psychomotor/affective level
    # scales belong to the faculty's YLO/CLO work, not here.
    bloom_level: BloomLevel
    action_verb_th: str
    smart_check: SMARTCheck
    source_need_ids: list[str]
    source_evidence_ids: list[str] = Field(default_factory=list)
    rationale_th: str
    distinctive_feature_th: str | None = None
    version: int = 1
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
