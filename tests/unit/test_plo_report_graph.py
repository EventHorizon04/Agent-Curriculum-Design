from __future__ import annotations

from unittest.mock import patch

from curriculum_agent.graph import AgentState, build_graph, review_plo_report


def test_review_plo_report_merges_payload():
    edited = [{"plo_id": "PLO1", "classification": "generic"}]
    state: AgentState = {
        "program_id": "t",
        "plos": [{"plo_id": "PLO1", "classification": "specific"}],
    }
    with patch("curriculum_agent.graph.interrupt", return_value={"plos": edited}):
        result = review_plo_report(state)
    assert result["plos"] == edited


def test_review_plo_report_returns_state_when_no_payload():
    state: AgentState = {"program_id": "t", "plos": [{"plo_id": "PLO1"}]}
    with patch("curriculum_agent.graph.interrupt", return_value=None):
        result = review_plo_report(state)
    assert result == state


def test_graph_wires_plo_report_and_detaches_ylo():
    nodes = set(build_graph().get_graph().nodes)
    assert "plo_report" in nodes
    assert "review_plo_report" in nodes
    assert "ylo_derivation" not in nodes
    assert "review_ylo" not in nodes
