from __future__ import annotations

import pytest
from pydantic import ValidationError

from curriculum_agent.models import (
    NOTE_MAX_CHARS,
    PLO,
    BloomLevel,
    DesignerNoteRequest,
    ExtractedSkill,
    KSECCategory,
    Need,
    ProgramCreateRequest,
    ProgramMetadata,
    SMARTCheck,
    StakeholderType,
)

SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def make_plo(**overrides) -> dict:
    base = {
        "plo_id": "PLO1",
        "program_id": "cs-test",
        "statement_th": "ออกแบบระบบซอฟต์แวร์ขนาดใหญ่ได้",
        "bloom_level": BloomLevel.CREATE,
        "action_verb_th": "ออกแบบ",
        "smart_check": SMART_PASS,
        "source_need_ids": ["C1"],
        "source_evidence_ids": ["E1"],
        "rationale_th": "ทดสอบ",
    }
    base.update(overrides)
    return base


# ---- forbidden words ---------------------------------------------------


@pytest.mark.parametrize("word", ["รู้", "จำ", "เข้าใจ", "ซาบซึ้ง", "ตระหนัก", "ศรัทธา", "รัก"])
def test_plo_rejects_forbidden_word(word: str) -> None:
    with pytest.raises(ValidationError, match="forbidden word"):
        PLO(**make_plo(statement_th=f"นักศึกษา{word}หลักการออกแบบ"))


def test_plo_accepts_clean_statement() -> None:
    plo = PLO(**make_plo())
    assert plo.plo_id == "PLO1"


# ---- evidence tracing --------------------------------------------------


def test_plo_rejects_empty_source_need_ids() -> None:
    with pytest.raises(ValidationError, match="no source Needs"):
        PLO(**make_plo(source_need_ids=[]))


def test_plo_rejects_empty_source_evidence_ids() -> None:
    with pytest.raises(ValidationError, match="source_evidence_ids"):
        PLO(**make_plo(source_evidence_ids=[]))


# ---- cognitive-only reshape (Task 6) ------------------------------------


def test_plo_requires_bloom_level() -> None:
    # bloom_level has no default — every PLO is cognitive, so it must be supplied.
    with pytest.raises(ValidationError):
        PLO(**{k: v for k, v in make_plo().items() if k != "bloom_level"})


# ---- new fields (Task 2) ---------------------------------------------------


def test_plo_new_field_defaults() -> None:
    plo = PLO(
        plo_id="PLO1",
        program_id="p1",
        statement_th="วิเคราะห์ข้อมูลด้วยเทคนิคทางสถิติได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=["c1"],
        source_evidence_ids=["e1"],
        rationale_th="จำเป็นต่อวิชาชีพ",
    )
    assert plo.smart_retry_count == 0
    assert plo.smart_escalated is False
    assert plo.soft_flags == []
    assert plo.is_optional is False


def test_escalated_plo_may_carry_forbidden_word() -> None:
    plo = PLO(
        plo_id="PLO9",
        program_id="p1",
        statement_th="เข้าใจหลักการวิเคราะห์ข้อมูล",  # forbidden word, but escalated
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=False, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=["c1"],
        source_evidence_ids=["e1"],
        rationale_th="เหตุผล",
        smart_escalated=True,
    )
    assert plo.smart_escalated is True


def test_escalated_plo_still_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="no source Needs"):
        PLO(
            plo_id="PLO9",
            program_id="p1",
            statement_th="เข้าใจหลักการวิเคราะห์ข้อมูล",
            bloom_level=BloomLevel.ANALYZE,
            action_verb_th="วิเคราะห์",
            smart_check=SMARTCheck(
                specific=True, measurable=False, achievable=True, relevant=True, timely=True
            ),
            source_need_ids=[],
            source_evidence_ids=[],
            rationale_th="เหตุผล",
            smart_escalated=True,
        )


# ---- ProgramCreateRequest / ProgramMetadata split (Task 1) -------------


def _valid_create_kwargs() -> dict:
    return {
        "name_th": "วิทยาการคอมพิวเตอร์",
        "name_en": "Computer Science",
        "field": "Computer Science",
        "degree_level": "bachelor",
        "duration_years": 4,
        "faculty": "วิศวกรรมศาสตร์",
        "university": "มหาวิทยาลัยทดสอบ",
        "program_goals_th": ["เป้าหมายที่ 1"],
        "program_objectives_th": ["วัตถุประสงค์ที่ 1"],
    }


def test_program_create_request_valid() -> None:
    req = ProgramCreateRequest(**_valid_create_kwargs())
    assert req.name_th == "วิทยาการคอมพิวเตอร์"
    assert req.program_goals_th == ["เป้าหมายที่ 1"]


def test_program_metadata_inherits_and_adds_program_id() -> None:
    meta = ProgramMetadata(program_id="cs-1", **_valid_create_kwargs())
    assert meta.program_id == "cs-1"
    assert meta.program_goals_th == ["เป้าหมายที่ 1"]


def test_program_names_are_optional() -> None:
    """Intake no longer asks for a program name — the institution, faculty, and
    field identify it. The columns stay for programs created before the change."""
    kwargs = _valid_create_kwargs()
    del kwargs["name_th"]
    del kwargs["name_en"]

    req = ProgramCreateRequest(**kwargs)

    assert req.name_th == ""
    assert req.name_en == ""


def test_goals_and_objectives_are_optional() -> None:
    """Intake stopped collecting them — the form asks for the program's place in
    the institution and nothing else. Both stay on the model so existing rows
    keep their content and CHECO 1.5 has somewhere to read from, but a create
    request that omits them is valid."""
    kwargs = _valid_create_kwargs()
    del kwargs["program_goals_th"]
    del kwargs["program_objectives_th"]

    req = ProgramCreateRequest(**kwargs)

    assert req.program_goals_th == []
    assert req.program_objectives_th == []


def test_program_metadata_accepts_legacy_backfilled_row() -> None:
    """Regression guard: rows backfilled by migration a845ef6ab4f6 with
    [] for program_goals_th must still deserialize via ProgramMetadata
    (e.g. ProgramRepository.get())."""
    kwargs = _valid_create_kwargs()
    kwargs["program_goals_th"] = []
    meta = ProgramMetadata(program_id="cs-legacy", **kwargs)
    assert meta.program_goals_th == []


def test_program_models_no_longer_carry_institutional_metadata():
    """The institution's direction lives in the evidence table now — a second copy
    on the program row would be a source of truth nobody keeps consistent."""
    from curriculum_agent.models import ProgramCreateRequest, ProgramMetadata

    gone = (
        "vision_th",
        "mission_th",
        "philosophy_th",
        "institutional_identity_th",
        "student_identity_th",
    )
    for field in gone:
        assert field not in ProgramCreateRequest.model_fields
        assert field not in ProgramMetadata.model_fields


def test_isced_code_is_still_validated_against_the_taxonomy():
    """The suggestion feature is gone but the code is still typed by hand, so the
    guard against an off-taxonomy value matters more, not less."""
    import pytest

    from curriculum_agent.models import ProgramCreateRequest

    with pytest.raises(ValueError, match="ISCED"):
        ProgramCreateRequest(
            name_th="วิทยาการคอมพิวเตอร์",
            name_en="Computer Science",
            field="Computer Science",
            isced_code="9999",
            degree_level="bachelor",
            duration_years=4,
            faculty="วิทยาศาสตร์",
            university="ทดสอบ",
            program_goals_th=["ผลิตบัณฑิตที่ทำงานได้"],
            program_objectives_th=["พัฒนาทักษะการเขียนโปรแกรม"],
        )


# ---- ProgramSummary (Task 1: program history) ---------------------------


def test_program_summary_minimal() -> None:
    """current_stage is required and session_status is not: progress is derived
    from the program's own rows and so always known, while "no run has ever
    started" is a real answer a session status has to be able to give."""
    from datetime import datetime

    from curriculum_agent.models import ProgramSummary

    s = ProgramSummary(
        program_id="computer-science",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        degree_level="bachelor",
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        current_stage="intake",
    )
    assert s.current_stage == "intake"
    assert s.session_status is None


def test_program_summary_with_session_fields() -> None:
    from datetime import datetime

    from curriculum_agent.models import ProgramSummary

    s = ProgramSummary(
        program_id="computer-science",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        degree_level="bachelor",
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        current_stage="skill_extraction",
        session_status="suspended",
    )
    assert s.current_stage == "skill_extraction"
    assert s.session_status == "suspended"


# ---- KSEC split / ExtractedSkill reshape (Task 2) ----------------------


def test_ksec_category_has_five_values_with_skill_split():
    assert {c.value for c in KSECCategory} == {"K", "S", "EC", "E", "C"}


def test_ksec_category_rejects_mixed_and_split_tags():
    for bad in ("mixed", "SS", "GS"):
        with pytest.raises(ValueError):
            KSECCategory(bad)


def test_parent_stakeholder_type_exists():
    assert StakeholderType.PARENT.value == "parent"


def _skill_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "skill_id": "S1",
        "program_id": "cs-test",
        "skill_name_th": "วิเคราะห์ข้อมูลขนาดใหญ่",
        "ksec_category": KSECCategory.S,
        "bloom_level": BloomLevel.ANALYZE,
        "evidence_span_th": "ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้",
        "source_evidence_id": "E1",
        "source_stakeholder_type": StakeholderType.EMPLOYER,
        "extraction_method": "llm",
        "confidence": 0.9,
        "importance_score": 0.5,
    }
    base.update(overrides)
    return base


def test_extracted_skill_accepts_full_tag_set():
    skill = ExtractedSkill(**_skill_kwargs())
    assert skill.ksec_category is KSECCategory.S
    assert skill.bloom_level is BloomLevel.ANALYZE


@pytest.mark.parametrize("missing", ["bloom_level", "ksec_category", "evidence_span_th"])
def test_extracted_skill_requires_tags_and_span(missing: str):
    kwargs = _skill_kwargs()
    del kwargs[missing]
    with pytest.raises(ValidationError):
        ExtractedSkill(**kwargs)


# ---- Need model (Task 5) -----------------------------------------------


def _need_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "need_id": "N1",
        "program_id": "cs-test",
        "statement_th": "สามารถวิเคราะห์ข้อมูลขนาดใหญ่เพื่อหา insight ทางธุรกิจ",
        "ksec_category": KSECCategory.S,
        "bloom_level": BloomLevel.ANALYZE,
        "member_skill_ids": ["S1", "S2"],
        "source_evidence_ids": ["E1"],
        "freq": 2,
        "demand_score": 0.8,
    }
    base.update(overrides)
    return base


def test_need_accepts_valid_payload():
    need = Need(**_need_kwargs())
    assert need.freq == 2
    assert need.is_optional is False


@pytest.mark.parametrize("empty_field", ["member_skill_ids", "source_evidence_ids"])
def test_need_requires_evidence_trail(empty_field: str):
    with pytest.raises(ValidationError):
        Need(**_need_kwargs(**{empty_field: []}))


# ---- Cross-stage designer note (Task 1) ---------------------------------


def test_designer_note_defaults_to_none():
    assert DesignerNoteRequest().note_th is None


def test_designer_note_blank_becomes_absent():
    """A blank textarea must not append an empty guidance block to the prompt."""
    assert DesignerNoteRequest(note_th="   \n\t ").note_th is None


def test_designer_note_rejects_over_the_limit():
    with pytest.raises(ValidationError):
        DesignerNoteRequest(note_th="ก" * (NOTE_MAX_CHARS + 1))


def test_designer_note_strips_before_measuring_length():
    """The limit applies to the stripped text.

    Pins the validator to mode="before". Run it after the constraint instead and
    these trailing spaces push an exactly-full note over the limit, rejecting a
    note the designer legitimately typed.
    """
    padded = "ก" * NOTE_MAX_CHARS + "    "
    assert DesignerNoteRequest(note_th=padded).note_th == "ก" * NOTE_MAX_CHARS


# ---- Stakeholder taxonomy (Task 1) --------------------------------------


def test_every_stakeholder_type_has_a_group():
    """A type added without a STAKEHOLDER_GROUP entry must fail loudly here,
    not default silently to internal at the weight table."""
    from curriculum_agent.models import STAKEHOLDER_GROUP, StakeholderType

    assert set(STAKEHOLDER_GROUP) == set(StakeholderType)


def test_external_and_internal_membership():
    from curriculum_agent.models import STAKEHOLDER_GROUP, StakeholderGroup, StakeholderType

    assert STAKEHOLDER_GROUP[StakeholderType.EMPLOYER] is StakeholderGroup.EXTERNAL
    assert STAKEHOLDER_GROUP[StakeholderType.PROFESSIONAL_COUNCIL] is StakeholderGroup.EXTERNAL
    assert STAKEHOLDER_GROUP[StakeholderType.FACULTY] is StakeholderGroup.INTERNAL
    assert STAKEHOLDER_GROUP[StakeholderType.INSTITUTIONAL_DIRECTION] is StakeholderGroup.INTERNAL


def test_ksec_has_no_ss_or_gs():
    from curriculum_agent.models import KSECCategory

    values = {c.value for c in KSECCategory}
    assert values == {"K", "S", "EC", "E", "C"}


def test_a_skill_may_not_carry_the_ec_umbrella_tag():
    """EC is a Need-level tag produced by bucketing; a skill mention is
    always specifically E or C."""
    from curriculum_agent.models import SKILL_KSEC, KSECCategory

    assert KSECCategory.EC not in SKILL_KSEC
    assert SKILL_KSEC == {KSECCategory.K, KSECCategory.S, KSECCategory.E, KSECCategory.C}  # noqa: SIM300


# ---- PLO scope guard ---------------------------------------------------


def _valid_skill_kwargs() -> dict:
    return {
        "skill_id": "S1",
        "program_id": "cs-test",
        "skill_name_th": "วิเคราะห์ข้อมูลขนาดใหญ่",
        "ksec_category": KSECCategory.S,
        "bloom_level": BloomLevel.ANALYZE,
        "evidence_span_th": "ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้",
        "source_evidence_id": "E1",
        "source_stakeholder_type": StakeholderType.EMPLOYER,
        "extraction_method": "llm",
        "confidence": 0.9,
        "importance_score": 0.5,
    }


def test_a_skill_that_was_never_judged_on_the_graduate_axis_reads_as_a_capability() -> None:
    """Defaulting to True is what keeps the pipeline behaving as it did for every
    skill row that predates the flag — the same reason the migration gives the
    column a server_default of true, and the same reason is_field_relevant
    defaults the way it does. False would mark every stored skill an institutional
    activity and disqualify every Need built from them."""
    skill = ExtractedSkill(**_valid_skill_kwargs())

    assert skill.is_graduate_capability is True
    assert skill.is_field_relevant is True


def test_the_two_skill_axes_stay_two_fields() -> None:
    """Separate bools, not one enum with four values. The 56% recall figure was
    measured on this shape and on no other, and the second field is what pushed
    the field flag from 3/9 to 5/9 even with no scope statement present at all.
    Collapsing them later is possible; splitting them later is not."""
    assert ExtractedSkill.model_fields["is_field_relevant"].annotation is bool
    assert ExtractedSkill.model_fields["is_graduate_capability"].annotation is bool


def test_a_program_may_be_created_without_a_scope_statement() -> None:
    """The intake field is optional, and leaving it blank is the common case: the
    program then gets the extraction prompt byte for byte as it was, and the guard
    turns into a no-op on its own."""
    req = ProgramCreateRequest(**_valid_create_kwargs())

    assert req.scope_th == ""


def test_a_scope_statement_survives_the_trip_to_program_metadata() -> None:
    scope = "หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจ การล่ามการเจรจา และการตรวจแก้งานแปล"
    meta = ProgramMetadata(program_id="cs-1", scope_th=scope, **_valid_create_kwargs())

    assert meta.scope_th == scope


def test_program_metadata_deserializes_a_row_written_before_the_scope_column() -> None:
    """Stored rows have no scope_th at all, and ProgramRepository.get validates
    straight off the row. A required field here would 500 every read of every
    program created before this shipped."""
    row = {"program_id": "cs-1", **_valid_create_kwargs()}

    meta = ProgramMetadata.model_validate(row)

    assert meta.scope_th == ""
