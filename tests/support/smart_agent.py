"""Shared stand-ins for the SMART gate.

Fifteen call sites across eight files patched the soft judge, each spelling out
its own three-line closure — and nine of them passed `relevant_alignment_ok`,
a field that has not existed since it was renamed `relevant_needs_ok`. Pydantic
swallowed it (`extra="ignore"`), so those tests had been asserting against
plain defaults for months and nothing said so.

Two helpers, one for each idiom already in the suite: a context manager for the
`with patch.object(...)` sites and a monkeypatch form for the rest. Both reach
the gate through the same place, so when the soft judge is replaced by the
validation agent this file changes and the fifteen call sites do not.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from curriculum_agent.stages import plo_synthesis as ps


def soft_judge_ok() -> Any:
    """A verdict with every soft criterion true — what a test uses when it only
    needs the gate to get out of the way."""
    return ps._SmartSoftJudge()


def _judge_mock(judge: Any | None) -> AsyncMock:
    return AsyncMock(return_value=judge if judge is not None else soft_judge_ok())


def patch_soft_judge(judge: Any | None = None) -> Any:
    """Context-manager form: `with patch_soft_judge():`."""
    return patch.object(ps, "complete_light", _judge_mock(judge))


def set_soft_judge(monkeypatch: Any, judge: Any | None = None) -> AsyncMock:
    """monkeypatch form, for tests that patch and then call `run()` at the same
    indent. Returns the mock so a test can assert on its call count."""
    mock = _judge_mock(judge)
    monkeypatch.setattr(ps, "complete_light", mock)
    return mock
