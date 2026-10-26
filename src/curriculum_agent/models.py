from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from curriculum_agent.data.isced import get_detailed_field

# Re-exported: the forbidden-word rule lives in `smart_vocabulary` so that this
# module and `stages/smart_rules.py` can share one scan without an import cycle.
# Callers that expect it here keep working.
from curriculum_agent.smart_vocabulary import (
    FORBIDDEN_WORDS_TH as FORBIDDEN_WORDS_TH,
)
from curriculum_agent.smart_vocabulary import (
    HARD_CODES,
    SmartFindingCode,
    forbidden_words_in,
)

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
# frozenset at import time (mirroring the `KSEC_LABEL_TH` guard in
# `prompts/summarize_need.py`), so the two cannot silently drift apart.
SKILL_KSEC = frozenset({KSECCategory.K, KSECCategory.S, KSECCategory.E, KSECCategory.C})


# Canonical order of a Need's tags.
_KSEC_TAG_ORDER = (
    KSECCategory.K,
    KSECCategory.S,
    KSECCategory.E,
    KSECCategory.C,
    KSECCategory.EC,
)


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
    # What the program covers, in the designer's own words: positive side only,
    # itemised ("หลักสูตรนี้ครอบคลุม A, B, C และ D"). Reaches the extraction model in
    # the *system* prompt as the yardstick for is_field_relevant and nothing else —
    # see prompts/extract_skills.py. Empty is fine and is the common case: a program
    # that writes nothing gets the pre-existing prompt byte for byte, and the scope
    # guard turns into a no-op on its own because every flag defaults to True.
    scope_th: str = ""
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
    # Which program this one was copied from (POST /programs/{id}/copy). On the
    # entity, not on ProgramCreateRequest, so a client cannot set it.
    copied_from: str | None = None

    # Entity model deserializes persisted rows verbatim, including any future
    # legacy code no longer in the taxonomy; input-time membership enforcement
    # lives on ProgramCreateRequest only.
    @model_validator(mode="after")
    def _validate_isced_code(self) -> ProgramMetadata:
        return self


class ProgramSummary(BaseModel):
    """List-page row: program metadata, how far it has got, and any live run.

    The two state fields answer different questions and are sourced differently.
    `current_stage` is derived from the rows the program owns, so it is always
    known — a program that exists has at least completed intake. `session_status`
    is None until a graph session has run, because "no run has ever started" is a
    real answer rather than a missing one.
    """

    program_id: str
    name_th: str = ""
    name_en: str = ""
    field: str = ""
    faculty: str = ""
    degree_level: str
    created_at: datetime
    current_stage: str
    session_status: str | None = None
    copied_from: str | None = None


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
    # Set by the extraction model: is this something a graduate can do, or is it
    # an activity of the institution / the programme / its teachers ("บริหารจัดการ
    # โครงสร้างหลักสูตร")? Deliberately a second flag rather than more values on the
    # first: the two axes do not overlap — "การสร้างเครือข่ายความร่วมมือระดับสากล" is
    # squarely in an international college's field and still not a graduate
    # capability — and separate bools are the only shape measured to work.
    # Collapsing the two later is possible; splitting them later is not.
    # Unlike is_field_relevant, this one never touches `classification`: see
    # classify_skills for why a rule here would be dead on the cases it should catch.
    is_graduate_capability: bool = True
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
    # Why this skill group is one demand, written by the same call that wrote the
    # sentence. An explanation, not a trail: source_evidence_ids below is what
    # immutable rule 2 is about and is assembled in code, while this is free text
    # nothing validates against the evidence. Read it as the model's account of
    # its own grouping and label it that way wherever it is shown.
    #
    # Defaults to empty rather than being required, for the same reason the
    # counters below default: a Need also arrives as a plain dict from a
    # LangGraph checkpoint suspended across the deploy that added the column, and
    # those never pass through the migration.
    rationale_th: str = ""
    # Clustering stays inside one KSEC bucket, so a skill-grouped Need carries one
    # tag; a Need merged from same-purpose Needs of different tags carries the
    # union. At least one, no duplicates, in K, S, E, C, EC order.
    ksec_categories: list[KSECCategory] = Field(min_length=1)
    # What most of the group asks for — the lower mention-weighted median of the
    # members' levels (need_grouping.group_bloom), not the highest one.
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
    # How many member *rows* carry each flag — not how many distinct skill names,
    # which is a different number whenever one name was extracted from several
    # evidence items (see need_combination for why the raw per-row count is the
    # useful one). The denominator is len(member_skill_ids), already on the Need,
    # which is why these are plain ints rather than a coverage dict.
    in_field_skill_count: int = 0
    graduate_capability_skill_count: int = 0
    # The most-demanded member skills, kept for display on a merged Need.
    top_skill_ids: list[str] = Field(default_factory=list)
    # A merged Need lists its originals (demand order); an original points back.
    # Originals are stored, never deleted: `merged_into` hides them from every
    # active read and a split clears it.
    merged_from: list[str] = Field(default_factory=list)
    merged_into: str | None = None
    merge_reason_th: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_single_ksec(cls, data: Any) -> Any:
        """Map the old single `ksec_category` key to `ksec_categories=[value]`.

        Rows and LangGraph checkpoints written before the column became a list
        still carry the old key. Copy first, for the same reason as below.
        """
        if not isinstance(data, dict):
            return data
        if "ksec_categories" not in data and "ksec_category" in data:
            data = {**data}
            data["ksec_categories"] = [data.pop("ksec_category")]
        return data

    @field_validator("ksec_categories")
    @classmethod
    def _dedupe_and_order_tags(cls, tags: list[KSECCategory]) -> list[KSECCategory]:
        return [t for t in _KSEC_TAG_ORDER if t in set(tags)]

    @property
    def is_merged(self) -> bool:
        return bool(self.merged_from)

    @model_validator(mode="before")
    @classmethod
    def _default_counts_to_all_members(cls, data: Any) -> Any:
        """A Need that never carried these counts reads as though every member
        passed both axes — the same thing the migration writes into pre-existing
        rows, for the same reason.

        Absent is not zero here. Zero means "the extractor judged every member
        out of scope" and disqualifies the Need; absent means nobody ever asked,
        which has to leave behaviour exactly as it was. Rows written before the
        columns existed are backfilled by the migration, but a Need also arrives
        as a plain dict — from a LangGraph checkpoint suspended across the deploy,
        or from a client — and those never touch the migration.
        """
        if not isinstance(data, dict):
            return data
        # Copy first: plo_synthesis validates every entry of state["needs"] in
        # place, so writing into the argument would quietly add two keys to the
        # LangGraph checkpoint payload the caller owns.
        data = {**data}
        members = data.get("member_skill_ids") or []
        for key in ("in_field_skill_count", "graduate_capability_skill_count"):
            if data.get(key) is None:
                data[key] = len(members)
        return data

    @property
    def in_field_ratio(self) -> float:
        """Share of member rows the extractor judged inside the program's field.

        A share rather than a flag: where the cut falls is policy, and policy for
        which Needs become PLOs lives in need_grouping with the other two bounds.
        This model reports what was measured and stops there.
        """
        return self._ratio(self.in_field_skill_count)

    @property
    def graduate_capability_ratio(self) -> float:
        """Share of member rows that describe something a graduate does."""
        return self._ratio(self.graduate_capability_skill_count)

    def _ratio(self, count: int) -> float:
        # A Need always has at least one member (min_length=1), so the guard is
        # for dicts that arrived without the list rather than for real rows.
        total = len(self.member_skill_ids)
        return count / total if total else 1.0


# --------------------------- Stage 3 -----------------------------


class SkillGroup(BaseModel):
    """A cluster of extracted skills that agent 1 hands to agent 2.

    Stored between the two agents so Need writing can start from the groups in
    a separate job. Fields mirror the candidate group `need_combination` builds
    before a Need's sentence is written; `is_graduate` records whether the
    group is a graduate capability rather than a purely in-field one.
    """

    group_id: str
    program_id: str
    ksec: KSECCategory
    skill_ids: list[str]
    evidence_ids: list[str]
    # Most-mentioned first; skill_frequencies[i] is how many member rows
    # collapsed into skill_names[i].
    skill_names: list[str]
    skill_frequencies: list[int]
    bloom_level: BloomLevel
    demand_score: float
    is_optional: bool
    is_graduate: bool
    classification_coverage: dict[str, int]
    stakeholder_coverage: dict[StakeholderType, int]
    stakeholder_types: list[StakeholderType]
    in_field_skill_count: int
    graduate_capability_skill_count: int


class SmartFinding(BaseModel):
    """One thing the validator found wrong with a PLO, and why.

    This is the information the old gate threw away. The surviving hard
    failures were a local list inside `_ensure_smart` that got logged and
    dropped, so a designer could see that a PLO escalated and never which
    criterion did it — the badge said "failed SMART after 3 retries" and that
    was the whole story.
    """

    criterion: SmartFindingCode
    severity: Literal["hard", "soft"]
    note_th: str

    @model_validator(mode="after")
    def check_severity_matches_the_criterion(self) -> SmartFinding:
        """A hard code carried as soft would read as non-blocking in the UI
        while pure code was escalating the PLO for exactly that reason."""
        expected = "hard" if self.criterion in HARD_CODES else "soft"
        if self.severity != expected:
            raise ValueError(
                f"SMART finding {self.criterion} is a {expected} criterion, not {self.severity}"
            )
        return self


class SMARTCheck(BaseModel):
    specific: bool
    measurable: bool
    achievable: bool
    relevant: bool
    timely: bool
    notes_th: str | None = None
    # Rides inside the existing smart_check JSONB column, so the richest new
    # field needs no migration and every stored row deserialises on the default.
    # Do not make this required, and do not give SMARTCheck extra="forbid":
    # either would make a pre-migration row unreadable, which loses a whole
    # program's PLO list on GET rather than one field.
    findings: list[SmartFinding] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all([self.specific, self.measurable, self.achievable, self.relevant, self.timely])

    @property
    def hard_findings(self) -> list[SmartFinding]:
        return [f for f in self.findings if f.severity == "hard"]


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
    # Repair drafts spent on this outcome. Not renamed when the validator became
    # an agent: it already means "repair attempts", and it is rendered inside a
    # Thai sentence on two pages and documented in data-schemas.md.
    smart_retry_count: int = 0
    smart_escalated: bool = False
    # Derived from smart_check.findings, and kept as a stored field rather than
    # a computed property: the exporter, both frontend pages and plo_report read
    # it directly, and a computed field disappears from model_dump(mode="json"),
    # which is what PLORepository.bulk_insert passes straight to PLOTable(**data).
    #
    # Still list[str], not list[SmartFindingCode]. Narrowing the type would make
    # any row carrying a code this build no longer knows unreadable — and
    # "R_alignment" was emitted for months — so one stale string would take out
    # a whole program's PLO list instead of one field. The typed detail lives in
    # smart_check.findings; a validator below keeps the two in step.
    soft_flags: list[str] = Field(default_factory=list)
    # Which validator produced this verdict. "legacy" is the honest answer for a
    # row written before the agent existed, and it is what stops the UI claiming
    # an agent diagnosed something no agent saw. "code_only" means the agent
    # could not run (endpoint down, budget exhausted) and pure code decided
    # alone; "stale" means a designer edited the statement and nothing has
    # re-judged it since.
    smart_validated_by: Literal["agent", "code_only", "stale", "legacy"] = "legacy"
    # The validator's overall diagnosis in Thai — the one genuinely new thing a
    # designer reads. The tool-call trail is not persisted: it is the largest
    # object in the row by an order of magnitude, PLO is the response model of
    # five endpoints, and plo_report re-upserts every PLO on every checkpoint
    # run. It goes to loguru at DEBUG. If it ever has to be stored, it belongs
    # in its own audit table keyed (program_id, plo_id, run_at) — not a column
    # on the outcome.
    smart_diagnosis_th: str | None = None
    is_optional: bool = False

    @model_validator(mode="after")
    def check_no_forbidden_words(self) -> PLO:
        """Reject unmeasurable words at the model boundary.

        Shares one scan with `smart_rules.hard_failures` (see
        `smart_vocabulary.forbidden_words_in`) rather than carrying its own copy:
        two independent substring loops could disagree about what a forbidden
        word even is, and the moment they do, a PLO the gate passed raises here
        instead — out of `PLO(...)` in the synthesis stage.
        """
        if self.smart_escalated:
            return self  # kept for human review; SMART gate already failed it loudly
        found = forbidden_words_in(self.statement_th)
        if found:
            raise ValueError(
                f"PLO {self.plo_id} contains forbidden word '{found[0]}' — "
                f"unmeasurable. Rewrite with an observable Bloom verb."
            )
        return self

    @model_validator(mode="after")
    def check_soft_flags_match_the_findings(self) -> PLO:
        """`soft_flags` is the same information as the soft findings, stored
        twice because five readers want the flat list. Two copies drift, so say
        so here rather than letting the UI and the export disagree.

        A row with findings but no flags, or flags naming a criterion no finding
        mentions, is a bug in whatever wrote it. A row with flags and *no*
        findings is a pre-agent row and is fine — that is what `legacy` means.
        """
        if not self.smart_check.findings:
            return self
        from_findings = {
            f.criterion.value for f in self.smart_check.findings if f.severity == "soft"
        }
        if set(self.soft_flags) != from_findings:
            raise ValueError(
                f"PLO {self.plo_id} soft_flags {sorted(self.soft_flags)} disagree with "
                f"its soft findings {sorted(from_findings)}"
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


# ------------------------- PLO set review -------------------------


class RedundancyFinding(BaseModel):
    """PLOs the set review reads as one outcome. Advisory."""

    plo_ids: list[str]
    reason_th: str
    suggestion_th: str = ""
    # How many of the review's runs said this (stages/plo_review_consensus.py).
    # 1 for a one-run review and for rows written before the field existed.
    agreed_runs: int = 1


class KsecFinding(BaseModel):
    """Where one PLO's domain should sit, possibly several of K/S/E/C.

    `current` and `agrees` are computed in code from the PLO's Needs; only
    `suggested` and `reason_th` come from the reviewer. Plain `str` lists, not a
    Literal: a stored row must stay readable if the vocabulary ever moves (the
    `soft_flags` lesson).
    """

    plo_id: str
    current: list[str]
    suggested: list[str]
    agrees: bool
    reason_th: str = ""
    # How many of the review's runs said this (stages/plo_review_consensus.py).
    # 1 for a one-run review and for rows written before the field existed.
    agreed_runs: int = 1


class BloomFinding(BaseModel):
    plo_id: str
    declared: BloomLevel
    suggested_level: BloomLevel | None = None
    reason_th: str = ""
    # How many of the review's runs said this (stages/plo_review_consensus.py).
    # 1 for a one-run review and for rows written before the field existed.
    agreed_runs: int = 1


class KsecCoverage(BaseModel):
    """How many PLOs (optional included) sit in each of K/S/E/C.

    Computed in code, never by the reviewer.

    Plain `str` keys and flags for the `soft_flags` reason: a stored row must
    stay readable if the vocabulary moves.
    """

    counts: dict[str, int] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class BloomHistogram(BaseModel):
    """PLOs (optional included) per Bloom level against the degree level. Computed in code."""

    counts: dict[str, int] = Field(default_factory=dict)
    degree_level: str = ""
    flags: list[str] = Field(default_factory=list)


class UnusedNeedFinding(BaseModel):
    """An important Need no PLO cites: facts from code, verdict from the reviewer."""

    need_id: str
    statement_th: str
    demand_score: float
    ksec_categories: list[str] = Field(default_factory=list)
    stakeholder_types: list[str] = Field(default_factory=list)
    exclusion: str
    # The Need's statement is a fallback ("[ต้องทบทวน]" plus skill names). Separate
    # from `exclusion`, which gives out_of_scope precedence, so an unwritten Need
    # that is also out of scope is still known to be unwritten. The default keeps
    # rows stored before the field readable.
    unwritten: bool = False
    verdict: str | None = None
    reason_th: str = ""

    @model_validator(mode="before")
    @classmethod
    def _legacy_single_ksec(cls, data: Any) -> Any:
        """Reviews stored before Needs carried several tags hold one `ksec_category`."""
        if isinstance(data, dict) and "ksec_categories" not in data and "ksec_category" in data:
            data = {**data}
            data["ksec_categories"] = [data.pop("ksec_category")]
        return data

    # How many of the review's runs said this (stages/plo_review_consensus.py).
    # 1 for a one-run review and for rows written before the field existed.
    agreed_runs: int = 1


class ReviewToolCall(BaseModel):
    """One tool call the QA agent made, in order, for the "what it looked at" list."""

    tool: str
    arg: str = ""


class PLOSetReview(BaseModel):
    """The QA agent's review of one program's PLO set — see stages/plo_review.py.

    `plo_fingerprint` is the set it was made from; a review whose fingerprint no
    longer matches the stored PLOs is stale and is shown labelled as such.
    """

    program_id: str
    plo_fingerprint: str
    model: str
    created_at: datetime
    redundancies: list[RedundancyFinding] = Field(default_factory=list)
    ksec: list[KsecFinding] = Field(default_factory=list)
    bloom: list[BloomFinding] = Field(default_factory=list)
    bloom_distribution_th: str = ""
    summary_th: str = ""
    ksec_coverage: KsecCoverage = Field(default_factory=KsecCoverage)
    bloom_histogram: BloomHistogram = Field(default_factory=BloomHistogram)
    coverage_th: str = ""
    unused_needs: list[UnusedNeedFinding] = Field(default_factory=list)
    # "agent" for every row written before this field existed: those were all
    # made by the model. Plain str, not a Literal, for the soft_flags reason.
    reviewed_by: str = "agent"
    code_only_reason: str | None = None
    tool_calls: list[ReviewToolCall] = Field(default_factory=list)
    # Code: agent entries accept_review refused, by kind. Empty for a code_only
    # review and for rows written before the field existed.
    dropped_findings: dict[str, int] = Field(default_factory=dict)
    # Self-consistency (spec 2026-10-17): how many agent runs were asked for,
    # how many produced a usable answer, and how many had to agree for a finding
    # to count. All 1 for a one-run review and for rows written before the fields.
    runs_requested: int = 1
    runs_succeeded: int = 1
    agreement_threshold: int = 1


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
        "plo_review",
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


# ----------------------- Background jobs -------------------------

JobKind = Literal[
    "needs_pipeline",
    "skill_extraction",
    "need_combination",
    "plo_synthesis",
    "plo_review",
    "plo_report",
    "plo_revalidate",
]
JobStatus = Literal["running", "succeeded", "failed"]


class JobInfo(BaseModel):
    """A background stage run as the API reports it (api/jobs.py)."""

    job_id: str
    program_id: str
    kind: JobKind
    label_th: str = ""
    status: JobStatus
    params: dict[str, Any] = Field(default_factory=dict)
    result: Any | None = None
    error_th: str | None = None
    created_at: datetime
    finished_at: datetime | None = None

    # Stored naive UTC like every table here; sent with its offset, because a
    # browser reads a naive ISO string as local time. JSON only: a python-mode
    # dump (JobRepository.insert) must keep the datetime, since a DateTime
    # column rejects an ISO string.
    @field_serializer("created_at", "finished_at", when_used="json")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()


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

    A background run records the note in its `jobs.params`, as a record of what that
    run was given; nothing reads it back. The note is still an input to one request,
    so a re-run needs it typed again, and the synchronous `/plos/from-needs` keeps
    it nowhere.
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
