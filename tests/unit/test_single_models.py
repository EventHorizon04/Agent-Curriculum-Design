from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    Need,
    ProgramMetadata,
    SMARTCheck,
)


def _need_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "need_id": "N1",
        "program_id": "cs-test",
        "statement_th": "ตลาดแรงงานต้องการผู้ที่วิเคราะห์ข้อมูลได้",
        "ksec_categories": ["S"],
        "bloom_level": BloomLevel.ANALYZE,
        "member_skill_ids": ["S1"],
        "source_evidence_ids": ["E1"],
        "freq": 1,
        "demand_score": 0.5,
    }
    base.update(overrides)
    return base


def _program_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "program_id": "cs-1",
        "field": "วิทยาการคอมพิวเตอร์",
        "degree_level": "bachelor",
        "duration_years": 4,
        "faculty": "วิทยาศาสตร์",
        "university": "มหาวิทยาลัยทดสอบ",
    }
    base.update(overrides)
    return base


def _plo_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "plo_id": "PLO1",
        "program_id": "cs-test",
        "statement_th": "ออกแบบระบบซอฟต์แวร์ขนาดใหญ่ได้",
        "bloom_level": BloomLevel.CREATE,
        "action_verb_th": "ออกแบบ",
        "smart_check": SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        "source_need_ids": ["N1"],
        "source_evidence_ids": ["E1"],
        "rationale_th": "ทดสอบ",
    }
    base.update(overrides)
    return base


def test_single_need_may_have_no_skills() -> None:
    need = Need(**_need_kwargs(origin="single", member_skill_ids=[]))
    assert need.member_skill_ids == [] and need.in_field_ratio == 1.0


def test_multi_need_without_skills_is_still_rejected() -> None:
    with pytest.raises(ValidationError):
        Need(**_need_kwargs(member_skill_ids=[]))


def test_old_rows_read_back_as_multi() -> None:
    assert Need(**_need_kwargs()).origin == "multi"
    assert ProgramMetadata(**_program_kwargs()).agent_mode == "multi"


def test_single_agent_is_a_valid_validator_label() -> None:
    plo = PLO(**_plo_kwargs(smart_validated_by="single_agent"))
    assert plo.smart_validated_by == "single_agent"
