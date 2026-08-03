from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import StakeholderEvidence, StakeholderType
from curriculum_agent.stages import stakeholder_needs as sn


def _evidence(eid: str, stype: StakeholderType) -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id=eid,
        program_id="cs-test",
        stakeholder_type=stype,
        source_name=f"source-{eid}",
        raw_text_th="ต้องการบัณฑิตที่วิเคราะห์ข้อมูลขนาดใหญ่ได้",
    )


async def test_run_classifies_without_any_llm_call(monkeypatch: pytest.MonkeyPatch):
    """No network, no cost: the stage must reach a full classification with the
    LLM module absent entirely."""
    monkeypatch.setattr(sn.EvidenceRepository, "bulk_insert", AsyncMock())

    state = await sn.run(
        {
            "program_id": "cs-test",
            "raw_evidence": [
                _evidence("E1", StakeholderType.PROFESSIONAL_COUNCIL).model_dump(mode="json"),
                _evidence("E2", StakeholderType.EMPLOYER).model_dump(mode="json"),
                _evidence("E3", StakeholderType.INSTITUTIONAL_DIRECTION).model_dump(mode="json"),
            ],
        }
    )

    by_id = {e["evidence_id"]: e["classification"] for e in state["classified_evidence"]}
    assert by_id == {"E1": "requirement", "E2": "general", "E3": "requirement"}


async def test_run_reclassifies_every_item_each_time(monkeypatch: pytest.MonkeyPatch):
    """Classification is now derived, not stored judgement — an item whose stored
    class disagrees with its type is corrected rather than skipped."""
    monkeypatch.setattr(sn.EvidenceRepository, "bulk_insert", AsyncMock())
    stale = _evidence("E1", StakeholderType.PROFESSIONAL_COUNCIL).model_dump(mode="json")
    stale["classification"] = "general"

    state = await sn.run({"program_id": "cs-test", "raw_evidence": [stale]})

    assert state["classified_evidence"][0]["classification"] == "requirement"


async def test_run_persists_the_classified_items(monkeypatch: pytest.MonkeyPatch):
    insert = AsyncMock()
    monkeypatch.setattr(sn.EvidenceRepository, "bulk_insert", insert)

    await sn.run(
        {
            "program_id": "cs-test",
            "raw_evidence": [_evidence("E1", StakeholderType.EMPLOYER).model_dump(mode="json")],
        }
    )

    insert.assert_awaited_once()
