"""The node -> stage map has to agree with the graph it describes.

`_run_graph` reads the node a suspended run stopped on and records the stage a
designer would call it. That map lived in the API layer and drifted: it still
named a `review_clusters` node that had been renamed `review_needs_node`, so
every run suspending after need_combination stored the raw node name in
`sessions.current_stage`, and the UI — which keys its rail off the stage list —
read that as a program that had never started a stage.

These tests check the map against the compiled graph in both directions, so a
node rename fails here rather than silently downgrading a program's progress.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_agent.api.routes.sessions import _run_graph
from curriculum_agent.graph import DESIGNER_STAGES, REVIEW_NODE_STAGE, build_graph

# Review nodes are named by convention, and the convention is load-bearing: it is
# what lets this test find them without hand-listing the very thing under test.
_REVIEW_PREFIX = "review"


def _review_nodes() -> set[str]:
    return {name for name in build_graph().nodes if name.startswith(_REVIEW_PREFIX)}


def test_every_review_node_maps_to_a_stage():
    """No node may suspend into a stage name nobody downstream recognises."""
    assert _review_nodes() == set(REVIEW_NODE_STAGE)


def test_no_stale_keys():
    """A key naming a node that no longer exists is dead weight that reads as
    coverage — which is exactly how `review_clusters` survived a rename."""
    assert set(REVIEW_NODE_STAGE) <= _review_nodes()


def test_every_mapped_stage_is_a_designer_stage():
    for node, stage in REVIEW_NODE_STAGE.items():
        assert stage in DESIGNER_STAGES, f"{node} maps to unknown stage '{stage}'"


def test_the_plo_checkpoint_is_reported_as_the_review_stage():
    assert REVIEW_NODE_STAGE["review_plos_node"] == "plo_review"


async def test_suspending_at_the_plo_checkpoint_records_plo_review():
    """The gate now sits after the QA review, so the session records that stage."""
    repo = AsyncMock()
    with patch("curriculum_agent.api.routes.sessions.SessionRepository", return_value=repo):
        await _run_graph(_suspended_at("review_plos_node"), {}, {}, "s1")

    repo.set_suspended.assert_awaited_once_with("s1", "plo_review", "Review required")


def _suspended_at(node: str) -> MagicMock:
    graph = MagicMock()
    graph.ainvoke = AsyncMock()
    graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(
            next=(node,),
            tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value="Review required")])],
        )
    )
    return graph


async def test_suspending_after_need_combination_records_need_analysis():
    """The regression itself: the gate after need_combination is reviewed on
    the Need analysis page, so that is the stage the session records."""
    repo = AsyncMock()
    with patch("curriculum_agent.api.routes.sessions.SessionRepository", return_value=repo):
        await _run_graph(_suspended_at("review_needs_node"), {}, {}, "s1")

    repo.set_suspended.assert_awaited_once_with("s1", "need_analysis", "Review required")


async def test_completed_run_is_not_recorded_as_suspended():
    graph = MagicMock()
    graph.ainvoke = AsyncMock()
    graph.aget_state = AsyncMock(return_value=SimpleNamespace(next=(), tasks=[]))

    repo = AsyncMock()
    with patch("curriculum_agent.api.routes.sessions.SessionRepository", return_value=repo):
        await _run_graph(graph, {}, {}, "s1")

    repo.set_status.assert_awaited_once_with("s1", "completed")
    repo.set_suspended.assert_not_awaited()
