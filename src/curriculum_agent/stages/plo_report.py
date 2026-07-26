from __future__ import annotations

from typing import Literal

from loguru import logger
from pydantic import BaseModel

from curriculum_agent.data.repositories import NeedRepository, PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import PLO, KSECCategory, Need
from curriculum_agent.prompts.plo_classify import build_plo_classify_prompt

# specific_fraction thresholds for the field-based decision; the open interval
# (LO, HI) is treated as ambiguous and routed to the LLM fallback.
_SPECIFIC_HI = 0.67
_SPECIFIC_LO = 0.33


class _ClassificationResult(BaseModel):
    classification: Literal["generic", "specific"]
    rationale_th: str


def _need_summary(n: Need) -> str:
    return f"{n.statement_en or n.statement_th} (ksec={n.ksec_category.value})"


async def _classify_one(plo: PLO, needs_by_id: dict[str, Need]) -> tuple[str, str, str]:
    """Return (classification, method, rationale_th) for a single PLO."""
    resolved = [needs_by_id[cid] for cid in plo.source_need_ids if cid in needs_by_id]

    if resolved:
        n_specific = sum(1 for n in resolved if n.ksec_category is KSECCategory.SS)
        fraction = n_specific / len(resolved)
        rationale = (
            f"{n_specific}/{len(resolved)} source Needs เป็น subject-specific (SS) "
            f"(fraction {fraction:.2f})"
        )
        if fraction >= _SPECIFIC_HI:
            return "specific", "ksec", rationale
        if fraction <= _SPECIFIC_LO:
            return "generic", "ksec", rationale

    # Ambiguous fraction, or no resolvable Needs → LLM fallback.
    summaries = [_need_summary(n) for n in resolved]
    messages = build_plo_classify_prompt(plo.statement_th, plo.bloom_level.value, summaries)
    result = await complete_light(_ClassificationResult, messages)
    return result.classification, "llm", result.rationale_th


async def run(state: AgentState) -> AgentState:
    """PLO Report stage: classify each PLO as generic/specific (method D)."""
    program_id = state.get("program_id", "unknown")
    plo_dicts = state.get("plos", [])
    if not plo_dicts:
        raise ValueError(
            f"PLO report: no PLOs for program '{program_id}' — run PLO synthesis first"
        )

    plos = [PLO.model_validate(d) for d in plo_dicts]
    needs = await NeedRepository().list_by_program(program_id)
    needs_by_id = {n.need_id: n for n in needs}

    logger.info(f"PLO report: classifying {len(plos)} PLOs (generic/specific)")

    classified: list[PLO] = []
    for plo in plos:
        classification, method, rationale = await _classify_one(plo, needs_by_id)
        classified.append(
            plo.model_copy(
                update={
                    "classification": classification,
                    "classification_method": method,
                    "classification_rationale_th": rationale,
                    "is_subject_specific": classification == "specific",
                }
            )
        )

    await PLORepository().bulk_insert(classified)

    state["plos"] = [p.model_dump(mode="json") for p in classified]
    state["current_stage"] = "plo_report"
    return state
