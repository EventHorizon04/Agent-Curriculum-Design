from __future__ import annotations

from typing import Literal

from loguru import logger
from pydantic import BaseModel

from curriculum_agent.data.repositories import ClusterRepository, PLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_light
from curriculum_agent.models import PLO, SkillCluster
from curriculum_agent.prompts.plo_classify import build_plo_classify_prompt

# specific_fraction thresholds for the field-based decision; the open interval
# (LO, HI) is treated as ambiguous and routed to the LLM fallback.
_SPECIFIC_HI = 0.67
_SPECIFIC_LO = 0.33


class _ClassificationResult(BaseModel):
    classification: Literal["generic", "specific"]
    rationale_th: str


def _cluster_summary(c: SkillCluster) -> str:
    spec = "เฉพาะสาขา" if c.is_subject_specific else "ทั่วไป"
    name = c.canonical_name_en or c.canonical_name_th
    return f"{name} (skill_type={c.skill_type.value}, {spec})"


async def _classify_one(plo: PLO, clusters_by_id: dict[str, SkillCluster]) -> tuple[str, str, str]:
    """Return (classification, method, rationale_th) for a single PLO."""
    resolved = [clusters_by_id[cid] for cid in plo.source_cluster_ids if cid in clusters_by_id]

    if resolved:
        n_specific = sum(1 for c in resolved if c.is_subject_specific)
        fraction = n_specific / len(resolved)
        rationale = (
            f"{n_specific}/{len(resolved)} source clusters เป็น subject-specific "
            f"(fraction {fraction:.2f})"
        )
        if fraction >= _SPECIFIC_HI:
            return "specific", "skill_type", rationale
        if fraction <= _SPECIFIC_LO:
            return "generic", "skill_type", rationale

    # Ambiguous fraction, or no resolvable clusters → LLM fallback.
    summaries = [_cluster_summary(c) for c in resolved]
    messages = build_plo_classify_prompt(plo.statement_th, plo.domain.value, summaries)
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
    clusters = await ClusterRepository().list_by_program(program_id)
    clusters_by_id = {c.cluster_id: c for c in clusters}

    logger.info(f"PLO report: classifying {len(plos)} PLOs (generic/specific)")

    classified: list[PLO] = []
    for plo in plos:
        classification, method, rationale = await _classify_one(plo, clusters_by_id)
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
