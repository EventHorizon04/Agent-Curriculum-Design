from __future__ import annotations

import asyncio
from typing import Any

import pytest

from curriculum_agent.config import settings
from curriculum_agent.models import (
    BloomHistogram,
    BloomLevel,
    KSECCategory,
    KsecCoverage,
    Need,
    UnusedNeedFinding,
)
from curriculum_agent.prompts.plo_review import ReviewItem
from curriculum_agent.stages import plo_review_agent as agent
from curriculum_agent.stages.plo_review_facts import ReviewDossier

_ITEM = ReviewItem(
    plo_id="PLO1",
    is_optional=False,
    statement_th="วิเคราะห์ระบบงานเพื่อเสนอแนวทาง",
    action_verb_th="วิเคราะห์",
    bloom_level="analyze",
    current_ksec=("S",),
    need_statements_th=("ต้องการบัณฑิตที่วิเคราะห์ระบบงานได้",),
)
_UNUSED = UnusedNeedFinding(
    need_id="u1",
    statement_th="ต้องการบัณฑิตที่ล่ามได้",
    demand_score=0.4,
    ksec_category="S",
    stakeholder_types=["employer"],
    exclusion="lost_on_demand",
)
_DOSSIER = ReviewDossier(
    program_context=None,
    degree_level="bachelor",
    items=(_ITEM,),
    ksec_coverage=KsecCoverage(counts={"K": 0, "S": 1, "E": 0, "C": 0}),
    bloom_histogram=BloomHistogram(counts={"analyze": 1}, degree_level="bachelor"),
    core_count=1,
    unused_needs=(_UNUSED,),
)
_U1 = Need(
    need_id="u1",
    program_id="p",
    statement_th="ต้องการบัณฑิตที่ล่ามได้ในการประชุมธุรกิจ",
    rationale_th="ทักษะล่ามสามข้อเป็นงานเดียวกัน",
    ksec_category=KSECCategory.S,
    bloom_level=BloomLevel.APPLY,
    member_skill_ids=["s1", "s2"],
    source_evidence_ids=["e1"],
    stakeholder_coverage={"employer": 2},
    freq=2,
    demand_score=0.4,
)


def _tool(tool: str, arg: str) -> agent.ReviewStep:
    return agent.ReviewStep(
        reasoning_th="ตรวจ", action={"kind": "call_tool", "tool": tool, "arg": arg}
    )


def _finish(**kw: Any) -> agent.ReviewStep:
    return agent.ReviewStep(reasoning_th="สรุป", action={"kind": "finish", "summary_th": "ดี", **kw})


class _Script:
    """A fake model: answers each step from a list, recording what it was sent."""

    def __init__(self, steps: list[Any]) -> None:
        self.steps = list(steps)
        self.sent: list[list[dict[str, Any]]] = []
        self.kwargs: list[dict[str, Any]] = []

    async def __call__(
        self, response_model: type, messages: list[dict[str, Any]], **kw: Any
    ) -> Any:
        self.sent.append([dict(m) for m in messages])
        self.kwargs.append(kw)
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch):
    def install(steps: list[Any]) -> _Script:
        fake = _Script(steps)
        monkeypatch.setattr(agent, "complete_plo_review", fake)
        return fake

    return install


async def test_a_finish_on_the_first_step_is_the_answer(script) -> None:
    fake = script([_finish()])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert out.reason is None and out.finish is not None and out.tool_calls == []
    assert fake.kwargs[0]["reasoning_max_tokens"] == 1024


async def test_tool_results_go_back_as_the_next_user_turn(script) -> None:
    fake = script([_tool("check_verbs", "PLO1"), _finish()])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert [c.model_dump() for c in out.tool_calls] == [{"tool": "check_verbs", "arg": "PLO1"}]
    last = fake.sent[1][-1]
    assert last["role"] == "user" and "opens_with_declared_verb" in last["content"]


async def test_the_fifth_tool_call_is_refused(script) -> None:
    fake = script([_tool("bloom_lookup", f"v{i}") for i in range(5)] + [_finish()])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert len(out.tool_calls) == agent.MAX_TOOL_CALLS == 4
    assert "ปฏิเสธ" in fake.sent[5][-1]["content"]
    assert out.finish is not None


async def test_a_refused_argument_still_counts_toward_the_budget(script) -> None:
    fake = script([_tool("need_detail", "not-unused"), _tool("check_verbs", "PLO9"), _finish()])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert len(out.tool_calls) == 2
    assert "ปฏิเสธ" in fake.sent[1][-1]["content"] and "ปฏิเสธ" in fake.sent[2][-1]["content"]


async def test_need_detail_gives_the_explanation_and_counts_never_evidence(script) -> None:
    fake = script([_tool("need_detail", "u1"), _finish()])
    await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    content = fake.sent[1][-1]["content"]
    assert "ทักษะล่ามสามข้อเป็นงานเดียวกัน" in content and '"member_count": 2' in content
    assert "e1" not in content and "s1" not in content


async def test_six_steps_without_a_finish_is_a_failure(script) -> None:
    script([_tool("bloom_lookup", f"v{i}") for i in range(6)])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert out.finish is None and out.reason == "failed"


async def test_a_malformed_or_failing_step_is_a_failure(script) -> None:
    script([ValueError("schema")])
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert out.finish is None and out.reason == "failed"


async def test_the_run_timeout_is_reported_as_timeout(script, monkeypatch) -> None:
    monkeypatch.setattr(settings, "plo_review_timeout_seconds", 0.01)

    async def slow(*_a: Any, **_k: Any) -> Any:
        await asyncio.sleep(1)

    monkeypatch.setattr(agent, "complete_plo_review", slow)
    out = await agent.run_review_agent(_DOSSIER, {"u1": _U1})
    assert out.finish is None and out.reason == "timeout"


def test_check_verbs_reports_the_opening_and_the_declared_verbs() -> None:
    ok, payload = agent.run_review_tool(_DOSSIER, {}, agent.ReviewToolName.CHECK_VERBS, "PLO1")
    assert ok and payload["opens_with_declared_verb"] is True
    assert payload["too_many_verbs"] is False
    assert "analyze" in payload["levels"]["วิเคราะห์"]


def test_bloom_lookup_answers_an_unknown_verb_without_refusing() -> None:
    ok, payload = agent.run_review_tool(_DOSSIER, {}, agent.ReviewToolName.BLOOM_LOOKUP, "ฟฟฟ")
    assert ok and payload == {"verb_th": "ฟฟฟ", "recognized": False, "levels": []}
