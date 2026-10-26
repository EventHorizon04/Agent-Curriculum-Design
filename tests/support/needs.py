"""Shared fixtures for the Need statement contract.

`_NeedStatement.rationale_th` is required, so every stub standing in for the
summarize call has to carry one. Keeping the sample here rather than retyping it
means a future change to what the field accepts is one edit, not fourteen — and
the sample is a *valid* one on purpose: a stub that silently stopped satisfying
the validators would make the stage's own guard untested everywhere at once.
"""

from __future__ import annotations

from typing import Any

# Long enough for MIN_RATIONALE_CHARS, short enough for MAX, and free of the
# head+modifier pairs find_vague_phrase rejects.
RATIONALE_TH = "ทักษะในกลุ่มนี้ใช้ทำงานเดียวกันคือการดูแลระบบสารสนเทศขององค์กรให้ทำงานต่อเนื่อง"


async def run_need_pipeline_from_skills(state: dict[str, Any]) -> dict[str, Any]:
    """Cluster `state["extracted_skills"]` in memory, then run Agent 2 on the groups.

    Stands in for the two stages back to back without touching the group
    repository: tests that assert on the Needs a set of skills turns into do not
    care that grouping is stored in between. Clustering is whatever the test
    patched onto `skill_grouping.cluster_skill_names`.
    """
    from curriculum_agent.models import ExtractedSkill  # noqa: PLC0415
    from curriculum_agent.prompts.program_context import build_program_context_th  # noqa: PLC0415
    from curriculum_agent.stages import need_combination, skill_grouping  # noqa: PLC0415
    from curriculum_agent.stages.demand import build_scoring_corpus  # noqa: PLC0415

    skills = [ExtractedSkill.model_validate(d) for d in state["extracted_skills"]]
    corpus = build_scoring_corpus(
        (s.source_evidence_id, s.source_stakeholder_type.value) for s in skills
    )
    groups = await skill_grouping.build_skill_groups(
        state.get("program_id", "unknown"),
        skills,
        corpus,
        build_program_context_th(state.get("metadata") or {}),
    )
    # extracted_skills stay on the state: Agent 2 reads them to score a merged Need,
    # exactly as it does in a graph session where Agent 1 just ran.
    rest = dict(state)
    rest["skill_groups"] = [g.model_dump(mode="json") for g in groups]
    return await need_combination.run(rest)  # type: ignore[arg-type]
