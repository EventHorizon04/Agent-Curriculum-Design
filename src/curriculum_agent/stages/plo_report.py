from __future__ import annotations

from typing import Any

from loguru import logger

from curriculum_agent.data.repositories import NeedRepository, PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import PLO


async def run(state: AgentState) -> AgentState:
    """PLO Report stage: assemble the reviewable report and persist the PLOs.

    This stage used to classify each PLO generic vs specific. That split came from
    the SS/GS KSEC tags, which no longer exist — a PLO's competency domain is the
    KSEC tag of the Needs behind it, and the report shows that directly instead of
    reducing it to a binary. No LLM call remains here.

    The stage keeps its own checkpoint: synthesis produces outcomes, and this is
    where a designer reviews the finished set and exports it.
    """
    program_id = state.get("program_id", "unknown")
    plo_dicts = state.get("plos", [])
    if not plo_dicts:
        raise ValueError(
            f"PLO report: no PLOs for program '{program_id}' — run PLO synthesis first"
        )

    plos = [PLO.model_validate(d) for d in plo_dicts]
    needs = await NeedRepository().list_by_program(program_id)

    core = sum(1 for p in plos if not p.is_optional)
    escalated = sum(1 for p in plos if p.smart_escalated)
    logger.info(
        f"PLO report: {len(plos)} PLOs ({core} core, {len(plos) - core} optional, "
        f"{escalated} escalated for repair)"
    )

    report: dict[str, Any] = {
        "plos": [p.model_dump(mode="json") for p in plos],
        # Keyed for drill-down: the page resolves each PLO's source_need_ids
        # against this rather than issuing a request per outcome.
        "needs_by_id": {n.need_id: n.model_dump(mode="json") for n in needs},
        "counts": {
            "total": len(plos),
            "core": core,
            "optional": len(plos) - core,
            "escalated": escalated,
        },
    }

    await PLORepository().bulk_insert(plos)

    state["plos"] = report["plos"]
    state["report"] = report
    state["current_stage"] = "plo_report"
    return state
