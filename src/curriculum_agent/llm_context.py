"""Who a model call belongs to, carried by context rather than by argument.

The recorder in `llm._complete` reads `current_scope()`; the places where work
starts (the job body, the graph session runner, the synchronous designer routes
that call a model) wrap it in `llm_scope(...)`. A `ContextVar` is per task, so
two programs running in one process attribute their own calls, which a module
global could not do. A task spawned inside a scope copies it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMScope:
    program_id: str | None = None
    job_id: str | None = None
    session_id: str | None = None


_scope: ContextVar[LLMScope | None] = ContextVar("llm_scope", default=None)


def current_scope() -> LLMScope:
    """The scope active in this task; all-null outside any `llm_scope`."""
    return _scope.get() or LLMScope()


@contextmanager
def llm_scope(
    *,
    program_id: str | None = None,
    job_id: str | None = None,
    session_id: str | None = None,
) -> Iterator[LLMScope]:
    scope = LLMScope(program_id=program_id, job_id=job_id, session_id=session_id)
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)
