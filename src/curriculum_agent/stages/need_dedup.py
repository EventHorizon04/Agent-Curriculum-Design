"""Find Needs that ask for one capability, before plo_synthesis drafts any.

`plo_synthesis` gives every Need its own slot, and the "one PLO per Need"
invariant only stops one Need being cited twice — two Needs that mean the same
thing still became two PLOs. This module asks one model which in-scope Needs
ask for the same graduate capability — `need_dedup_runs` times, in parallel — and
hands back the groups a majority of the usable answers agree on. Each accepted
group becomes one merged Need (stages/need_merge.py) that replaces its members for
synthesis, as a designer's manual merge would.

Evidence overlap is not the similarity, and it was measured before this was
written: on the stored run a marketing Need and an ethics Need shared 55% of
their evidence while a true duplicate pair shared under 20%. A small corpus
puts every Need on the same few documents. See the design doc,
`docs/superpowers/specs/2026-09-30-need-dedup-before-synthesis-design.md`.

The structural rules live in `accept_groups`, not in pydantic validators: a
validator failure makes instructor retry and then fail the whole call, which
discards every good group in an answer for one bad one. The schema only has to
parse. And a rule-breaking group is dropped whole, never trimmed — which member
to cut is the judgement the model was asked for, and code cutting by position
would make a decision nobody made.

One call is not a stable answer. Replaying it six times on the same ten Needs
gave six different sets of groups (none, two pairs, a different pair...) and no
pair reached a majority, so a single call decided merges by luck. Each run's
answer therefore goes through `accept_groups` on its own, and the vote counts
pairs across runs, as `plo_review_consensus` does for redundancy findings: a pair
is merged when more than half of the usable runs named it. Borderline pairs stay
unmerged for the designer to merge by hand at the checkpoint.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.config import settings
from curriculum_agent.llm import complete_need_dedup
from curriculum_agent.models import Need, ProgramMetadata
from curriculum_agent.prompts.need_dedup import build_need_dedup_prompt
from curriculum_agent.prompts.program_context import build_program_context_th
from curriculum_agent.stages.need_grouping import ksec_label
from curriculum_agent.stages.plo_review_consensus import agreement_threshold

# One sentence has to carry every member. Past five it stops being able to,
# which is ticket 18's fifteen-name group over again. It was three while the
# fold fed a PLO draft; a merged Need is written from its top skills only, so
# five originals still fit one sentence.
MAX_GROUP_SIZE = 5

# Instructor attempts in total (an int max_retries is attempts, not retries).
_ATTEMPTS = 2

# GLM took 30-258 s on identical input with its reasoning unbounded; the vote
# makes several calls at once, so one runaway call must not set the stage's time.
_MAX_TOKENS = 4096
_REASONING_MAX_TOKENS = 1024

_Pair = tuple[str, str]


class DuplicateGroup(BaseModel):
    labels: list[str] = Field(default_factory=list)
    reason_th: str = ""


class DedupAnswer(BaseModel):
    groups: list[DuplicateGroup] = Field(default_factory=list)


@dataclass(frozen=True)
class FoldGroup:
    """Needs the check found to ask for one capability, in label (demand) order."""

    needs: tuple[Need, ...]
    reason_th: str


class AcceptedGroups(list[FoldGroup]):
    """The accepted groups, plus how many the model proposed.

    A plain list to every caller. `proposed` and `call` ride along so the merge
    step's one summary line can say how many groups the rules dropped, and
    whether an empty answer means "the model found nothing" (`call == "ok"`) or
    "there was no answer" (`"failed"`, `"disabled"`, `"skipped"` for fewer than
    two Needs), without `accept_groups` or `find_duplicate_groups` changing what
    they return.
    """

    proposed: int = 0
    call: str = "ok"

    @classmethod
    def with_call(cls, call: str) -> AcceptedGroups:
        """An empty result that says why it is empty."""
        empty = cls()
        empty.call = call
        return empty


def label_needs(needs: list[Need]) -> dict[str, Need]:
    """`N1`, `N2`, ... in the order given — the caller passes demand order."""
    return {f"N{i}": need for i, need in enumerate(needs, start=1)}


def _rejection(known: list[str], taken: set[str]) -> str | None:
    # No KSEC rule: Needs of different tags that ask for one capability merge into
    # one multi-tag Need, so the tags may differ.
    if len(known) < 2:
        return "fewer than two known Needs"
    if taken.intersection(known):
        return "a member is already in an accepted group"
    if len(known) > MAX_GROUP_SIZE:
        return f"more than {MAX_GROUP_SIZE} members"
    return None


def accept_groups(answer: DedupAnswer, labelled: dict[str, Need]) -> AcceptedGroups:
    """The groups that break no structural rule, first group winning a contested Need."""
    order = {label: i for i, label in enumerate(labelled)}
    taken: set[str] = set()
    accepted = AcceptedGroups()
    accepted.proposed = len(answer.groups)
    for group in answer.groups:
        raw = [label.strip().upper() for label in group.labels]
        known = list(dict.fromkeys(label for label in raw if label in labelled))
        rejection = _rejection(known, taken)
        if rejection:
            logger.warning(f"need_dedup: dropped group {raw} — {rejection}")
            continue
        known.sort(key=order.__getitem__)
        taken.update(known)
        accepted.append(
            FoldGroup(
                needs=tuple(labelled[label] for label in known),
                reason_th=group.reason_th.strip(),
            )
        )
    logger.info(
        f"need_dedup: {len(accepted)} group(s) accepted, "
        f"{len(answer.groups) - len(accepted)} dropped by rule"
    )
    return accepted


def _label_order(label: str) -> int:
    # N10 after N9: compare the number, not the string.
    return int(label[1:])


_RunGroups = Sequence[tuple[list[str], str]]


def _vote(
    runs: Sequence[_RunGroups], threshold: int
) -> tuple[list[tuple[list[str], str]], Counter[_Pair]]:
    """The (labels in order, reason) groups a majority of runs agree on, plus pair support.

    Pairs are counted once per run. A connected component of passing pairs
    becomes one group only when every pair inside it passes and it fits
    `MAX_GROUP_SIZE` — joining N4+N9 and N6+N9 would assert N4+N6, which no
    majority said. Otherwise its passing pairs are emitted as 2-Need groups,
    most supported first, skipping a pair whose member is already placed.
    """
    support: Counter[_Pair] = Counter()
    for run in runs:
        named: set[_Pair] = set()
        for members, _ in run:
            named.update(combinations(sorted(members, key=_label_order), 2))
        support.update(named)  # a pair counts once per run
    passing = {p for p, n in support.items() if n >= threshold}

    neighbours: dict[str, set[str]] = {}
    for a, b in passing:
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)

    chosen: list[list[str]] = []
    placed: set[str] = set()
    for start in sorted(neighbours, key=_label_order):
        if start in placed:
            continue
        component: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node not in component:
                component.add(node)
                stack.extend(neighbours[node] - component)
        placed |= component
        members = sorted(component, key=_label_order)
        inner = set(combinations(members, 2))
        if len(members) <= MAX_GROUP_SIZE and inner <= passing:
            chosen.append(members)
            continue
        taken: set[str] = set()
        ranked = sorted(
            inner & passing,
            key=lambda p: (-support[p], _label_order(p[0]), _label_order(p[1])),
        )
        for a, b in ranked:
            if a in taken or b in taken:
                continue
            taken.update((a, b))
            chosen.append([a, b])
    chosen.sort(key=lambda members: _label_order(members[0]))

    voted: list[tuple[list[str], str]] = []
    for members in chosen:
        want = set(members)
        # The first run whose group holds every member. A pair carved out of a
        # component was named by some run, so a group holding it always exists.
        reasons = [r for run in runs for g, r in run if want <= set(g)]
        voted.append((members, reasons[0] if reasons else ""))
    return voted, support


async def find_duplicate_groups(needs: list[Need], metadata: ProgramMetadata) -> AcceptedGroups:
    """`need_dedup_runs` parallel calls over the in-scope Needs, already in synthesis order.

    Returns no groups — today's one-slot-per-Need behaviour — when the slot is
    switched off, when there is nothing to compare, and when every call fails.
    A failed call is not a vote: the threshold is a majority of the calls that
    answered. The step can only fold, so its absence never costs a PLO.
    """
    if not settings.need_dedup_provider:
        logger.info("need_dedup: disabled — every Need gets its own slot")
        return AcceptedGroups.with_call("disabled")
    if len(needs) < 2:
        return AcceptedGroups.with_call("skipped")

    labelled = label_needs(needs)
    messages = build_need_dedup_prompt(
        [(label, ksec_label(n), n.statement_th) for label, n in labelled.items()],
        program_context=build_program_context_th(metadata.model_dump()),
    )
    requested = settings.need_dedup_runs
    answers = await asyncio.gather(
        *(
            complete_need_dedup(
                DedupAnswer,
                messages,
                max_retries=_ATTEMPTS,
                temperature=0,
                max_tokens=_MAX_TOKENS,
                reasoning_max_tokens=_REASONING_MAX_TOKENS,
            )
            for _ in range(requested)
        ),
        return_exceptions=True,
    )
    usable: list[AcceptedGroups] = []
    for answer in answers:
        if isinstance(answer, BaseException):
            logger.warning(f"need_dedup: a call failed and does not vote: {answer}")
        else:
            usable.append(accept_groups(answer, labelled))
    if not usable:
        logger.warning("need_dedup: every call failed, folding nothing")
        return AcceptedGroups.with_call("failed")

    label_of = {need.need_id: label for label, need in labelled.items()}
    per_run = [
        [([label_of[n.need_id] for n in g.needs], g.reason_th) for g in run] for run in usable
    ]
    threshold = agreement_threshold(len(usable))
    voted, support = _vote(per_run, threshold)

    result = AcceptedGroups()
    result.proposed = sum(run.proposed for run in usable)
    for members, reason in voted:
        result.append(FoldGroup(needs=tuple(labelled[m] for m in members), reason_th=reason))
    pairs = " ".join(f"{a}+{b}={n}" for (a, b), n in support.most_common())
    logger.info(
        f"need_dedup: {len(usable)}/{requested} runs, threshold {threshold}, "
        f"pairs {pairs or 'none'} -> {len(result)} group(s) agreed"
    )
    return result
