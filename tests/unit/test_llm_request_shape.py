"""What actually leaves the process, observed below instructor.

Both defects this file pins were invisible from above: the loop's own tests
replace the model with a fake that never goes through instructor, so neither
the in-place schema append nor the missing reasoning budget could show up in
them. Here the real instructor client runs against an httpx transport that
records each request body and answers with a fixed completion — the network is
the only thing mocked.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import instructor
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from curriculum_agent import llm


class _Answer(BaseModel):
    value: str


def _recording_client(bodies: list[dict[str, Any]]) -> instructor.AsyncInstructor:
    def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"value": "ok"}'},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    raw = AsyncOpenAI(
        base_url="http://test.invalid/v1",
        api_key="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    return instructor.from_openai(raw, mode=instructor.Mode.JSON)


@pytest.fixture
def bodies(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    client = _recording_client(seen)
    monkeypatch.setattr(llm, "_get_client", lambda provider: client)
    return seen


async def test_a_reused_message_list_is_not_grown_by_the_call(
    bodies: list[dict[str, Any]],
) -> None:
    """instructor's JSON mode appends the response schema to the system message
    in place — its `kwargs.copy()` is shallow, so the dict it edits is ours.

    The SMART agent keeps one message list for the whole loop and calls once per
    turn, so turn N carried N copies of a ~1,650-token schema. Measured on a
    stored PLO: the same opening turn sent 5,773, then 7,423, then 9,073 prompt
    tokens. Every other caller builds a fresh list per call and never saw it.
    """
    messages = [
        {"role": "system", "content": "rubric"},
        {"role": "user", "content": "plo"},
    ]

    await llm._complete("openrouter", "m", _Answer, messages)
    await llm._complete("openrouter", "m", _Answer, messages)

    assert messages[0]["content"] == "rubric"
    first, second = (b["messages"][0]["content"] for b in bodies)
    assert first == second
    assert second.count("Parse the content and return a JSON object") == 1


async def test_a_reasoning_budget_reaches_an_openrouter_request(
    bodies: list[dict[str, Any]],
) -> None:
    """The model shares one max_tokens between hidden reasoning and the answer.

    On one stored PLO it spent all 4,096 on reasoning and returned no content at
    all, twice out of two, for a step whose answer is "call check_hard"; given
    16,000 it used 5,715. A reasoning budget is what leaves the answer room.
    """
    await llm._complete(
        "openrouter", "m", _Answer, [{"role": "user", "content": "x"}], reasoning_max_tokens=1024
    )

    assert bodies[0]["reasoning"] == {"max_tokens": 1024}


@pytest.mark.parametrize("provider", ["opentyphoon", "ollama"])
async def test_the_reasoning_budget_is_not_sent_where_it_means_nothing(
    bodies: list[dict[str, Any]], provider: str
) -> None:
    """`reasoning` is OpenRouter's request field. Another endpoint may reject an
    unknown field or ignore it; either way it is not a knob there, and moving the
    validation slot must not start failing its calls."""
    await llm._complete(
        provider, "m", _Answer, [{"role": "user", "content": "x"}], reasoning_max_tokens=1024
    )

    assert "reasoning" not in bodies[0]


async def test_no_budget_asked_for_sends_no_reasoning_field(bodies: list[dict[str, Any]]) -> None:
    """Every other slot's requests stay byte-for-byte what they were."""
    await llm._complete("openrouter", "m", _Answer, [{"role": "user", "content": "x"}])

    assert "reasoning" not in bodies[0]


async def test_ollama_still_gets_its_keep_alive(bodies: list[dict[str, Any]]) -> None:
    """The budget merges into the provider's own extra body rather than replacing it."""
    await llm._complete(
        "ollama", "m", _Answer, [{"role": "user", "content": "x"}], reasoning_max_tokens=1024
    )

    assert bodies[0]["keep_alive"] == -1


async def test_the_step_policy_does_not_retry_a_truncated_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """instructor retries every exception by default, a truncation included, so a
    runaway step spent the full step cap twice before the loop heard about it —
    141 seconds on stored OPT1's first turn. The loop's answer to a truncation is
    to bound reasoning, which a blind retry cannot do, so it must arrive at once."""
    from instructor.core.exceptions import IncompleteOutputException

    from curriculum_agent.stages.smart_agent import _step_retrying

    requests: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(1)
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": ""},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 4096, "total_tokens": 4097},
            },
        )

    raw = AsyncOpenAI(
        base_url="http://test.invalid/v1",
        api_key="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    client = instructor.from_openai(raw, mode=instructor.Mode.JSON)
    monkeypatch.setattr(llm, "_get_client", lambda provider: client)

    with pytest.raises(IncompleteOutputException):
        await llm._complete(
            "openrouter",
            "m",
            _Answer,
            [{"role": "user", "content": "x"}],
            max_retries=_step_retrying(),
        )
    assert len(requests) == 1
