from __future__ import annotations

from curriculum_agent.graph import DESIGNER_STAGES, REVIEW_NODE_STAGE, build_graph


def _edges() -> set[tuple[str, str]]:
    g = build_graph().get_graph()
    return {(e.source, e.target) for e in g.edges}


def test_graph_wires_plo_report_and_detaches_ylo():
    nodes = set(build_graph().get_graph().nodes)
    assert "plo_report" in nodes
    assert "plo_review" in nodes
    assert "review_plo_report" not in nodes
    assert "ylo_derivation" not in nodes
    assert "review_ylo" not in nodes


def test_report_then_qa_then_end_with_no_checkpoint_after_the_plos():
    edges = _edges()
    assert ("review_plos_node", "plo_report") in edges
    assert ("plo_report", "plo_review") in edges
    assert ("plo_review", "__end__") in edges
    assert not any("review_plo_report" in (a, b) for a, b in edges)


def test_qa_is_the_sixth_designer_stage_and_no_checkpoint_maps_to_it():
    assert DESIGNER_STAGES[-2:] == ("plo_report", "plo_review")
    assert "review_plo_report" not in REVIEW_NODE_STAGE
