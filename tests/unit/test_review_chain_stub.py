"""conftest stubs the review chain after `POST /plos/run` unless a test opts in.

The chain's `_start_review_job` reads the stored PLOs through the module-level
`_repo`, so a synthesis-route test that did not patch it made a real asyncpg
connect and left an unawaited `Connection._cancel` behind.
"""

from __future__ import annotations

import pytest

from curriculum_agent.api.routes import plos as plos_route


async def test_the_review_chain_is_a_recorder_by_default(
    review_chain_calls: list[tuple[str, bool]],
) -> None:
    await plos_route._start_review_job("cs-test", or_409=False)
    assert review_chain_calls == [("cs-test", False)]


@pytest.mark.review_chain
def test_a_test_marked_review_chain_gets_the_real_function(
    review_chain_calls: list[tuple[str, bool]],
) -> None:
    assert plos_route._start_review_job.__qualname__ == "_start_review_job"
    assert plos_route._start_review_job.__module__ == plos_route.__name__
    assert review_chain_calls == []
