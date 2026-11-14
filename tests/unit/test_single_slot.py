"""The single_agent slot: settings, resolution and the prompt-token sink."""

from __future__ import annotations

import json
from typing import Any

import httpx
import instructor
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from curriculum_agent import llm
from curriculum_agent.config import SLOTS, Settings
from curriculum_agent.models import LLMUsage


class _Answer(BaseModel):
    value: str


_MSG = [{"role": "user", "content": "x"}]


def _completion(content: str, prompt_tokens: int) -> dict[str, Any]:
    return {
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
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 3,
            "total_tokens": prompt_tokens + 3,
        },
    }


def _use_script(monkeypatch: pytest.MonkeyPatch, bodies: list[dict[str, Any]]) -> None:
    calls = {"n": 0}

    async def handle(request: httpx.Request) -> httpx.Response:
        json.loads(request.content)
        body = bodies[min(calls["n"], len(bodies) - 1)]
        calls["n"] += 1
        return httpx.Response(200, json=body)

    raw = AsyncOpenAI(
        base_url="http://test.invalid/v1",
        api_key="test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    client = instructor.from_openai(raw, mode=instructor.Mode.JSON)
    monkeypatch.setattr(llm, "_get_client", lambda provider: client)


def test_single_agent_slot_is_declared_last_and_not_disableable() -> None:
    spec = SLOTS[-1]
    assert spec.name == "single_agent"
    assert not spec.disableable


def test_single_agent_slot_follows_the_pipeline_pair() -> None:
    s = Settings(
        _env_file=None, pipeline_provider="openrouter", pipeline_model="z-ai/glm-5.3-flash"
    )
    assert (s.single_agent_provider, s.single_agent_model) == ("openrouter", "z-ai/glm-5.3-flash")


def test_single_agent_budgets_have_their_plan_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.single_agent_max_turns == 80
    assert s.single_agent_timeout_seconds == 1800
    assert s.single_agent_evidence_part_chars == 6000
    assert s.single_agent_context_budget_ratio == 0.7
    assert s.single_agent_context_window_tokens == 128000


async def test_usage_sink_receives_prompt_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_script(monkeypatch, [_completion('{"value": "ok"}', 321)])
    sink: list[int] = []
    result = await llm.complete_single_agent(_Answer, _MSG, usage_sink=sink)
    assert result.value == "ok"
    assert sink == [321]


async def test_usage_sink_holds_the_attempt_that_produced_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_script(
        monkeypatch,
        [_completion('{"wrong": 1}', 100), _completion('{"value": "ok"}', 150)],
    )
    sink: list[int] = []
    await llm.complete_single_agent(_Answer, _MSG, usage_sink=sink, max_retries=2)
    assert sink == [150]


async def test_usage_is_recorded_under_the_single_agent_slot(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[LLMUsage]
) -> None:
    _use_script(monkeypatch, [_completion('{"value": "ok"}', 7)])
    await llm.complete_single_agent(_Answer, _MSG)
    [row] = usage_rows
    assert row.slot == "single_agent"
