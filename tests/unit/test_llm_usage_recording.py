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
