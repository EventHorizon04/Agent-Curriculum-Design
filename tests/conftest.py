from __future__ import annotations

import pytest

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    Domain,
    ProgramMetadata,
    SkillCluster,
    SkillType,
    SMARTCheck,
)

SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
SMART_FAIL = SMARTCheck(
    specific=True, measurable=False, achievable=True, relevant=True, timely=True
)


@pytest.fixture
def program_metadata() -> ProgramMetadata:
    return ProgramMetadata(
        program_id="cs-test",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
        vision_th="มุ่งผลิตบัณฑิตที่มีความเชี่ยวชาญด้านเทคโนโลยี",
        program_objectives_th=["ผลิตบัณฑิตที่มีทักษะด้านซอฟต์แวร์"],
    )


@pytest.fixture
def skill_cluster() -> SkillCluster:
    return SkillCluster(
        cluster_id="C1",
        program_id="cs-test",
        canonical_name_th="การเขียนโปรแกรม",
        description_th="ทักษะการเขียนและออกแบบโปรแกรม",
        skill_type=SkillType.KNOWLEDGE,
        is_subject_specific=True,
        member_skill_ids=["S1", "S2"],
        source_evidence_ids=["E1"],
        demand_score=0.9,
    )


@pytest.fixture
def valid_plo(skill_cluster: SkillCluster) -> PLO:
    return PLO(
        plo_id="PLO1",
        program_id="cs-test",
        statement_th="ออกแบบและพัฒนาซอฟต์แวร์ที่มีคุณภาพได้",
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.CREATE,
        is_subject_specific=True,
        action_verb_th="ออกแบบ",
        smart_check=SMART_PASS,
        source_cluster_ids=["C1"],
        rationale_th="ทักษะหลักที่นายจ้างต้องการ",
    )


@pytest.fixture
def sample_metadata() -> ProgramMetadata:
    return ProgramMetadata(
        program_id="cs-test",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
        vision_th="มุ่งผลิตบัณฑิตที่มีความเชี่ยวชาญด้านเทคโนโลยี",
        program_objectives_th=["ผลิตบัณฑิตที่มีทักษะด้านซอฟต์แวร์"],
    )


@pytest.fixture
def sample_clusters(sample_metadata: ProgramMetadata) -> list[SkillCluster]:
    return [
        SkillCluster(
            cluster_id="C1",
            program_id=sample_metadata.program_id,
            canonical_name_th="การเขียนโปรแกรม",
            description_th="ทักษะการเขียนและออกแบบโปรแกรม",
            skill_type=SkillType.KNOWLEDGE,
            is_subject_specific=True,
            member_skill_ids=["S1", "S2"],
            source_evidence_ids=["E1"],
            demand_score=0.9,
        )
    ]
