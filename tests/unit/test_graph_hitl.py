# tests/unit/test_graph_hitl.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.data.repositories import EvidenceRepository
from curriculum_agent.graph import AgentState, review_stakeholder_needs
from curriculum_agent.models import StakeholderEvidence


def _evidence(
    evidence_id: str, text: str, stakeholder_type: str = "employer"
) -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id=evidence_id,
        program_id="test",
        stakeholder_type=stakeholder_type,  # type: ignore[arg-type]
        source_name="แหล่งทดสอบ",
        raw_text_th=text,
    )


async def test_review_merges_designer_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """interrupt() payload must be merged into state, not discarded."""
    monkeypatch.setattr(EvidenceRepository, "list_by_program", AsyncMock(return_value=[]))
    initial_state: AgentState = {"program_id": "test", "classified_evidence": []}

    with patch("curriculum_agent.graph.interrupt", return_value={"designer_note": "x"}):
        result = await review_stakeholder_needs(initial_state)

    assert result["designer_note"] == "x"


async def test_review_keeps_state_when_no_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """If interrupt() returns non-dict (e.g. None), only the evidence is refreshed."""
    stored = [_evidence("E1", "ข้อความหลักฐานเดิม")]
    monkeypatch.setattr(EvidenceRepository, "list_by_program", AsyncMock(return_value=stored))
    initial_state: AgentState = {
        "program_id": "test",
        "current_stage": "stakeholder_needs",
        "classified_evidence": [stored[0].model_dump(mode="json")],
    }

    with patch("curriculum_agent.graph.interrupt", return_value=None):
        result = await review_stakeholder_needs(initial_state)

    assert result["current_stage"] == "stakeholder_needs"
    assert [e["evidence_id"] for e in result["classified_evidence"]] == ["E1"]


async def test_review_reloads_evidence_edited_while_paused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence is unlocked while a session waits here, so the designer can edit,
    add and delete items; skill_extraction reads `classified_evidence` from the
    checkpoint, and without a reload would extract from the old text and cite
    rows that now say something else."""
    paused = [
        _evidence("E1", "ข้อความเดิมก่อนแก้ไข"),
        _evidence("E2", "หลักฐานที่ผู้ออกแบบลบทิ้งระหว่างรอ"),
    ]
    now_stored = [
        _evidence("E1", "ข้อความที่ผู้ออกแบบแก้แล้ว"),
        # Added while paused; stored with the default class, so the reload has to
        # classify it the way stage 1 does.
        _evidence("E3", "หลักฐานที่เพิ่มระหว่างรอ", stakeholder_type="professional_council"),
    ]
    load = AsyncMock(return_value=now_stored)
    monkeypatch.setattr(EvidenceRepository, "list_by_program", load)
    state: AgentState = {
        "program_id": "test",
        "classified_evidence": [e.model_dump(mode="json") for e in paused],
    }

    with patch("curriculum_agent.graph.interrupt", return_value={"checkpoint_status": "approved"}):
        result = await review_stakeholder_needs(state)

    load.assert_awaited_once_with("test")
    by_id = {e["evidence_id"]: e for e in result["classified_evidence"]}
    assert set(by_id) == {"E1", "E3"}
    assert by_id["E1"]["raw_text_th"] == "ข้อความที่ผู้ออกแบบแก้แล้ว"
    assert by_id["E3"]["classification"] == "requirement"
    assert result["checkpoint_status"] == "approved"
