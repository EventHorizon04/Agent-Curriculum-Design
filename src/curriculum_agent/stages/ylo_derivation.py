from __future__ import annotations

import uuid

from loguru import logger
from pydantic import BaseModel, Field

from curriculum_agent.data.repositories import YLORepository
from curriculum_agent.graph import AgentState
from curriculum_agent.llm import complete_heavy, complete_light
from curriculum_agent.models import (
    FORBIDDEN_WORDS_TH,
    PLO,
    YLO,
    BloomLevel,
    KrathwohlLevel,
    SMARTCheck,
    YLOMatrix,
)
from curriculum_agent.models import ProgramMetadata
from curriculum_agent.prompts.smart_validator import build_smart_validate_prompt
from curriculum_agent.prompts.stage_4_ylo import build_ylo_derivation_prompt

_MAX_RETRIES = 3


class _YLODraft(BaseModel):
    ylo_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    year: int = Field(ge=1, le=8)
    statement_th: str
    statement_en: str | None = None
    bloom_level: BloomLevel | None = None
    krathwohl_level: KrathwohlLevel | None = None
    action_verb_th: str
    rationale_th: str


class _YLOListResponse(BaseModel):
    ylos: list[_YLODraft]


async def _draft_to_ylo(draft: _YLODraft, program_id: str, parent_plo_id: str) -> YLO | None:
    for word in FORBIDDEN_WORDS_TH:
        if word in draft.statement_th:
            logger.warning(f"YLO draft {draft.ylo_id} contains forbidden word '{word}' — skipping")
            return None
    smart = await complete_light(SMARTCheck, build_smart_validate_prompt(draft.statement_th))
    return YLO(
        ylo_id=draft.ylo_id,
        program_id=program_id,
        parent_plo_id=parent_plo_id,
        year=draft.year,
        statement_th=draft.statement_th,
        statement_en=draft.statement_en,
        bloom_level=draft.bloom_level,
        krathwohl_level=draft.krathwohl_level,
        action_verb_th=draft.action_verb_th,
        smart_check=smart,
        rationale_th=draft.rationale_th,
        version=1,
    )


async def _derive_ylos_for_plo(
    metadata: ProgramMetadata,
    plo: PLO,
    program_id: str,
    avoid_words: set[str] | None = None,
) -> tuple[list[YLO], set[str]]:
    messages = build_ylo_derivation_prompt(metadata, plo, avoid_words=avoid_words)
    response = await complete_heavy(_YLOListResponse, messages, max_retries=_MAX_RETRIES)
    ylos = []
    found_forbidden: set[str] = set()
    for draft in response.ylos:
        for word in FORBIDDEN_WORDS_TH:
            if word in draft.statement_th:
                found_forbidden.add(word)
        ylo = await _draft_to_ylo(draft, program_id, plo.plo_id)
        if ylo:
            ylos.append(ylo)
    return ylos, found_forbidden


async def run(state: AgentState) -> AgentState:
    """Stage 4: derive YLO matrix from approved PLOs."""
    plos_dicts = state.get("plos", [])
    program_id = state.get("program_id", "unknown")
    metadata_dict = state.get("metadata")
    if not metadata_dict:
        raise ValueError("AgentState missing 'metadata' — cannot run YLO derivation stage")
    metadata = ProgramMetadata.model_validate(metadata_dict)

    plos = [PLO.model_validate(d) for d in plos_dicts]
    logger.info(f"Stage 4: deriving YLOs for {len(plos)} PLOs")

    all_ylos: list[YLO] = []
    for plo in plos:
        ylos, _ = await _derive_ylos_for_plo(metadata, plo, program_id)
        all_ylos.extend(ylos)
        logger.debug(f"  {plo.plo_id}: {len(ylos)} YLOs generated")

    matrix = YLOMatrix(program_id=program_id, plos=plos, ylos=all_ylos)
    issues = matrix.validate_coverage()

    if issues:
        logger.warning(f"Stage 4: {len(issues)} coverage issues — regenerating problematic PLOs")
        # Collect PLO IDs with issues
        problem_plo_ids: set[str] = set()
        for issue in issues:
            # issue text references plo_id (e.g. "PLO-1 has no YLO...")
            for plo in plos:
                if plo.plo_id in issue:
                    problem_plo_ids.add(plo.plo_id)

        for attempt in range(_MAX_RETRIES):
            if not problem_plo_ids:
                break
            new_ylos_map: dict[str, list[YLO]] = {}
            for plo in plos:
                if plo.plo_id in problem_plo_ids:
                    new_ylos_map[plo.plo_id], _ = await _derive_ylos_for_plo(
                        metadata, plo, program_id, avoid_words=FORBIDDEN_WORDS_TH
                    )

            # Replace YLOs for problematic PLOs
            kept = [y for y in all_ylos if y.parent_plo_id not in problem_plo_ids]
            replacement = [y for ylo_list in new_ylos_map.values() for y in ylo_list]
            all_ylos = kept + replacement

            matrix = YLOMatrix(program_id=program_id, plos=plos, ylos=all_ylos)
            issues = matrix.validate_coverage()
            problem_plo_ids = set()
            for issue in issues:
                for plo in plos:
                    if plo.plo_id in issue:
                        problem_plo_ids.add(plo.plo_id)

            if not problem_plo_ids:
                logger.info(f"Stage 4: coverage issues resolved on attempt {attempt + 1}")
                break

        if issues:
            logger.warning(f"Stage 4: {len(issues)} issues remain after retries: {issues}")

    await YLORepository().save_matrix(matrix)

    state["ylo_matrix"] = matrix.model_dump(mode="json")
    state["current_stage"] = "ylo_derivation"
    return state
