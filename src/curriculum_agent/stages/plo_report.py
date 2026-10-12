from __future__ import annotations

from typing import Any

from loguru import logger

from curriculum_agent.data.repositories import NeedRepository, PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import PLO
from curriculum_agent.stages.plo_synthesis import cited_need_ids


async def run(state: AgentState) -> AgentState:
    """PLO Report stage: assemble the reviewable report and persist the PLOs.

    This stage used to classify each PLO generic vs specific. That split came from
    the SS/GS KSEC tags, which no longer exist — a PLO's competency domain is the
    KSEC tag of the Needs behind it, and the report shows that directly instead of
    reducing it to a binary. No LLM call remains here.

    No checkpoint follows it: the set was approved at the PLO checkpoint, and the
    QA review (stage 06, `plo_review`) runs after this stage and is not part of
    the report.
    """
    program_id = state.get("program_id", "unknown")
    plo_dicts = state.get("plos", [])
    if not plo_dicts:
        raise ValueError(
            f"PLO report: no PLOs for program '{program_id}' — run PLO synthesis first"
        )

    plos = [PLO.model_validate(d) for d in plo_dicts]
    needs = await NeedRepository().list_by_program(program_id)
    needs_by_id = {n.need_id: n for n in needs}

    # Every PLO must trace to evidence (project rule); a source_need_id that
    # resolves to nothing here would ship a checkpoint the designer cannot
    # actually drill into. The old classification stage surfaced this same
    # gap as method="fallback" — this is its replacement, now that there is
    # no classification step left to carry the signal.
    for plo in plos:
        unresolved = [nid for nid in plo.source_need_ids if nid not in needs_by_id]
        if unresolved:
            logger.warning(
                f"PLO {plo.plo_id} cites Need id(s) {unresolved} not found for "
                f"program '{program_id}' — the drill-down for this outcome will be incomplete"
            )

    # Derived from the data rather than read off AgentState: a Need ends up with
    # no PLO because it lost the MAX_CORE_PLOS cut, because its synthesis failed,
    # or because a merge superseded the outcome that used to cite it. All three
    # belong in front of the designer, and all three are the same question — which
    # is why `cited_need_ids` answers it here and for the merge endpoint alike.
    # This list is also the pool a merge selects from: a Need is behind at most
    # one outcome, so absence from the citations is what makes it available again.
    cited = cited_need_ids(plos)
    not_synthesized = [nid for nid in needs_by_id if nid not in cited]

    core = sum(1 for p in plos if not p.is_optional)
    escalated = sum(1 for p in plos if p.smart_escalated)
    # "the validator judged this and it failed" and "no validator has judged
    # this as written" are different facts, and a designer at the checkpoint has
    # to be able to tell them apart. `stale` is a hand-edited statement awaiting
    # revalidation; `code_only` is a verdict the pure checks reached alone
    # because the agent could not run.
    stale = sum(1 for p in plos if p.smart_validated_by == "stale")
    code_only = sum(1 for p in plos if p.smart_validated_by == "code_only")
    logger.info(
        f"PLO report: {len(plos)} PLOs ({core} core, {len(plos) - core} optional, "
        f"{escalated} escalated for repair, {stale} awaiting revalidation, "
        f"{code_only} judged by code alone), {len(not_synthesized)} Need(s) without a PLO"
    )

    report: dict[str, Any] = {
        "plos": [p.model_dump(mode="json") for p in plos],
        # Keyed for drill-down: the page resolves each PLO's source_need_ids
        # against this rather than issuing a request per outcome.
        "needs_by_id": {nid: n.model_dump(mode="json") for nid, n in needs_by_id.items()},
        # Needs that produced no PLO — the ones below the MAX_CORE_PLOS cut, plus
        # any whose synthesis failed. Listed, not just counted, so the review page
        # can name them.
        "needs_not_synthesized": not_synthesized,
        "counts": {
            "total": len(plos),
            "core": core,
            "optional": len(plos) - core,
            "escalated": escalated,
            "stale": stale,
            "code_only": code_only,
            "needs_not_synthesized": len(not_synthesized),
        },
    }

    await PLORepository().bulk_insert(plos)

    state["plos"] = report["plos"]
    state["report"] = report
    state["current_stage"] = "plo_report"
    return state
