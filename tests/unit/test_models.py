from __future__ import annotations

import pytest
from pydantic import ValidationError

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    Domain,
    KrathwohlLevel,
    ProgramCreateRequest,
    ProgramMetadata,
    PsychomotorLevel,
    SkillCluster,
    SkillType,
    SMARTCheck,
)

SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def make_plo(**overrides) -> dict:
    base = {
        "plo_id": "PLO1",
        "program_id": "cs-test",
        "statement_th": "ออกแบบระบบซอฟต์แวร์ขนาดใหญ่ได้",
        "domain": Domain.COGNITIVE,
        "bloom_level": BloomLevel.CREATE,
        "is_subject_specific": True,
        "action_verb_th": "ออกแบบ",
        "smart_check": SMART_PASS,
        "source_cluster_ids": ["C1"],
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


def test_plo_rejects_empty_source_clusters() -> None:
    with pytest.raises(ValidationError, match="no source clusters"):
        PLO(**make_plo(source_cluster_ids=[]))


def test_plo_rejects_empty_source_evidence_ids() -> None:
    with pytest.raises(ValidationError, match="source_evidence_ids"):
        PLO(**make_plo(source_evidence_ids=[]))


# ---- domain / level matching -------------------------------------------


def test_cognitive_plo_requires_bloom_level() -> None:
    with pytest.raises(ValidationError, match="missing bloom_level"):
        PLO(**make_plo(bloom_level=None))


def test_affective_plo_requires_krathwohl_level() -> None:
    with pytest.raises(ValidationError, match="missing krathwohl_level"):
        PLO(**make_plo(domain=Domain.AFFECTIVE, bloom_level=None, krathwohl_level=None))


def test_affective_plo_accepts_krathwohl() -> None:
    plo = PLO(
        **make_plo(
            domain=Domain.AFFECTIVE,
            bloom_level=None,
            krathwohl_level=KrathwohlLevel.VALUING,
        )
    )
    assert plo.domain == Domain.AFFECTIVE


def test_psychomotor_plo_requires_psychomotor_level() -> None:
    with pytest.raises(ValidationError, match="missing psychomotor_level"):
        PLO(**make_plo(domain=Domain.PSYCHOMOTOR, bloom_level=None))


def test_psychomotor_plo_rejects_bloom_only() -> None:
    # bloom_level does not substitute for the psychomotor scale
    with pytest.raises(ValidationError, match="missing psychomotor_level"):
        PLO(**make_plo(domain=Domain.PSYCHOMOTOR, bloom_level=BloomLevel.APPLY))


def test_psychomotor_plo_accepts_psychomotor_level() -> None:
    plo = PLO(
        **make_plo(
            domain=Domain.PSYCHOMOTOR,
            bloom_level=None,
            psychomotor_level=PsychomotorLevel.PRECISE,
            statement_th="สาธิตการใช้เครื่องมือวัดทางไฟฟ้าได้อย่างถูกต้อง",
            action_verb_th="สาธิต",
        )
    )
    assert plo.domain == Domain.PSYCHOMOTOR
    assert plo.psychomotor_level == PsychomotorLevel.PRECISE


# ---- new fields (Task 2) ---------------------------------------------------


def test_skill_cluster_new_field_defaults() -> None:
    c = SkillCluster(
        cluster_id="c1",
        program_id="p1",
        canonical_name_th="วิเคราะห์ข้อมูล",
        description_th="กลุ่มทักษะวิเคราะห์ข้อมูล",
        skill_type=SkillType.KNOWLEDGE,
        is_subject_specific=True,
        member_skill_ids=["s1"],
        source_evidence_ids=["e1"],
        demand_score=0.5,
    )
    assert c.bloom_level is None
    assert c.psychomotor_level is None
    assert c.krathwohl_level is None
    assert c.is_optional is False
    assert c.classification_coverage == {}


def test_plo_new_field_defaults() -> None:
    plo = PLO(
        plo_id="PLO1",
        program_id="p1",
        statement_th="วิเคราะห์ข้อมูลด้วยเทคนิคทางสถิติได้",
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.ANALYZE,
        is_subject_specific=True,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_cluster_ids=["c1"],
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
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.ANALYZE,
        is_subject_specific=True,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=False, achievable=True, relevant=True, timely=True
        ),
        source_cluster_ids=["c1"],
        source_evidence_ids=["e1"],
        rationale_th="เหตุผล",
        smart_escalated=True,
    )
    assert plo.smart_escalated is True


def test_escalated_plo_still_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="no source clusters"):
        PLO(
            plo_id="PLO9",
            program_id="p1",
            statement_th="เข้าใจหลักการวิเคราะห์ข้อมูล",
            domain=Domain.COGNITIVE,
            bloom_level=BloomLevel.ANALYZE,
            is_subject_specific=True,
            action_verb_th="วิเคราะห์",
            smart_check=SMARTCheck(
                specific=True, measurable=False, achievable=True, relevant=True, timely=True
            ),
            source_cluster_ids=[],
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
        "vision_th": "วิสัยทัศน์",
        "mission_th": "พันธกิจ",
        "philosophy_th": "ปรัชญา",
        "program_goals_th": ["เป้าหมายที่ 1"],
        "program_objectives_th": ["วัตถุประสงค์ที่ 1"],
    }


def test_program_create_request_valid() -> None:
    req = ProgramCreateRequest(**_valid_create_kwargs())
    assert req.mission_th == "พันธกิจ"
    assert req.institutional_identity_th is None


def test_program_metadata_inherits_and_adds_program_id() -> None:
    meta = ProgramMetadata(program_id="cs-1", **_valid_create_kwargs())
    assert meta.program_id == "cs-1"
    assert meta.philosophy_th == "ปรัชญา"


@pytest.mark.parametrize("empty_field", ["mission_th", "philosophy_th"])
def test_empty_required_text_rejected(empty_field: str) -> None:
    kwargs = _valid_create_kwargs()
    kwargs[empty_field] = ""
    with pytest.raises(ValidationError):
        ProgramCreateRequest(**kwargs)


def test_empty_program_goals_rejected() -> None:
    kwargs = _valid_create_kwargs()
    kwargs["program_goals_th"] = []
    with pytest.raises(ValidationError):
        ProgramCreateRequest(**kwargs)


def test_program_metadata_accepts_legacy_backfilled_row() -> None:
    """Regression guard: rows backfilled by migration a845ef6ab4f6 with
    ""/[] for mission_th/philosophy_th/program_goals_th must still
    deserialize via ProgramMetadata (e.g. ProgramRepository.get())."""
    kwargs = _valid_create_kwargs()
    kwargs["mission_th"] = ""
    kwargs["philosophy_th"] = ""
    kwargs["program_goals_th"] = []
    meta = ProgramMetadata(program_id="cs-legacy", **kwargs)
    assert meta.mission_th == ""
    assert meta.philosophy_th == ""
    assert meta.program_goals_th == []
