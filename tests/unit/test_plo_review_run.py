from __future__ import annotations

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
    SMARTCheck,
)
from curriculum_agent.stages import plo_review as pr

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
_ANSWER = pr.ReviewAnswer(
    redundancies=[pr._Redundancy(plo_ids=["PLO1", "PLO2"], reason_th="ซ้ำ", suggestion_th="รวม")],
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
    call = AsyncMock(return_value=_ANSWER)
    monkeypatch.setattr(pr, "complete_plo_review", call)
    return call


async def test_a_fresh_review_is_judged_and_stored(live: AsyncMock) -> None:
    review = await pr.fresh_review("p", _PLOS)
    assert review is not None
    assert review.redundancies[0].plo_ids == ["PLO1", "PLO2"]
    assert review.plo_fingerprint == pr.plo_fingerprint(_PLOS, {_NEED.need_id: _NEED.demand_score})
    assert _MemoryRepo.rows["p"] == review
    live.assert_awaited_once()


async def test_the_prompt_carries_every_plo_and_its_needs(live: AsyncMock) -> None:
    await pr.fresh_review("p", _PLOS)
    messages = live.await_args.args[1]
    user = messages[1]["content"]
    assert "[PLO1]" in user and "[PLO2]" in user
    assert "ต้องการบัณฑิตที่แปลเอกสารธุรกิจได้" in user
    assert live.await_args.kwargs["temperature"] == 0
    assert live.await_args.kwargs["max_tokens"] == 8192
    assert live.await_args.kwargs["reasoning_max_tokens"] == 1024


async def test_an_unchanged_set_reuses_the_stored_review(live: AsyncMock) -> None:
    first = await pr.review_plo_set("p", _PLOS)
    again = await pr.review_plo_set("p", _PLOS)
    assert again == first
    live.assert_awaited_once()


async def test_a_changed_set_is_reviewed_again(live: AsyncMock) -> None:
    await pr.review_plo_set("p", _PLOS)
    changed = [_PLOS[0].model_copy(update={"statement_th": "ล่ามการเจรจาธุรกิจ"}), _PLOS[1]]
    await pr.review_plo_set("p", changed)
    assert live.await_count == 2


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("provider down"), TimeoutError()],
)
async def test_a_failed_call_stores_nothing_and_returns_the_stored_review(
    live: AsyncMock, failure: BaseException
) -> None:
    old = await pr.fresh_review("p", _PLOS)
    live.side_effect = failure
    changed = [_PLOS[0].model_copy(update={"statement_th": "ล่ามการเจรจาธุรกิจ"}), _PLOS[1]]
    assert await pr.fresh_review("p", changed) is None
    assert await pr.review_plo_set("p", changed) == old
    assert _MemoryRepo.rows["p"] == old


async def test_an_answer_the_judge_empties_is_a_failure(live: AsyncMock) -> None:
    live.return_value = pr.ReviewAnswer(
        redundancies=[pr._Redundancy(plo_ids=["PLO9", "PLO8"], reason_th="ไม่มีจริง")]
    )
    assert await pr.fresh_review("p", _PLOS) is None
    assert "p" not in _MemoryRepo.rows


async def test_the_switched_off_slot_never_calls(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "")
    assert await pr.fresh_review("p", _PLOS) is None
    live.assert_not_awaited()


async def test_a_second_review_while_one_is_in_flight_is_refused(live: AsyncMock) -> None:
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()

    async def hang(*_a: object, **_k: object) -> pr.ReviewAnswer:
        entered.set()
        await release.wait()
        return _ANSWER

    live.side_effect = hang
    first = asyncio.create_task(pr.fresh_review("p", _PLOS))
    await entered.wait()
    try:
        with pytest.raises(pr.ReviewAlreadyRunning):
            await asyncio.wait_for(pr.fresh_review("p", _PLOS), timeout=2)
    finally:
        release.set()
        await first


async def test_run_puts_the_review_on_the_state(live: AsyncMock) -> None:
    state = await pr.run({"program_id": "p", "plos": [p.model_dump(mode="json") for p in _PLOS]})
    assert state["plo_review"]["summary_th"] == "สองข้อซ้ำกัน"


async def test_run_with_no_plos_leaves_no_review(live: AsyncMock) -> None:
    state = await pr.run({"program_id": "p", "plos": []})
    assert state["plo_review"] is None
    live.assert_not_awaited()


# ---- Fix round 1: every boundary the review touches must fail safe ----


async def test_a_storage_failure_returns_none_and_falls_back_to_the_stored_review(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = await pr.fresh_review("p", _PLOS)
    monkeypatch.setattr(_MemoryRepo, "upsert", AsyncMock(side_effect=RuntimeError("db down")))
    changed = [_PLOS[0].model_copy(update={"statement_th": "ล่ามการเจรจาธุรกิจ"}), _PLOS[1]]
    assert await pr.fresh_review("p", changed) is None
    assert await pr.review_plo_set("p", changed) == old


async def test_the_stored_review_read_failing_does_not_stop_a_fresh_one(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MemoryRepo, "get", AsyncMock(side_effect=RuntimeError("db down")))
    review = await pr.review_plo_set("p", _PLOS)
    assert review is not None
    assert review.summary_th == "สองข้อซ้ำกัน"
    live.assert_awaited_once()


async def test_a_needs_read_failure_means_no_call_is_made(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pr,
        "NeedRepository",
        lambda: AsyncMock(list_by_program=AsyncMock(side_effect=RuntimeError("db down"))),
    )
    assert await pr.fresh_review("p", _PLOS) is None
    live.assert_not_awaited()


async def test_review_plo_set_degrades_to_the_stored_review_while_one_is_in_flight(
    live: AsyncMock,
) -> None:
    """A second caller (e.g. GET /review's implicit refresh path, or a racing
    report/run) must not pile a second call onto a review already running for
    this program — it gets the stored answer instead, and the model is never
    asked twice."""
    old = await pr.fresh_review("p", _PLOS)
    changed = [_PLOS[0].model_copy(update={"statement_th": "ล่ามการเจรจาธุรกิจ"}), _PLOS[1]]
    pr._REVIEW_IN_FLIGHT.add("p")
    try:
        result = await pr.review_plo_set("p", changed)
    finally:
        pr._REVIEW_IN_FLIGHT.discard("p")
    assert result == old
    live.assert_awaited_once()


async def test_run_with_a_storage_failure_leaves_the_state_unset(
    live: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MemoryRepo, "upsert", AsyncMock(side_effect=RuntimeError("db down")))
    state = await pr.run({"program_id": "p", "plos": [p.model_dump(mode="json") for p in _PLOS]})
    assert state["plo_review"] is None
