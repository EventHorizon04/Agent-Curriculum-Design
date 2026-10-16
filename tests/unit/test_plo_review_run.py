from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.config import settings
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    PLOSetReview,
    ProgramMetadata,
    ReviewToolCall,
    SMARTCheck,
)
from curriculum_agent.stages import plo_review as pr
from curriculum_agent.stages.plo_review_agent import AgentOutcome, Redundancy, ReviewFinish
from curriculum_agent.stages.plo_review_facts import need_demands

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
_META = ProgramMetadata.model_validate(
    {
        "program_id": "p",
        "field": "การแปล",
        "degree_level": "bachelor",
        "duration_years": 4,
        "faculty": "ศิลปศาสตร์",
        "university": "Test",
    }
)
_NEED = Need(
    need_id="n1",
    program_id="p",
    statement_th="ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้",
    ksec_category=KSECCategory.S,
    bloom_level=BloomLevel.APPLY,
    member_skill_ids=["s1"],
    source_evidence_ids=["e1"],
    freq=1,
    demand_score=0.5,
)
_PLOS = [
    PLO(
        plo_id=pid,
        program_id="p",
        statement_th=f"แปลเอกสารธุรกิจ {pid}",
        bloom_level=BloomLevel.APPLY,
        action_verb_th="แปล",
        smart_check=_SMART,
        source_need_ids=["n1"],
        source_evidence_ids=["e1"],
        rationale_th="เหตุผล",
    )
    for pid in ("PLO1", "PLO2")
]
_FINISH = ReviewFinish(
    kind="finish",
    redundancies=[Redundancy(plo_ids=["PLO1", "PLO2"], reason_th="ซ้ำ", suggestion_th="รวม")],
    summary_th="สองข้อซ้ำกัน",
)


class _MemoryRepo:
    rows: dict[str, PLOSetReview] = {}

    async def get(self, program_id: str) -> PLOSetReview | None:
        return self.rows.get(program_id)

    async def upsert(self, review: PLOSetReview) -> None:
        self.rows[review.program_id] = review


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Undo the conftest kill switch for this module and fake every boundary."""
    _MemoryRepo.rows = {}
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    monkeypatch.setattr(pr, "PLOReviewRepository", _MemoryRepo)
    monkeypatch.setattr(
        pr, "ProgramRepository", lambda: AsyncMock(get=AsyncMock(return_value=_META))
    )
    monkeypatch.setattr(
        pr,
        "NeedRepository",
        lambda: AsyncMock(list_by_program=AsyncMock(return_value=[_NEED])),
    )
    agent_run = AsyncMock(
        return_value=AgentOutcome(_FINISH, None, [ReviewToolCall(tool="check_verbs", arg="PLO1")])
    )
    monkeypatch.setattr(pr, "run_review_agent", agent_run)
    return agent_run


def _changed() -> list[PLO]:
    return [_PLOS[0].model_copy(update={"statement_th": "ล่ามการเจรจาธุรกิจ"}), _PLOS[1]]


async def test_a_fresh_review_is_the_agents_answer_judged_and_stored(live: AsyncMock) -> None:
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "agent" and review.redundancies[0].plo_ids == ["PLO1", "PLO2"]
    assert review.tool_calls[0].tool == "check_verbs"
    assert review.plo_fingerprint == pr.plo_fingerprint(_PLOS, need_demands([_NEED]))
    assert _MemoryRepo.rows["p"] == review


async def test_the_agent_is_handed_the_dossier_and_only_the_unused_needs(live: AsyncMock) -> None:
    await pr.fresh_review("p", _PLOS)
    dossier, unused = live.await_args.args
    assert [i.plo_id for i in dossier.items] == ["PLO1", "PLO2"]
    assert dict(unused) == {}  # _NEED is cited by both PLOs


@pytest.mark.parametrize("reason", ["failed", "timeout"])
async def test_an_agent_failure_stores_the_code_facts(live: AsyncMock, reason: str) -> None:
    live.return_value = AgentOutcome(None, reason, [])
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "code_only" and review.code_only_reason == reason
    assert review.redundancies == [] and review.summary_th == ""
    assert _MemoryRepo.rows["p"] == review


async def test_an_answer_the_judge_empties_is_stored_as_code_only(live: AsyncMock) -> None:
    live.return_value = AgentOutcome(ReviewFinish(kind="finish"), None, [])
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "code_only" and review.code_only_reason == "failed"


async def test_the_switched_off_slot_never_runs_the_agent(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "")
    review = await pr.fresh_review("p", _PLOS)
    live.assert_not_awaited()
    assert review.reviewed_by == "code_only" and review.code_only_reason == "disabled"


async def test_an_unchanged_set_reuses_the_stored_review(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_runs", 1)
    first = await pr.review_plo_set("p", _PLOS)
    second = await pr.review_plo_set("p", _PLOS)
    assert first == second and live.await_count == 1


@pytest.mark.parametrize("reason", ["failed", "timeout"])
async def test_a_stored_code_only_failure_is_run_fresh_not_reused(
    live: AsyncMock, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_runs", 1)
    live.return_value = AgentOutcome(None, reason, [])
    first = await pr.review_plo_set("p", _PLOS)
    assert first is not None and first.code_only_reason == reason
    live.return_value = AgentOutcome(_FINISH, None, [])
    second = await pr.review_plo_set("p", _PLOS)
    assert second is not None and second.reviewed_by == "agent" and live.await_count == 2


async def test_a_stored_disabled_review_is_reused_while_the_slot_stays_off(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "")
    first = await pr.review_plo_set("p", _PLOS)
    second = await pr.review_plo_set("p", _PLOS)
    assert first == second and first is not None and first.code_only_reason == "disabled"
    live.assert_not_awaited()


async def test_a_stored_disabled_review_is_run_fresh_once_the_slot_is_on(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_runs", 1)
    monkeypatch.setattr(settings, "plo_review_provider", "")
    off = await pr.review_plo_set("p", _PLOS)
    assert off is not None and off.code_only_reason == "disabled"
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    on = await pr.review_plo_set("p", _PLOS)
    assert on is not None and on.reviewed_by == "agent" and live.await_count == 1


async def test_a_changed_set_is_reviewed_again(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_runs", 1)
    await pr.review_plo_set("p", _PLOS)
    await pr.review_plo_set("p", _changed())
    assert live.await_count == 2


async def test_a_storage_failure_raises_from_fresh_review(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MemoryRepo, "upsert", AsyncMock(side_effect=RuntimeError("db down")))
    with pytest.raises(RuntimeError):
        await pr.fresh_review("p", _PLOS)


async def test_review_plo_set_keeps_the_stored_review_when_the_new_one_fails_to_store(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = await pr.fresh_review("p", _PLOS)
    monkeypatch.setattr(_MemoryRepo, "upsert", AsyncMock(side_effect=RuntimeError("db down")))
    assert await pr.review_plo_set("p", _changed()) == old


async def test_review_plo_set_degrades_to_the_stored_review_while_one_is_in_flight(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_runs", 1)
    old = await pr.fresh_review("p", _PLOS)
    pr._REVIEW_IN_FLIGHT.add("p")
    try:
        result = await pr.review_plo_set("p", _changed())
    finally:
        pr._REVIEW_IN_FLIGHT.discard("p")
    assert result == old
    live.assert_awaited_once()


async def test_review_plo_set_returns_none_when_its_reads_fail(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MemoryRepo, "get", AsyncMock(side_effect=RuntimeError("db down")))
    assert await pr.review_plo_set("p", _PLOS) is None
    live.assert_not_awaited()


async def test_the_graph_node_keeps_going_when_the_needs_fail_to_load(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pr,
        "NeedRepository",
        lambda: AsyncMock(list_by_program=AsyncMock(side_effect=RuntimeError("db"))),
    )
    state = await pr.run({"program_id": "p", "plos": [p.model_dump(mode="json") for p in _PLOS]})
    assert state["plo_review"] is None and state["current_stage"] == "plo_review"


async def test_run_puts_the_review_on_the_state(live: AsyncMock) -> None:
    state = await pr.run({"program_id": "p", "plos": [p.model_dump(mode="json") for p in _PLOS]})
    assert state["plo_review"]["summary_th"] == "สองข้อซ้ำกัน"
    assert state["current_stage"] == "plo_review"


async def test_run_with_no_plos_leaves_no_review(live: AsyncMock) -> None:
    state = await pr.run({"program_id": "p", "plos": []})
    assert state["plo_review"] is None and state["current_stage"] == "plo_review"
    live.assert_not_awaited()


async def test_a_second_review_while_one_is_in_flight_is_refused(live: AsyncMock) -> None:
    pr._REVIEW_IN_FLIGHT.add("p")
    try:
        with pytest.raises(pr.ReviewAlreadyRunning):
            await pr.fresh_review("p", _PLOS)
    finally:
        pr._REVIEW_IN_FLIGHT.discard("p")


def _finish(*groups: list[str]) -> ReviewFinish:
    return ReviewFinish(
        kind="finish",
        redundancies=[Redundancy(plo_ids=g, reason_th="ซ้ำ", suggestion_th="รวม") for g in groups],
        summary_th="สรุป",
    )


async def test_three_runs_are_asked_for_and_voted_over(live: AsyncMock) -> None:
    review = await pr.fresh_review("p", _PLOS)
    assert live.await_count == 3
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 3, 2)
    assert review.redundancies[0].agreed_runs == 3


async def test_the_runs_are_concurrent(live: AsyncMock) -> None:
    started = 0
    all_started = asyncio.Event()

    async def blocking(dossier, unused):  # type: ignore[no-untyped-def]
        nonlocal started
        started += 1
        if started == 3:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1)
        return AgentOutcome(_FINISH, None, [])

    live.side_effect = blocking
    review = await pr.fresh_review("p", _PLOS)
    assert review.runs_succeeded == 3


async def test_two_successes_and_one_failure_vote_over_two(live: AsyncMock) -> None:
    live.side_effect = [
        AgentOutcome(_FINISH, None, []),
        AgentOutcome(None, "timeout", []),
        AgentOutcome(_FINISH, None, []),
    ]
    review = await pr.fresh_review("p", _PLOS)
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 2, 2)
    assert review.redundancies[0].agreed_runs == 2


async def test_one_success_is_stored_as_is_and_marked(live: AsyncMock) -> None:
    live.side_effect = [
        AgentOutcome(None, "failed", []),
        AgentOutcome(_finish(["PLO1", "PLO2"]), None, []),
        AgentOutcome(None, "timeout", []),
    ]
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "agent"
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 1, 1)
    assert review.redundancies[0].agreed_runs == 1


async def test_all_timeouts_store_timeout(live: AsyncMock) -> None:
    live.return_value = AgentOutcome(None, "timeout", [])
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "code_only" and review.code_only_reason == "timeout"
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 0, 1)


async def test_mixed_failures_store_failed(live: AsyncMock) -> None:
    live.side_effect = [
        AgentOutcome(None, "timeout", []),
        AgentOutcome(None, "failed", []),
        AgentOutcome(ReviewFinish(kind="finish"), None, []),  # judged empty: a failure
    ]
    review = await pr.fresh_review("p", _PLOS)
    assert review.reviewed_by == "code_only" and review.code_only_reason == "failed"
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (3, 0, 1)


async def test_an_unconfirmed_stored_review_is_run_fresh(live: AsyncMock) -> None:
    live.side_effect = [
        AgentOutcome(None, "failed", []),
        AgentOutcome(_finish(["PLO1", "PLO2"]), None, []),
        AgentOutcome(None, "timeout", []),
    ]
    first = await pr.review_plo_set("p", _PLOS)
    assert first is not None and (first.runs_requested, first.runs_succeeded) == (3, 1)
    live.side_effect = None
    live.return_value = AgentOutcome(_FINISH, None, [])
    second = await pr.review_plo_set("p", _PLOS)
    assert second is not None and second.runs_succeeded == 3 and live.await_count == 6


@pytest.mark.parametrize("succeeded", [2, 3])
async def test_a_confirmed_stored_review_is_reused(live: AsyncMock, succeeded: int) -> None:
    ok = AgentOutcome(_FINISH, None, [])
    live.side_effect = [ok] * succeeded + [AgentOutcome(None, "failed", [])] * (3 - succeeded)
    first = await pr.review_plo_set("p", _PLOS)
    assert first is not None and first.runs_succeeded == succeeded
    second = await pr.review_plo_set("p", _PLOS)
    assert second == first and live.await_count == 3


async def test_one_run_setting_is_todays_single_review(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_runs", 1)
    review = await pr.fresh_review("p", _PLOS)
    assert live.await_count == 1
    assert (review.runs_requested, review.runs_succeeded, review.agreement_threshold) == (1, 1, 1)
    assert review.tool_calls[0].tool == "check_verbs"
