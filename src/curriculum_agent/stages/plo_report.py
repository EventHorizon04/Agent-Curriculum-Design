from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from curriculum_agent.data.repositories import (
    NeedRepository,
    PLOReportRepository,
    PLORepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.models import PLOReport
from curriculum_agent.stages.plo_review_facts import need_demands, plo_fingerprint
from curriculum_agent.stages.plo_synthesis import cited_need_ids


async def run(state: AgentState) -> AgentState:
    """PLO Report stage: assemble the report from the stored PLOs and store it.

    This stage used to classify each PLO generic vs specific. That split came from
    the SS/GS KSEC tags, which no longer exist — a PLO's competency domain is the
    KSEC tag of the Needs behind it, and the report shows that directly instead of
    reducing it to a binary. No LLM call remains here.

    It reads the PLOs from the database, never from `state["plos"]`: the designer
    may have edited the set while the session was suspended, and writing the
    checkpoint's copy back would undo that. It writes no PLO; the report is one
    row in `plo_reports`, stamped with the fingerprint of the set it was built from.

    No checkpoint follows it: it is the last stage, built from the set the designer
    approved at the PLO checkpoint after the QA review (stage 06, `plo_review`).
    """
    program_id = state.get("program_id", "unknown")
    plos = await PLORepository().list_by_program(program_id)
    if not plos:
        raise ValueError(
            f"PLO report: no PLOs for program '{program_id}' — run PLO synthesis first"
        )

    needs = await NeedRepository().list_active_by_program(program_id)
    needs_by_id = {n.need_id: n for n in needs}

    # Needs the designer excluded at the Need stage. A merged-away original is a
    # fold (`merged_into`), not an exclusion, so it is left out. The active read
    # drops both kinds, so these never also appear in `needs_not_synthesized`.
    every = await NeedRepository().list_by_program(program_id)
    excluded = sorted(
        (n for n in every if n.excluded_at is not None and n.merged_into is None),
        key=lambda n: (n.excluded_at, n.need_id),
    )
    needs_excluded = [
        {
            "need_id": n.need_id,
            "statement_th": n.statement_th,
            "ksec_categories": list(n.ksec_categories),
            "demand_score": n.demand_score,
            "excluded_at": n.excluded_at.isoformat() if n.excluded_at else None,
        }
        for n in excluded
    ]

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
        # Needs the designer excluded: listed so the approved report says what
        # was left out on purpose, apart from what simply lost the cut.
        "needs_excluded": needs_excluded,
        "counts": {
            "total": len(plos),
            "core": core,
            "optional": len(plos) - core,
            "escalated": escalated,
            "stale": stale,
            "code_only": code_only,
            "needs_not_synthesized": len(not_synthesized),
            "needs_excluded": len(needs_excluded),
        },
    }

    await PLOReportRepository().upsert(
        PLOReport(
            program_id=program_id,
            plo_fingerprint=plo_fingerprint(plos, need_demands(needs)),
            created_at=datetime.now(UTC).replace(tzinfo=None),
            report=report,
        )
    )

    state["plos"] = report["plos"]
    state["report"] = report
    state["current_stage"] = "plo_report"
    return state
