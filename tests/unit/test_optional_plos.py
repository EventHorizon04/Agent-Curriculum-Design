from __future__ import annotations

from unittest.mock import AsyncMock, patch

from curriculum_agent.models import ProgramMetadata, SkillCluster, SkillType
from curriculum_agent.prompts.stage_3_plo import build_optional_plo_prompt


def _cluster(cid: str, optional: bool) -> SkillCluster:
    return SkillCluster(
        cluster_id=cid, program_id="p1", canonical_name_th=f"กลุ่ม {cid}",
        description_th="คำอธิบาย", skill_type=SkillType.KNOWLEDGE,
        is_subject_specific=True, member_skill_ids=["s1"],
        source_evidence_ids=["e1"], demand_score=0.6, is_optional=optional,
    )


def test_optional_prompt_labels_output_optional(sample_metadata, sample_clusters):
    msgs = build_optional_plo_prompt(sample_metadata, sample_clusters)
    joined = msgs[0]["content"] + msgs[1]["content"]
    assert "เสริม" in joined or "optional" in joined.lower()
    assert "1-4" in joined


def test_optional_clusters_split_from_core():
    clusters = [_cluster("c1", False), _cluster("c2", True), _cluster("c3", False)]
    core = [c for c in clusters if not c.is_optional]
    optional = [c for c in clusters if c.is_optional]
    assert [c.cluster_id for c in core] == ["c1", "c3"]
    assert [c.cluster_id for c in optional] == ["c2"]


from curriculum_agent.stages.plo_synthesis import (  # noqa: E402
    _OptionalDraftList,
    _PLODraft,
    _PLODraftList,
    _SmartSoftJudge,
    run,
)

_SOFT_OK = _SmartSoftJudge(
    specific_object_ok=True, achievable_ok=True, relevant_alignment_ok=True
)


def _core_draft(i: int) -> _PLODraft:
    from curriculum_agent.models import BloomLevel, Domain

    return _PLODraft(
        plo_id=f"PLO-{i}",
        statement_th=f"ออกแบบและพัฒนาระบบสารสนเทศสำหรับงาน {i} ได้อย่างมีประสิทธิภาพ",
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.CREATE,
        is_subject_specific=True,
        action_verb_th="ออกแบบ",
        source_cluster_ids=["c1"],
        source_evidence_ids=["e1"],
        rationale_th=f"ทักษะที่นายจ้างต้องการลำดับที่ {i}",
    )


def _optional_draft() -> _PLODraft:
    from curriculum_agent.models import BloomLevel, Domain

    return _PLODraft(
        plo_id="OPT-1",
        statement_th="ประยุกต์ใช้เทคโนโลยีเสริมเฉพาะทางในการพัฒนาระบบได้",
        domain=Domain.COGNITIVE,
        bloom_level=BloomLevel.APPLY,
        is_subject_specific=True,
        action_verb_th="ประยุกต์ใช้",
        source_cluster_ids=["c7"],
        source_evidence_ids=["e7"],
        rationale_th="ทักษะเสริมที่ตลาดต้องการเพิ่มเติม",
    )


def _clusters_core_plus_optional() -> list[dict]:
    clusters = [_cluster(f"c{i}", False) for i in range(1, 7)]
    clusters.append(_cluster("c7", True))
    return [c.model_dump(mode="json") for c in clusters]


async def test_run_optional_pass_produces_one_optional_plo(program_metadata: ProgramMetadata) -> None:
    state = {
        "program_id": program_metadata.program_id,
        "metadata": program_metadata.model_dump(mode="json"),
        "skill_clusters": _clusters_core_plus_optional(),
    }

    main_drafts = _PLODraftList(plos=[_core_draft(i) for i in range(1, 7)])
    optional_drafts = _OptionalDraftList(plos=[_optional_draft()])

    heavy_mock = AsyncMock(side_effect=[main_drafts, optional_drafts])

    with (
        patch("curriculum_agent.stages.plo_synthesis.complete_heavy", heavy_mock),
        patch(
            "curriculum_agent.stages.plo_synthesis.complete_light",
            new_callable=AsyncMock,
            return_value=_SOFT_OK,
        ),
        patch(
            "curriculum_agent.stages.plo_synthesis.PLORepository.bulk_insert",
            new_callable=AsyncMock,
        ),
    ):
        result = await run(state)

    assert heavy_mock.call_count == 2

    second_call_messages = heavy_mock.call_args_list[1].args[1]
    second_call_content = " ".join(m["content"] for m in second_call_messages)
    assert "c7" in second_call_content
    assert "c1" not in second_call_content

    optional_plos = [p for p in result["plos"] if p.get("is_optional") is True]
    assert len(optional_plos) == 1
