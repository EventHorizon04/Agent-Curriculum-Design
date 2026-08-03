# tests/unit/test_graph_hitl.py
from __future__ import annotations

from unittest.mock import patch

from curriculum_agent.graph import AgentState, review_stakeholder_needs


def test_review_merges_designer_edits() -> None:
    """interrupt() payload must be merged into state, not discarded."""
    edited_evidence = [{"evidence_id": "E1", "classification": "general"}]
    initial_state: AgentState = {
        "program_id": "test",
        "classified_evidence": [{"evidence_id": "E1", "classification": "unclassified"}],
    }

    with patch(
        "curriculum_agent.graph.interrupt", return_value={"classified_evidence": edited_evidence}
    ):
        result = review_stakeholder_needs(initial_state)

    assert result["classified_evidence"] == edited_evidence


def test_review_returns_state_unchanged_when_no_payload() -> None:
    """If interrupt() returns non-dict (e.g. None), state must be returned as-is."""
    initial_state: AgentState = {
        "program_id": "test",
        "classified_evidence": [{"evidence_id": "E1", "classification": "general"}],
    }

    with patch("curriculum_agent.graph.interrupt", return_value=None):
        result = review_stakeholder_needs(initial_state)

    assert result == initial_state
