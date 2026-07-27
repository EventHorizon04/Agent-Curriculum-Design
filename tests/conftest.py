from __future__ import annotations

import sys

if sys.platform == "win32":
    # Block `import magic` (python-magic) on Windows. Under Git Bash the PATH
    # contains C:\Program Files\Git\usr\bin, so python-magic's loader picks up
    # msys-magic-1.dll — an MSYS2 build whose runtime is incompatible with
    # native CPython. Loading it segfaults or hangs the whole pytest process.
    # Forcing ImportError instead makes unstructured take its extension-based
    # fallback (LIBMAGIC_AVAILABLE = False), which is deterministic across
    # shells. Remove this once a native libmagic (e.g. python-magic-bin) is a
    # project dependency.
    sys.modules["magic"] = None  # type: ignore[assignment]

import pytest

from curriculum_agent.config import settings
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    ProgramMetadata,
    SMARTCheck,
)

SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
SMART_FAIL = SMARTCheck(
    specific=True, measurable=False, achievable=True, relevant=True, timely=True
)


@pytest.fixture(autouse=True)
def _default_api_key_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests assume auth is disabled (settings.api_key is None) unless a test
    explicitly monkeypatches it otherwise. Without this, a developer's local
    .env with a real API_KEY leaks into the whole suite via pydantic-settings'
    env loading, turning every unauthenticated-request test into a spurious
    401."""
    monkeypatch.setattr(settings, "api_key", None)


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
        mission_th="พันธกิจของหลักสูตร",
        philosophy_th="ปรัชญาของหลักสูตร",
        program_goals_th=["เป้าหมายหลักสูตรที่ 1"],
        program_objectives_th=["ผลิตบัณฑิตที่มีทักษะด้านซอฟต์แวร์"],
    )


@pytest.fixture
def need() -> Need:
    return Need(
        need_id="N1",
        program_id="cs-test",
        statement_th="สามารถเขียนและออกแบบโปรแกรมตามความต้องการของธุรกิจ",
        ksec_category=KSECCategory.SS,
        bloom_level=BloomLevel.CREATE,
        member_skill_ids=["S1", "S2"],
        source_evidence_ids=["E1"],
        freq=2,
        demand_score=0.9,
    )


@pytest.fixture
def valid_plo(need: Need) -> PLO:
    return PLO(
        plo_id="PLO1",
        program_id="cs-test",
        statement_th="ออกแบบและพัฒนาซอฟต์แวร์ที่มีคุณภาพได้",
        bloom_level=BloomLevel.CREATE,
        is_subject_specific=True,
        action_verb_th="ออกแบบ",
        smart_check=SMART_PASS,
        source_need_ids=[need.need_id],
        source_evidence_ids=need.source_evidence_ids,
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
        mission_th="พันธกิจของหลักสูตร",
        philosophy_th="ปรัชญาของหลักสูตร",
        program_goals_th=["เป้าหมายหลักสูตรที่ 1"],
        program_objectives_th=["ผลิตบัณฑิตที่มีทักษะด้านซอฟต์แวร์"],
    )


@pytest.fixture
def sample_needs(sample_metadata: ProgramMetadata) -> list[Need]:
    return [
        Need(
            need_id="C1",
            program_id=sample_metadata.program_id,
            statement_th="สามารถเขียนและออกแบบโปรแกรมตามความต้องการของธุรกิจ",
            ksec_category=KSECCategory.SS,
            bloom_level=BloomLevel.CREATE,
            member_skill_ids=["S1", "S2"],
            source_evidence_ids=["E1"],
            freq=2,
            demand_score=0.9,
        )
    ]
