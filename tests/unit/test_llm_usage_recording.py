"""Token accounting below instructor: one row per provider response (phase 5).

The real instructor client runs against an httpx transport that answers from a
script, so the retry path and the hooks are the real ones. The repository is the
in-memory one conftest installs (`usage_rows`); no database is reached.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import instructor
import pytest
from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel

from curriculum_agent import llm
from curriculum_agent.api import jobs as jobs_mod
from curriculum_agent.llm_context import current_scope, llm_scope
from curriculum_agent.models import LLMUsage


class _Answer(BaseModel):
    value: str


_GOOD = '{"value": "ok"}'
_BAD = '{"wrong": 1}'
_MSG = [{"role": "user", "content": "x"}]


def _completion(content: str, usage: dict[str, Any] | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _client(
    script: Callable[[int], dict[str, Any]], delay: float = 0.0
) -> instructor.AsyncInstructor:
    calls = {"n": 0}

    async def handle(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        json.loads(request.content)
        if delay:
            await asyncio.sleep(delay)
        return httpx.Response(200, json=script(calls["n"]))

    raw = AsyncOpenAI(
        base_url="http://test.invalid/v1",
        api_key="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    return instructor.from_openai(raw, mode=instructor.Mode.JSON)


def _use(monkeypatch: pytest.MonkeyPatch, client: instructor.AsyncInstructor) -> None:
    monkeypatch.setattr(llm, "_get_client", lambda provider: client)


_USAGE = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


async def test_a_single_response_is_one_row_with_its_tokens(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE)))

    result = await llm._complete("openrouter", "glm", _Answer, _MSG, slot="clustering")

    assert result.value == "ok"
    [row] = usage_rows
    assert (row.slot, row.provider, row.model) == ("clustering", "openrouter", "glm")
    assert (row.prompt_tokens, row.completion_tokens, row.ok) == (11, 7, True)
    assert row.reasoning_tokens is None
    assert (row.program_id, row.job_id, row.session_id) == (None, None, None)


async def test_an_instructor_retry_records_both_responses_the_first_failed(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    """Review focus 1: the first response fails validation, instructor asks again,
    the second passes. Two rows, both with tokens, the first `ok=False`."""
    usages = {
        1: {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        2: {"prompt_tokens": 150, "completion_tokens": 9, "total_tokens": 159},
    }
    _use(
        monkeypatch,
        _client(lambda n: _completion(_BAD if n == 1 else _GOOD, usages[n])),
    )

    result = await llm._complete("openrouter", "m", _Answer, _MSG, slot="extraction", max_retries=2)

    assert result.value == "ok"
    assert [(r.ok, r.prompt_tokens, r.completion_tokens) for r in usage_rows] == [
        (False, 100, 20),
        (True, 150, 9),
    ]


async def test_a_call_that_exhausts_its_retries_still_records_every_response(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    _use(monkeypatch, _client(lambda n: _completion(_BAD, _USAGE)))

    with pytest.raises(Exception):  # noqa: B017, PT011 - instructor's retry exception
        await llm._complete("openrouter", "m", _Answer, _MSG, slot="extraction", max_retries=2)

    assert [r.ok for r in usage_rows] == [False, False]


async def test_reasoning_tokens_are_read_when_the_endpoint_reports_them(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    usage = {**_USAGE, "completion_tokens_details": {"reasoning_tokens": 5}}
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, usage)))

    await llm._complete("openrouter", "m", _Answer, _MSG, slot="validation")

    assert usage_rows[0].reasoning_tokens == 5


async def test_a_response_without_usage_records_zeros_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    """Review focus 4: some endpoints send no `usage`, or no reasoning detail."""
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, None)))

    result = await llm._complete("openrouter", "m", _Answer, _MSG, slot="plo_review")

    assert result.value == "ok"
    [row] = usage_rows
    assert (row.prompt_tokens, row.completion_tokens, row.reasoning_tokens) == (0, 0, None)


class _Broken:
    async def add(self, row: LLMUsage) -> None:
        raise RuntimeError("database is down")


async def test_a_failing_insert_leaves_the_result_and_logs_one_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review focus 2."""
    monkeypatch.setattr(llm, "LLMUsageRepository", _Broken)
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE)))
    warnings: list[str] = []
    sink = logger.add(lambda m: warnings.append(str(m)), level="WARNING")
    try:
        result = await llm._complete("openrouter", "m", _Answer, _MSG, slot="clustering")
    finally:
        logger.remove(sink)

    assert result.value == "ok"
    assert len(warnings) == 1
    assert "database is down" in warnings[0]


async def test_an_integrity_error_from_a_deleted_program_is_swallowed_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`program_id` is a foreign key: a program deleted mid-run makes the insert
    raise an integrity error, which must not fail the model call."""
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415

    class _Gone:
        async def add(self, row: LLMUsage) -> None:
            raise IntegrityError("insert", {}, Exception("fk violation"))

    monkeypatch.setattr(llm, "LLMUsageRepository", _Gone)
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE)))

    with llm_scope(program_id="deleted"):
        result = await llm._complete("openrouter", "m", _Answer, _MSG, slot="clustering")

    assert result.value == "ok"


async def test_concurrent_scopes_attribute_to_their_own_program(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    """Review focus 3: two programs in one process, one cached client, calls
    interleaved by the transport's delay. Each row carries its own program."""
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE), delay=0.02))

    async def call(program_id: str, job_id: str) -> None:
        with llm_scope(program_id=program_id, job_id=job_id):
            await llm._complete("openrouter", "m", _Answer, _MSG, slot="clustering")
            await llm._complete("openrouter", "m", _Answer, _MSG, slot="clustering")

    await asyncio.gather(call("p1", "j1"), call("p2", "j2"))

    assert len(usage_rows) == 4
    pairs = {(r.program_id, r.job_id) for r in usage_rows}
    assert pairs == {("p1", "j1"), ("p2", "j2")}
    assert sorted(r.program_id or "" for r in usage_rows) == ["p1", "p1", "p2", "p2"]


async def test_the_scope_is_gone_once_the_block_ends() -> None:
    with llm_scope(program_id="p1", session_id="s1"):
        assert current_scope().session_id == "s1"
    assert current_scope().program_id is None


async def test_a_job_body_runs_inside_its_programs_scope(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    """The scope is entered inside `_run`, the spawned task, not around the
    `start_job` call that spawns it."""
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE), delay=0.01))

    async def work() -> _Answer:
        return await llm._complete("openrouter", "m", _Answer, _MSG, slot="need_combination")

    await asyncio.gather(
        jobs_mod._run("p1", "job-a", "need_combination", work),
        jobs_mod._run("p2", "job-b", "need_combination", work),
    )

    assert {(r.program_id, r.job_id) for r in usage_rows} == {("p1", "job-a"), ("p2", "job-b")}


async def test_hooks_are_installed_once_per_client(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    """The client is a cached singleton; a second call must not double its rows."""
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE)))

    await llm._complete("openrouter", "m", _Answer, _MSG, slot="clustering")
    await llm._complete("openrouter", "m", _Answer, _MSG, slot="clustering")

    assert len(usage_rows) == 2


async def test_a_truncated_response_that_is_retried_is_recorded_failed(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    """finish_reason=length raises IncompleteOutputException, which instructor
    retries through `completion:error`, not `parse:error`."""

    def script(n: int) -> dict[str, Any]:
        body = _completion("" if n == 1 else _GOOD, _USAGE)
        if n == 1:
            body["choices"][0]["finish_reason"] = "length"
        return body

    _use(monkeypatch, _client(script))

    result = await llm._complete("openrouter", "m", _Answer, _MSG, slot="validation", max_retries=2)

    assert result.value == "ok"
    assert [r.ok for r in usage_rows] == [False, True]


async def test_latency_is_measured_per_response(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE), delay=0.05))

    await llm._complete("openrouter", "m", _Answer, _MSG, slot="clustering")

    assert usage_rows[0].latency_ms >= 40


async def test_a_parse_error_marks_only_its_own_calls_attempt(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    """Two interleaved calls on one client; only the first call's first response
    is invalid. Rows are told apart by program."""
    seen: dict[str, int] = {}

    async def handle(request: httpx.Request) -> httpx.Response:
        text = json.loads(request.content)["messages"][-1]["content"]
        seen[text] = seen.get(text, 0) + 1
        await asyncio.sleep(0.02)
        bad = text == "bad" and seen[text] == 1
        return httpx.Response(200, json=_completion(_BAD if bad else _GOOD, _USAGE))

    raw = AsyncOpenAI(
        base_url="http://test.invalid/v1",
        api_key="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    _use(monkeypatch, instructor.from_openai(raw, mode=instructor.Mode.JSON))

    async def call(program_id: str, text: str) -> None:
        with llm_scope(program_id=program_id):
            await llm._complete(
                "openrouter",
                "m",
                _Answer,
                [{"role": "user", "content": text}],
                slot="clustering",
                max_retries=2,
            )

    await asyncio.gather(call("p-bad", "bad"), call("p-good", "good"))

    by_program = {p: [r.ok for r in usage_rows if r.program_id == p] for p in ("p-bad", "p-good")}
    assert by_program == {"p-bad": [False, True], "p-good": [True]}


# ------------- scope wiring on the other entry points (review M5) -------------


async def test_a_graph_session_node_is_attributed_to_its_program_and_session(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    """`_run_graph` enters the scope and the graph runs its nodes in tasks it creates
    itself. A task copies the context it is created in, so a call made inside such a
    node must still carry program and session (and no job)."""
    from types import SimpleNamespace  # noqa: PLC0415
    from unittest.mock import AsyncMock  # noqa: PLC0415

    from curriculum_agent.api.routes import sessions as sessions_route  # noqa: PLC0415

    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE)))
    monkeypatch.setattr(sessions_route, "SessionRepository", lambda: AsyncMock())

    async def node() -> None:
        await llm._complete("openrouter", "m", _Answer, _MSG, slot="plo_synthesis")

    class _Graph:
        async def ainvoke(self, input_: Any, config: Any) -> None:
            await asyncio.create_task(node())  # how LangGraph runs a node

        async def aget_state(self, config: Any) -> Any:
            return SimpleNamespace(next=(), tasks=())

    await sessions_route._run_graph(_Graph(), {}, {}, "sess-1", "prog-1")  # type: ignore[arg-type]

    [row] = usage_rows
    assert (row.program_id, row.session_id, row.job_id) == ("prog-1", "sess-1", None)
    assert current_scope().program_id is None


def test_from_needs_attributes_its_model_call_to_the_program(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    from unittest.mock import AsyncMock  # noqa: PLC0415

    from fastapi.testclient import TestClient  # noqa: PLC0415

    from curriculum_agent.api.main import app  # noqa: PLC0415
    from curriculum_agent.api.routes import plos as plos_route  # noqa: PLC0415
    from tests.unit.test_api_plos import _plo, _program  # noqa: PLC0415

    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE)))
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))

    async def redraft(*args: Any, **kwargs: Any) -> tuple[Any, int]:
        await llm._complete("openrouter", "m", _Answer, _MSG, slot="plo_synthesis")
        return _plo("PLO1", ["N1", "N2"]), 0

    monkeypatch.setattr(plos_route, "redraft_from_needs", redraft)

    response = TestClient(app).post(
        "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]}
    )

    assert response.status_code == 200, response.text
    [row] = usage_rows
    assert (row.program_id, row.job_id, row.session_id) == ("cs-test", None, None)


def test_manual_need_merge_attributes_its_model_call_to_the_program(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage], jobs_store: Any
) -> None:
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from curriculum_agent.api.main import app  # noqa: PLC0415
    from tests.unit import test_need_manual_merge as t  # noqa: PLC0415

    t._install(monkeypatch, t._pool())
    _use(monkeypatch, _client(lambda n: _completion(_GOOD, _USAGE)))

    async def write_merged(*args: Any, **kwargs: Any) -> Any:
        await llm._complete("openrouter", "m", _Answer, _MSG, slot="need_combination")
        return t._need("M", merged_by="designer", merged_from=["A", "B"])

    monkeypatch.setattr(t.nm, "_write_merged", write_merged)

    response = TestClient(app).post("/programs/p/needs/merge", json={"need_ids": ["A", "B"]})

    assert response.status_code == 200, response.text
    [row] = usage_rows
    assert (row.program_id, row.job_id, row.session_id) == ("p", None, None)
