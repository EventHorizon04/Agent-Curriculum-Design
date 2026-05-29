from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.graph import AgentState, build_graph
from curriculum_agent.models import (
    Domain,
    BloomLevel,
    KrathwohlLevel,
    ProgramMetadata,
    SMARTCheck,
    SkillCluster,
    SkillType,
    StakeholderEvidence,
    StakeholderType,
    YLOMatrix,
)
from curriculum_agent.stages.plo_synthesis import _PLODraft, _PLODraftList
from curriculum_agent.stages.ylo_derivation import _YLODraft, _YLOListResponse

_SMART_PASS = SMARTCheck(
    specific=True, measurable=True, achievable=True, relevant=True, timely=True
)

_EVIDENCE_CLASSIFY = type(
    "_ClassifyResult",
    (),
    {"classification": "need", "classification_rationale_th": "ข้อมูลทดสอบ"},
)()

_SKILL_RESP = type("_ExtractedSkillsResponse", (), {"skills": []})()

_CLUSTER_RESP = type(
    "_ClusterNameResult",
    (),
    {
        "canonical_name_th": "การเขียนโปรแกรม",
        "canonical_name_en": "Programming",
        "description_th": "ทักษะการเขียนโปรแกรม",
        "skill_type": "knowledge",
        "is_subject_specific": True,
        "sample_quotes_th": [],
    },
)()

_PLO_DRAFTS = _PLODraftList(
    plos=[
        _PLODraft(
            plo_id=f"PLO-{i}",
            statement_th=f"ออกแบบและพัฒนาซอฟต์แวร์ในด้านที่ {i} ได้อย่างเป็นระบบ",
            domain=Domain.COGNITIVE,
            bloom_level=BloomLevel.CREATE,
            is_subject_specific=True,
            action_verb_th="ออกแบบ",
            source_cluster_ids=["C1"],
            source_evidence_ids=["E1"],
            rationale_th=f"สาเหตุที่ {i}",
        )
        for i in range(1, 5)
    ]
)

_YLO_RESP = _YLOListResponse(
    ylos=[
        _YLODraft(
            ylo_id=f"YLO-PLO-{plo}-Y{yr}",
            year=yr,
            statement_th=f"ปฏิบัติทักษะด้านซอฟต์แวร์ปีที่ {yr} ได้",
            bloom_level=[BloomLevel.REMEMBER, BloomLevel.APPLY, BloomLevel.ANALYZE, BloomLevel.CREATE][yr - 1],
            action_verb_th="ปฏิบัติ",
            rationale_th=f"เหตุผลปีที่ {yr}",
        )
        for plo in range(1, 5)
        for yr in range(1, 5)
    ]
)


def _heavy_side_effect(*args, **kwargs):
    if "ylos" in str(args):
        return _YLO_RESP
    return _PLO_DRAFTS


@pytest.fixture
def initial_state(program_metadata: ProgramMetadata) -> AgentState:
    evidence = StakeholderEvidence(
        evidence_id="E1",
        program_id=program_metadata.program_id,
        stakeholder_type=StakeholderType.EMPLOYER,
        source_name="บริษัททดสอบ",
        raw_text_th="ต้องการผู้สำเร็จการศึกษาที่เขียนโปรแกรมได้และทำงานเป็นทีมได้",
    )
    return AgentState(
        program_id=program_metadata.program_id,
        metadata=program_metadata.model_dump(mode="json"),
        raw_evidence=[evidence.model_dump(mode="json")],
    )


@pytest.mark.anyio
async def test_full_graph_runs_and_stops_at_interrupt(
    initial_state: AgentState,
) -> None:
    """Graph should process Stage 0+1 then stop at review_evidence interrupt."""
    from langgraph.checkpoint.memory import MemorySaver
    graph = build_graph(checkpointer=MemorySaver())

    with (
        patch(
            "curriculum_agent.stages.intake.ProgramRepository.upsert",
            new_callable=AsyncMock,
        ),
        patch(
            "curriculum_agent.stages.stakeholder_needs.complete_light",
            new_callable=AsyncMock,
            return_value=_EVIDENCE_CLASSIFY,
        ),
        patch(
            "curriculum_agent.stages.stakeholder_needs.EvidenceRepository.bulk_insert",
            new_callable=AsyncMock,
        ),
        patch(
            "curriculum_agent.stages.stakeholder_needs._ensure_collection",
            new_callable=AsyncMock,
        ),
        patch(
            "curriculum_agent.stages.stakeholder_needs.embed",
            return_value=[[0.1] * 1024],
        ),
        patch(
            "curriculum_agent.stages.stakeholder_needs.get_qdrant",
            return_value=AsyncMock(upsert=AsyncMock()),
        ),
    ):
        result = await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "test-e2e"}},
        )
        assert "__interrupt__" in result, "Graph should have stopped at review_evidence interrupt"
        assert len(result["__interrupt__"]) > 0, "Interrupt list should be non-empty"


@pytest.mark.anyio
async def test_ylo_matrix_passes_coverage(program_metadata: ProgramMetadata) -> None:
    """Verify that a complete YLOMatrix built from stage outputs passes validate_coverage()."""
    from curriculum_agent.models import PLO, YLO, YLOMatrix

    plos = [PLO.model_validate(d.model_dump(mode="json") | {"program_id": "cs-test", "smart_check": _SMART_PASS.model_dump()})
            for d in _PLO_DRAFTS.plos]
    ylos = []
    for yr in range(1, 5):
        for plo in plos:
            ylos.append(
                YLO(
                    ylo_id=f"YLO-{plo.plo_id}-Y{yr}",
                    program_id="cs-test",
                    parent_plo_id=plo.plo_id,
                    year=yr,
                    statement_th=f"ปฏิบัติงานด้านซอฟต์แวร์ปีที่ {yr} ได้อย่างถูกต้อง",
                    bloom_level=[
                        BloomLevel.REMEMBER,
                        BloomLevel.APPLY,
                        BloomLevel.ANALYZE,
                        BloomLevel.CREATE,
                    ][yr - 1],
                    action_verb_th="ปฏิบัติ",
                    smart_check=_SMART_PASS,
                    rationale_th="เหตุผลทดสอบ",
                )
            )

    matrix = YLOMatrix(program_id="cs-test", plos=plos, ylos=ylos)
    issues = matrix.validate_coverage()
    assert issues == [], f"Coverage issues: {issues}"
