from __future__ import annotations

from curriculum_agent.smart_vocabulary import SmartFindingCode as C
from curriculum_agent.stages.smart_vote import (
    REPAIR_EXCLUDED,
    JudgeRun,
    first_batch_size,
    is_decided,
    repairable,
    vote,
    vote_threshold,
)


def _run(*failed: C, turns: int = 1) -> JudgeRun:
    return JudgeRun(
        failed=frozenset(failed),
        notes_th={code: f"note {code.value}" for code in failed},
        diagnosis_th="d",
        repair_hint_th="h",
        turns=turns,
    )


def test_thresholds() -> None:
    assert vote_threshold(5) == 3
    assert vote_threshold(1) == 1
    assert first_batch_size(5) == 3
    assert first_batch_size(1) == 1


def test_three_unanimous_passes_decided_with_two_pending() -> None:
    assert is_decided([_run(), _run(), _run()], 5)


def test_two_one_split_not_decided() -> None:
    runs = [_run(C.S_OBJECT), _run(C.S_OBJECT), _run()]
    assert not is_decided(runs, 5)


def test_three_runs_failing_s_object_decided() -> None:
    runs = [_run(C.S_OBJECT)] * 3
    assert is_decided(runs, 5)
    result = vote(runs, 5)
    assert result is not None
    assert result.failed == (C.S_OBJECT,)
    assert result.threshold == 3
    assert result.runs_requested == 5
    assert result.runs_used == 3


def test_failed_run_plus_two_successes_not_decided() -> None:
    assert not is_decided([None, _run(), _run()], 5)


def test_too_few_successes_vote_none() -> None:
    runs = [_run(), _run(), None, None, None]
    assert is_decided(runs, 5)
    assert vote(runs, 5) is None


def test_representative_most_majority_codes_then_fewest_extra_then_earliest() -> None:
    a = _run(C.S_OBJECT, C.M_ASSESSABLE)
    b = _run(C.S_OBJECT, C.M_ASSESSABLE, C.T_HORIZON)  # extra non-majority code
    c = _run(C.S_OBJECT, C.M_ASSESSABLE)
    d = _run(C.S_OBJECT)
    result = vote([a, b, c, d], 5)
    assert result is not None
    assert result.failed == (C.S_OBJECT, C.M_ASSESSABLE) or result.failed == (C.S_OBJECT,)
    # S_OBJECT f=4, M f=3 (a,b,c), T f=1 -> majority {S, M}
    assert result.failed == (C.S_OBJECT, C.M_ASSESSABLE)
    assert result.representative is a  # a ties c on both counts; earliest wins; b has extra


def test_failed_codes_follow_soft_verdict_order() -> None:
    runs = [_run(C.T_HORIZON, C.S_OBJECT)] * 3
    result = vote(runs, 5)
    assert result is not None
    assert result.failed == (C.S_OBJECT, C.T_HORIZON)


def test_repairable_drops_actor_and_scope_keeps_order() -> None:
    assert frozenset({C.A_ACTOR, C.A_SCOPE}) == REPAIR_EXCLUDED
    got = repairable([C.S_OBJECT, C.A_ACTOR, C.A_LEVEL, C.A_SCOPE, C.T_HORIZON])
    assert got == [C.S_OBJECT, C.A_LEVEL, C.T_HORIZON]
