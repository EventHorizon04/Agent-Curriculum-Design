from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import StakeholderEvidence, StakeholderType
from curriculum_agent.stages import stakeholder_needs as sn


def _evidence(stakeholder_type: StakeholderType) -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id="E1",
        program_id="cs-test",
        stakeholder_type=stakeholder_type,
        source_name="ตัวอย่างแหล่งข้อมูล",
        raw_text_th="อยากให้บัณฑิตสื่อสารกับชุมชนได้ดี",
    )


@pytest.mark.parametrize("stype", [StakeholderType.COMMUNITY, StakeholderType.PARENT])
async def test_community_and_parent_are_want_without_llm(
    stype: StakeholderType, monkeypatch: pytest.MonkeyPatch
):
    llm = AsyncMock()
    monkeypatch.setattr(sn, "complete_light", llm)

    result = await sn.classify_single(_evidence(stype))

    assert result.classification == "want"
    llm.assert_not_awaited()  # pure code — no tokens spent


async def test_employer_takes_the_llm_path(monkeypatch: pytest.MonkeyPatch):
    llm = AsyncMock(
        return_value=sn._ClassifyResult(
            classification="requirement", classification_rationale_th="เป็นข้อกำหนดของวิชาชีพ"
        )
    )
    monkeypatch.setattr(sn, "complete_light", llm)

    result = await sn.classify_single(_evidence(StakeholderType.EMPLOYER))

    assert result.classification == "requirement"
    llm.assert_awaited_once()


def test_llm_result_model_cannot_return_want():
    # `want` is reserved for community/parent, decided in code. The LLM schema
    # must not offer it, or an employer posting could be demoted to a wish.
    with pytest.raises(ValueError):
        sn._ClassifyResult(classification="want", classification_rationale_th="x")


def test_want_only_types_is_exactly_community_and_parent():
    assert frozenset({StakeholderType.COMMUNITY, StakeholderType.PARENT}) == sn.WANT_ONLY_TYPES
