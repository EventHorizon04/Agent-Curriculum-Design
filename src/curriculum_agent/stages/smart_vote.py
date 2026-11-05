"""Pure majority vote over parallel SMART judge runs.

The validation agent judges one PLO several times and a soft criterion counts
as failed only when a majority of the successful runs failed it. Nothing here
calls a model: a run that could not be completed is `None`, and the functions
only count. A vote never touches the hard criteria, which `hard_failures`
decides on the final statement whatever happens here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from curriculum_agent.smart_vocabulary import SmartFindingCode

# Soft verdict field -> the code recorded when it is false. Every code here has
# a label in FINDING_LABEL_TH and its frontend mirror, which is what the
# exporter and both pages render.
#
# actor_ok and scope_ok arrived after the other five and answer what nothing
# else did at the PLO level. The scope guard judges a *Need* from skill flags
# and a ratio, so a Need that passes it can still yield a sentence describing
# the institution's mission or another profession's job; these two read the
# sentence itself. They fold into SMARTCheck.achievable in plo_synthesis rather
# than adding a field, so no stored row changes shape.
_SOFT_VERDICTS: tuple[tuple[str, SmartFindingCode], ...] = (
    ("specific_object_ok", SmartFindingCode.S_OBJECT),
    ("measurable_ok", SmartFindingCode.M_ASSESSABLE),
    ("achievable_ok", SmartFindingCode.A_LEVEL),
    ("actor_ok", SmartFindingCode.A_ACTOR),
    ("scope_ok", SmartFindingCode.A_SCOPE),
    ("relevant_needs_ok", SmartFindingCode.R_NEEDS),
    ("time_bound_ok", SmartFindingCode.T_HORIZON),
)

_SOFT_ORDER: tuple[SmartFindingCode, ...] = tuple(code for _, code in _SOFT_VERDICTS)

# A repair cannot change who the actor is or what profession the work belongs
# to: both are properties of the Need, so they are reported, never repaired.
REPAIR_EXCLUDED: frozenset[SmartFindingCode] = frozenset(
    {SmartFindingCode.A_ACTOR, SmartFindingCode.A_SCOPE}
)


@dataclass(frozen=True)
class JudgeRun:
    failed: frozenset[SmartFindingCode]
    notes_th: Mapping[SmartFindingCode, str]
    diagnosis_th: str
    repair_hint_th: str
    turns: int


@dataclass(frozen=True)
class SoftVote:
    threshold: int
    runs_requested: int
    runs_used: int
    failed: tuple[SmartFindingCode, ...]
    representative: JudgeRun


def vote_threshold(requested: int) -> int:
    return requested // 2 + 1


def first_batch_size(requested: int) -> int:
    return vote_threshold(requested)


def _successes(runs: Sequence[JudgeRun | None]) -> list[JudgeRun]:
    return [run for run in runs if run is not None]


def is_decided(runs: Sequence[JudgeRun | None], requested: int) -> bool:
    """True when the runs still pending cannot change the outcome of the vote."""
    t = vote_threshold(requested)
    pending = requested - len(runs)
    ok = _successes(runs)
    if not (len(ok) >= t or len(ok) + pending < t):
        return False
    for code in _SOFT_ORDER:
        f = sum(1 for run in ok if code in run.failed)
        if not (f >= t or f + pending < t):
            return False
    return True


def vote(runs: Sequence[JudgeRun | None], requested: int) -> SoftVote | None:
    """The majority verdict, or None when too few runs succeeded to hold a vote."""
    t = vote_threshold(requested)
    ok = _successes(runs)
    if len(ok) < t:
        return None
    failed = tuple(code for code in _SOFT_ORDER if sum(1 for run in ok if code in run.failed) >= t)
    majority = frozenset(failed)
    # max() keeps the first of equal keys, which is the earliest run.
    representative = max(
        ok,
        key=lambda run: (len(run.failed & majority), -len(run.failed - majority)),
    )
    return SoftVote(
        threshold=t,
        runs_requested=requested,
        runs_used=len(ok),
        failed=failed,
        representative=representative,
    )


def repairable(failed: Sequence[SmartFindingCode]) -> list[SmartFindingCode]:
    return [code for code in failed if code not in REPAIR_EXCLUDED]
