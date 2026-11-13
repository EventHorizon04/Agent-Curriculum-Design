from __future__ import annotations

from curriculum_agent.graph import DESIGNER_STAGES, REVIEW_NODE_STAGE, build_graph


def _edges() -> set[tuple[str, str]]:
    g = build_graph().get_graph()
    return {(e.source, e.target) for e in g.edges}


def test_graph_wires_plo_report_and_plo_review():
    nodes = set(build_graph().get_graph().nodes)
    assert "plo_report" in nodes
    assert "plo_review" in nodes
    assert "review_plo_report" not in nodes


def test_review_then_checkpoint_then_report_then_end():
    edges = _edges()
    assert ("plo_synthesis", "plo_review") in edges
    assert ("plo_review", "review_plos_node") in edges
    assert ("review_plos_node", "plo_report") in edges
    assert ("plo_report", "__end__") in edges
    # The old order is gone.
    assert ("plo_synthesis", "review_plos_node") not in edges
    assert ("plo_report", "plo_review") not in edges
    assert ("plo_review", "__end__") not in edges
    assert not any("review_plo_report" in (a, b) for a, b in edges)


def test_report_is_the_last_designer_stage_and_the_checkpoint_maps_to_the_review():
    assert DESIGNER_STAGES[-2:] == ("plo_review", "plo_report")
    assert "review_plo_report" not in REVIEW_NODE_STAGE
    assert REVIEW_NODE_STAGE["review_plos_node"] == "plo_review"


async def test_review_plos_resume_reloads_edited_plos(monkeypatch):
    """The designer edits a PLO while the session is suspended, then approves: the
    state holds the stored statement, not the checkpoint's."""
    from unittest.mock import AsyncMock

    from curriculum_agent import graph as graph_mod
    from curriculum_agent.data import repositories as repos
    from curriculum_agent.models import PLO, BloomLevel, SMARTCheck

    def plo(statement: str) -> PLO:
        return PLO(
            plo_id="PLO1",
            program_id="p",
            statement_th=statement,
            bloom_level=BloomLevel.APPLY,
            action_verb_th="แปล",
            smart_check=SMARTCheck(
                specific=True, measurable=True, achievable=True, relevant=True, timely=True
            ),
            source_need_ids=["n1"],
            source_evidence_ids=["e1"],
            rationale_th="เหตุผล",
        )

    monkeypatch.setattr(graph_mod, "interrupt", lambda _msg: {"checkpoint_status": "approved"})
    monkeypatch.setattr(
        repos.PLORepository,
        "list_by_program",
        AsyncMock(return_value=[plo("แปลเอกสารที่ผู้ออกแบบแก้แล้ว")]),
    )

    state = await graph_mod.review_plos(
        {"program_id": "p", "plos": [plo("แปลเอกสารฉบับเดิม").model_dump(mode="json")]}
    )

    assert state["plos"][0]["statement_th"] == "แปลเอกสารที่ผู้ออกแบบแก้แล้ว"
    assert state["checkpoint_status"] == "approved"
