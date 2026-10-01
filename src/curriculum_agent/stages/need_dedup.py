"""Find Needs that ask for one capability, before plo_synthesis drafts any.

`plo_synthesis` gives every Need its own slot, and the "one PLO per Need"
invariant only stops one Need being cited twice — two Needs that mean the same
thing still became two PLOs. This module asks one model, once per run, which
in-scope Needs ask for the same graduate capability, and hands back the groups
the code accepts. Each accepted group becomes one slot drafted from all its
members, exactly as a designer's manual merge would be.

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
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.config import settings
from curriculum_agent.llm import complete_need_dedup
from curriculum_agent.models import Need, ProgramMetadata
from curriculum_agent.prompts.need_dedup import build_need_dedup_prompt
from curriculum_agent.prompts.program_context import build_program_context_th

# One sentence has to carry every member. Past three it stops being able to,
# which is ticket 18's fifteen-name group over again at the PLO level.
MAX_GROUP_SIZE = 3

# Instructor attempts in total (an int max_retries is attempts, not retries).
_ATTEMPTS = 2


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


def label_needs(needs: list[Need]) -> dict[str, Need]:
    """`N1`, `N2`, ... in the order given — the caller passes demand order."""
    return {f"N{i}": need for i, need in enumerate(needs, start=1)}


def _rejection(known: list[str], taken: set[str], labelled: dict[str, Need]) -> str | None:
    if len(known) < 2:
        return "fewer than two known Needs"
    if taken.intersection(known):
        return "a member is already in an accepted group"
    if len({labelled[label].ksec_category for label in known}) > 1:
        return "members span more than one KSEC tag"
    if len(known) > MAX_GROUP_SIZE:
        return f"more than {MAX_GROUP_SIZE} members"
    return None


def accept_groups(answer: DedupAnswer, labelled: dict[str, Need]) -> list[FoldGroup]:
    """The groups that break no structural rule, first group winning a contested Need."""
    order = {label: i for i, label in enumerate(labelled)}
    taken: set[str] = set()
    accepted: list[FoldGroup] = []
    for group in answer.groups:
        raw = [label.strip().upper() for label in group.labels]
        known = list(dict.fromkeys(label for label in raw if label in labelled))
        rejection = _rejection(known, taken, labelled)
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


async def find_duplicate_groups(needs: list[Need], metadata: ProgramMetadata) -> list[FoldGroup]:
    """One call over the in-scope Needs, already in synthesis order.

    Returns no groups — today's one-slot-per-Need behaviour — when the slot is
    switched off, when there is nothing to compare, and when the call fails for
    any reason. The step can only fold, so its absence never costs a PLO.
    """
    if not settings.need_dedup_provider:
        logger.info("need_dedup: disabled — every Need gets its own slot")
        return []
    if len(needs) < 2:
        return []

    labelled = label_needs(needs)
    messages = build_need_dedup_prompt(
        [(label, n.ksec_category.value, n.statement_th) for label, n in labelled.items()],
        program_context=build_program_context_th(metadata.model_dump()),
    )
    try:
        answer = await complete_need_dedup(
            DedupAnswer, messages, max_retries=_ATTEMPTS, temperature=0
        )
    except Exception as exc:
        logger.warning(f"need_dedup: call failed, folding nothing: {exc}")
        return []
    return accept_groups(answer, labelled)
