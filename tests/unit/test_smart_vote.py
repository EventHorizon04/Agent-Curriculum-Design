from __future__ import annotations

from curriculum_agent.smart_vocabulary import SmartFindingCode as C
from curriculum_agent.stages.smart_vote import (
    REPAIR_EXCLUDED,
    JudgeRun,
    can_still_decide,
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


def test_can_still_decide_failed_run_means_the_rest_must_start() -> None:
    # requested 5, t 3: the batch finished with one None and two agreeing runs,
    # so 2 successes + 2 unrequested can still reach 3 and the rest must start.
    assert can_still_decide([None, _run(), _run()], 0, 5) is False
    # Conservative: with two still pending a None cannot yet be called either way.
    assert can_still_decide([None], 2, 5) is True


def test_can_still_decide_two_runs_disagreeing_on_a_code() -> None:
    # one failed M, one did not; batch of 3 has 1 pending; after it 2 unrequested
    assert can_still_decide([_run(C.M_ASSESSABLE), _run()], 1, 5) is False


def test_can_still_decide_two_agreeing_runs_one_pending() -> None:
    assert can_still_decide([_run(), _run()], 1, 5) is True
    assert can_still_decide([_run(C.M_ASSESSABLE), _run(C.M_ASSESSABLE)], 1, 5) is True


def test_can_still_decide_nothing_pending_matches_is_decided() -> None:
    for runs in (
        [_run(), _run(), _run()],
        [_run(C.M_ASSESSABLE), _run(), _run()],
        [_run(C.M_ASSESSABLE)] * 3,
        [_run(), None, _run()],
    ):
        assert can_still_decide(runs, 0, 5) == is_decided(runs, 5)


def test_can_still_decide_single_run_and_three() -> None:
    assert can_still_decide([], 1, 1) is True
    assert can_still_decide([None], 0, 1) is True  # nothing left to start either way
    # requested 3, t 2, batch 2: one agreeing run so far, one pending
    assert can_still_decide([_run()], 1, 3) is True
    assert can_still_decide([_run(C.S_OBJECT)], 1, 3) is True
    assert can_still_decide([None, _run()], 0, 3) is False


def test_can_still_decide_never_false_when_the_batch_could_decide() -> None:
    import itertools

    outcomes = [None, _run(), _run(C.M_ASSESSABLE), _run(C.M_ASSESSABLE, C.S_OBJECT)]
    for requested in (1, 3, 5):
        first = first_batch_size(requested)
        for done_n in range(first):
            pending = first - done_n
            for done in itertools.product(outcomes, repeat=done_n):
                for rest in itertools.product(outcomes, repeat=pending):
                    if is_decided([*done, *rest], requested):
                        assert can_still_decide(list(done), pending, requested)
