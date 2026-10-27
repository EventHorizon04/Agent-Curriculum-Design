"""Extraction runs its LLM calls concurrently, under a bounded fan-out.

One call per evidence item, awaited one after another, is fine against a local
model (~10s each) and fatal against a hosted one: measured at ~90s per call on
OpenRouter, fourteen evidence items need ~1259s and the stage sits behind
`asyncio.wait_for(..., timeout=300)` in `api/routes/needs.py`. It timed out
around the third item. These tests pin the fan-out and the bound on it.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.stages import skill_extraction as se


def _evidence(n: int) -> dict[str, Any]:
    return {
        "evidence_id": f"E{n}",
        "program_id": "cs-test",
        "stakeholder_type": "employer",
        "source_name": "ประกาศรับสมัครงาน",
        "raw_text_th": f"ผู้สมัครต้องวิเคราะห์ข้อมูลขนาดใหญ่ลำดับที่ {n} เพื่อสนับสนุนการตัดสินใจได้",
        "classification": "requirement",
    }


def _response(n: int) -> se._ExtractedSkillsResponse:
    return se._ExtractedSkillsResponse(
        skills=[
            se._SkillItem(
                skill_name_th=f"วิเคราะห์ข้อมูลลำดับที่ {n}",
                skill_name_en=f"Analysis {n}",
                ksec_category="S",
                bloom_level="analyze",
                evidence_span_th=f"วิเคราะห์ข้อมูลขนาดใหญ่ลำดับที่ {n}",
                confidence=0.9,
            )
        ]
    )


@pytest.fixture
def _stub_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(se.LLMCacheRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(se.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(se.SkillRepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(se.SkillGroupRepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(se.SkillRepository, "bulk_insert", AsyncMock())


class _ConcurrencyTracker:
    """Records how many extraction calls are in flight at once."""

    def __init__(self) -> None:
        self.live = 0
        self.peak = 0
        self.calls = 0

    async def __call__(self, response_model: Any, messages: list[dict[str, Any]]) -> Any:
        self.calls += 1
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            # Yield twice so every coroutine that has started gets to overlap
            # before any of them finishes — a single sleep(0) can be resumed in
            # lockstep and would understate the peak.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            n = int(messages[-1]["content"].split("ลำดับที่ ")[1].split(" ")[0])
            return _response(n)
        finally:
            self.live -= 1


async def test_extraction_calls_overlap(monkeypatch: pytest.MonkeyPatch, _stub_repos: None) -> None:
    tracker = _ConcurrencyTracker()
    monkeypatch.setattr(se, "complete_extraction", tracker)

    await se.run(
        {
            "program_id": "cs-test",
            "classified_evidence": [_evidence(n) for n in range(1, 9)],
            "metadata": {"field": "วิทยาการคอมพิวเตอร์"},
        }
    )

    assert tracker.calls == 8
    assert tracker.peak > 1, "extraction still awaits one evidence item at a time"


async def test_fan_out_respects_the_configured_ceiling(
    monkeypatch: pytest.MonkeyPatch, _stub_repos: None
) -> None:
    """Unbounded gather over a large corpus would open one connection per item
    and earn a 429 from any hosted provider."""
    tracker = _ConcurrencyTracker()
    monkeypatch.setattr(se, "complete_extraction", tracker)
    monkeypatch.setattr(se.settings, "llm_max_concurrency", 3)

    await se.run(
        {
            "program_id": "cs-test",
            "classified_evidence": [_evidence(n) for n in range(1, 13)],
            "metadata": {"field": "วิทยาการคอมพิวเตอร์"},
        }
    )

    assert tracker.calls == 12
    assert tracker.peak <= 3, f"fan-out reached {tracker.peak}, ceiling is 3"


async def test_results_keep_evidence_order(
    monkeypatch: pytest.MonkeyPatch, _stub_repos: None
) -> None:
    """Concurrency must not reorder the output: skill rows feed frequency counts
    and ids downstream, and a run that shuffles them is not reproducible."""
    tracker = _ConcurrencyTracker()
    monkeypatch.setattr(se, "complete_extraction", tracker)

    state = await se.run(
        {
            "program_id": "cs-test",
            "classified_evidence": [_evidence(n) for n in range(1, 7)],
            "metadata": {"field": "วิทยาการคอมพิวเตอร์"},
        }
    )

    assert [s["source_evidence_id"] for s in state["extracted_skills"]] == [
        f"E{n}" for n in range(1, 7)
    ]


async def test_one_failing_item_does_not_sink_the_others(
    monkeypatch: pytest.MonkeyPatch, _stub_repos: None
) -> None:
    """gather(return_exceptions=False) would abort the whole stage on the first
    provider hiccup. Each item's failure has to stay its own."""

    async def flaky(response_model: Any, messages: list[dict[str, Any]]) -> Any:
        n = int(messages[-1]["content"].split("ลำดับที่ ")[1].split(" ")[0])
        if n == 2:
            raise RuntimeError("provider said no")
        return _response(n)

    monkeypatch.setattr(se, "complete_extraction", flaky)

    state = await se.run(
        {
            "program_id": "cs-test",
            "classified_evidence": [_evidence(n) for n in range(1, 5)],
            "metadata": {"field": "วิทยาการคอมพิวเตอร์"},
        }
    )

    assert [s["source_evidence_id"] for s in state["extracted_skills"]] == ["E1", "E3", "E4"]


async def test_run_drops_stale_skill_groups(
    monkeypatch: pytest.MonkeyPatch, _stub_repos: None
) -> None:
    """Groups point at skill ids that run() deletes. They go first, before any
    skill row is touched, so a failed insert cannot leave groups pointing at
    deleted skills and a failed grouping leaves Agent 2 refusing."""
    monkeypatch.setattr(se, "complete_extraction", _ConcurrencyTracker())
    order: list[str] = []

    def recording(name: str, result: int) -> AsyncMock:
        async def call(*_: Any) -> int:
            order.append(name)
            return result

        return AsyncMock(side_effect=call)

    drop = recording("drop_groups", 3)
    monkeypatch.setattr(se.SkillGroupRepository, "delete_by_program", drop)
    monkeypatch.setattr(se.SkillRepository, "delete_by_program", recording("delete_skills", 0))
    monkeypatch.setattr(se.SkillRepository, "bulk_insert", recording("insert_skills", 0))

    await se.run(
        {
            "program_id": "cs-test",
            "classified_evidence": [_evidence(1)],
            "metadata": {"field": "วิทยาการคอมพิวเตอร์"},
        }
    )

    drop.assert_awaited_once_with("cs-test")
    assert order == ["drop_groups", "delete_skills", "insert_skills"]
