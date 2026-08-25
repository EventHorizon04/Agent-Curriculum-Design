from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from curriculum_agent.graph import build_graph, discard_thread


async def test_discard_thread_asks_the_checkpointer_to_drop_the_thread() -> None:
    graph = MagicMock()
    graph.checkpointer.adelete_thread = AsyncMock()

    assert await discard_thread(graph, "cs:s1") is True
    graph.checkpointer.adelete_thread.assert_awaited_once_with("cs:s1")


async def test_discard_thread_reports_failure_instead_of_raising() -> None:
    """Every caller runs it after the deletion the user asked for has committed.
    Raising there would answer 500 for something that is already gone."""
    graph = MagicMock()
    graph.checkpointer.adelete_thread = AsyncMock(side_effect=RuntimeError("checkpointer down"))

    assert await discard_thread(graph, "cs:s1") is False


async def test_discard_thread_on_a_graph_with_no_checkpointer_is_a_no_op() -> None:
    """build_graph() defaults to no checkpointer — nothing was persisted, so
    there is nothing to drop and no error to report."""
    graph = build_graph()

    assert await discard_thread(graph, "cs:s1") is False
