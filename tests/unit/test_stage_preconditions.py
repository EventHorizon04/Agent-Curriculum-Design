"""Every stage reads the same input whether it was reached by the graph or by
the per-stage REST route the designer's page calls.

There are two ways to run a stage, and until now they disagreed about where a
stage's input comes from. The REST routes load it from the repositories and
answer 422 when there is nothing to load. The graph passed it forward in
`AgentState` alone, so a session that began after a designer had already run
some stages by hand started from nothing, walked silently through three stages
that each produced an empty list, and failed at `plo_synthesis` with a message
blaming `need_combination` — the one stage that had in fact just run and
returned normally.

The rule pinned here: a missing key means "this stage was entered directly" and
the stage loads its own input from the repository; an *empty* key means the
previous stage ran and produced nothing, and the stage says so instead of
loading older rows that would hide the failure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    ProgramMetadata,
    SkillGroup,
    StakeholderEvidence,
    StakeholderType,
)
from curriculum_agent.stages import need_combination as nc
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages import skill_extraction as se
from curriculum_agent.stages import skill_grouping as sg
from curriculum_agent.stages import stakeholder_needs as sn
from tests.support.needs import RATIONALE_TH

PROGRAM = "cs-test"


def _evidence(eid: str = "E1") -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id=eid,
        program_id=PROGRAM,
        stakeholder_type=StakeholderType.EMPLOYER,
        source_name="สถานประกอบการตัวอย่าง",
        raw_text_th="ต้องการบัณฑิตที่ออกแบบและพัฒนาระบบสารสนเทศขององค์กรได้",
    )


def _skill(sid: str = "S1", eid: str = "E1") -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id=PROGRAM,
        skill_name_th="ออกแบบฐานข้อมูล",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th="ออกแบบฐานข้อมูล",
        source_evidence_id=eid,
        source_stakeholder_type=StakeholderType.EMPLOYER,
        classification="need",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


def _metadata() -> dict[str, object]:
    """A full ProgramMetadata payload — plo_synthesis validates it before it
    looks at the Needs, so a partial dict fails on the wrong error."""
    return ProgramMetadata(
        program_id=PROGRAM,
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
    ).model_dump(mode="json")


def _need(nid: str = "N1") -> Need:
    return Need(
        need_id=nid,
        program_id=PROGRAM,
        statement_th="ต้องการบัณฑิตที่ออกแบบและดูแลระบบฐานข้อมูลขององค์กรให้ใช้งานได้จริง",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=1,
        demand_score=0.8,
    )


# --------------------------------------------------------------------------
# Sync: a missing key is filled from the repository, so a graph run picks up
# whatever the designer already produced by hand.
# --------------------------------------------------------------------------


async def test_stakeholder_needs_loads_evidence_when_state_carries_none(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        sn.EvidenceRepository, "list_by_program", AsyncMock(return_value=[_evidence()])
    )
    monkeypatch.setattr(sn.EvidenceRepository, "bulk_insert", AsyncMock())

    state = await sn.run({"program_id": PROGRAM})

    assert [e["evidence_id"] for e in state["classified_evidence"]] == ["E1"]


async def test_skill_extraction_loads_evidence_when_state_carries_none(
    monkeypatch: pytest.MonkeyPatch,
):
    loader = AsyncMock(return_value=[_evidence()])
    monkeypatch.setattr(se.EvidenceRepository, "list_by_program", loader)
    monkeypatch.setattr(se.SkillRepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(se.SkillRepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(se.LLMCacheRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(se.LLMCacheRepository, "set", AsyncMock())

    async def fake_extraction(model, messages, **kw):  # noqa: ANN001, ANN003
        return se._ExtractedSkillsResponse(
            skills=[
                se._SkillItem(
                    skill_name_th="ออกแบบฐานข้อมูล",
                    ksec_category="S",
                    bloom_level="apply",
                    evidence_span_th="ออกแบบและพัฒนาระบบสารสนเทศ",
                    confidence=0.9,
                )
            ]
        )

    monkeypatch.setattr(se, "complete_extraction", fake_extraction)

    state = await se.run({"program_id": PROGRAM, "metadata": {"field": "Computer Science"}})

    loader.assert_awaited_once_with(PROGRAM)
    assert len(state["extracted_skills"]) == 1


async def test_skill_grouping_loads_skills_when_state_carries_none(
    monkeypatch: pytest.MonkeyPatch,
):
    loader = AsyncMock(return_value=[_skill()])
    monkeypatch.setattr(sg.SkillRepository, "list_by_program", loader)
    monkeypatch.setattr(sg.SkillGroupRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(sg.SkillGroupRepository, "bulk_insert", AsyncMock())

    async def fake_cluster(names, target=None, program_context=None):  # noqa: ANN001
        return [[i] for i in range(len(names))]

    monkeypatch.setattr(sg, "cluster_skill_names", fake_cluster)

    state = await sg.run({"program_id": PROGRAM})

    loader.assert_awaited_once_with(PROGRAM)
    assert len(state["skill_groups"]) == 1


async def test_skill_grouping_refuses_an_empty_extraction_without_deleting_groups(
    monkeypatch: pytest.MonkeyPatch,
):
    """An empty `extracted_skills` is stage 2's answer, not a missing key.

    Loading the stored skills here would cluster the previous run's rows and
    report success, hiding an extraction that produced nothing.
    """
    loader = AsyncMock(return_value=[_skill()])
    delete = AsyncMock()
    monkeypatch.setattr(sg.SkillRepository, "list_by_program", loader)
    monkeypatch.setattr(sg.SkillGroupRepository, "delete_by_program", delete)

    with pytest.raises(ValueError, match="skill_extraction"):
        await sg.run({"program_id": PROGRAM, "extracted_skills": []})

    loader.assert_not_awaited()
    delete.assert_not_awaited()


def _group_dict() -> dict[str, object]:
    return SkillGroup(
        group_id="G1",
        program_id=PROGRAM,
        ksec=KSECCategory.S,
        skill_ids=["S1"],
        evidence_ids=["E1"],
        skill_names=["ออกแบบฐานข้อมูล"],
        skill_frequencies=[1],
        bloom_level=BloomLevel.APPLY,
        demand_score=0.5,
        is_optional=False,
        is_graduate=True,
        classification_coverage={"need": 1},
        stakeholder_coverage={StakeholderType.EMPLOYER: 1},
        stakeholder_types=[StakeholderType.EMPLOYER],
        in_field_skill_count=1,
        graduate_capability_skill_count=1,
    ).model_dump(mode="json")


async def test_need_combination_loads_groups_when_state_carries_none(
    monkeypatch: pytest.MonkeyPatch,
):
    stored = SkillGroup.model_validate(_group_dict())
    loader = AsyncMock(return_value=[stored])
    monkeypatch.setattr(nc.SkillGroupRepository, "list_by_program", loader)
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc._NeedStatement(
            statement_th="ต้องการบัณฑิตที่ออกแบบและดูแลระบบฐานข้อมูลขององค์กรให้ใช้งานได้จริง",
            statement_en="The market needs graduates who design and maintain databases",
            rationale_th=RATIONALE_TH,
        )

    monkeypatch.setattr(nc, "complete_need_combination", fake_summarize)

    state = await nc.run({"program_id": PROGRAM})

    loader.assert_awaited_once_with(PROGRAM)
    assert len(state["needs"]) == 1


async def test_need_combination_refuses_an_empty_group_list_without_deleting_needs(
    monkeypatch: pytest.MonkeyPatch,
):
    """An empty `skill_groups` is Agent 1's answer, not a missing key."""
    loader = AsyncMock(return_value=[SkillGroup.model_validate(_group_dict())])
    delete = AsyncMock()
    monkeypatch.setattr(nc.SkillGroupRepository, "list_by_program", loader)
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", delete)

    with pytest.raises(ValueError, match="กลุ่มทักษะ"):
        await nc.run({"program_id": PROGRAM, "skill_groups": []})

    loader.assert_not_awaited()
    delete.assert_not_awaited()


async def test_plo_synthesis_does_not_blame_need_combination_for_an_empty_result(
    monkeypatch: pytest.MonkeyPatch,
):
    """The message the failing session logged blamed the wrong stage.

    `need_combination` had run and returned normally with no groups; telling the
    designer to "run need_combination successfully" sends them to the one stage
    that is not at fault.
    """
    loader = AsyncMock(return_value=[_need()])
    monkeypatch.setattr(ps.NeedRepository, "list_by_program", loader)

    with pytest.raises(ValueError) as excinfo:
        await ps.run(
            {
                "program_id": PROGRAM,
                "metadata": _metadata(),
                "needs": [],
            }
        )

    loader.assert_not_awaited()
    assert "need_combination" in str(excinfo.value)
    assert "successfully" not in str(excinfo.value)


async def test_skill_extraction_separates_a_failed_provider_from_an_empty_reading(
    monkeypatch: pytest.MonkeyPatch,
):
    """Every call failing is not the same answer as every call succeeding empty.

    The first is infrastructure — a quota, a dead endpoint — and must stop the
    run where the cause is known. The second is a real reading of the evidence
    and keeps the existing behaviour: return empty, leave the stored rows alone.
    """
    monkeypatch.setattr(se.SkillRepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(se.SkillRepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(se.LLMCacheRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(se.LLMCacheRepository, "set", AsyncMock())

    state_in = {
        "program_id": PROGRAM,
        "metadata": {"field": "Computer Science"},
        "classified_evidence": [_evidence().model_dump(mode="json")],
    }

    async def every_call_fails(model, messages, **kw):  # noqa: ANN001, ANN003
        raise RuntimeError("402 in_flight_budget_exhausted")

    monkeypatch.setattr(se, "complete_extraction", every_call_fails)
    with pytest.raises(RuntimeError, match="ทุก"):
        await se.run(dict(state_in))

    async def every_call_reads_nothing(model, messages, **kw):  # noqa: ANN001, ANN003
        return se._ExtractedSkillsResponse(skills=[])

    monkeypatch.setattr(se, "complete_extraction", every_call_reads_nothing)
    state = await se.run(dict(state_in))
    assert state["extracted_skills"] == []


async def test_intake_leaves_the_key_unset_when_the_program_has_no_evidence_yet(
    monkeypatch: pytest.MonkeyPatch,
):
    """Intake preloads evidence, and an empty preload must not look like an answer.

    It wrote `raw_evidence` unconditionally, so a program with nothing recorded
    yet reached `stakeholder_needs` carrying `[]` — which by the rule above means
    "the previous stage ran and produced nothing" and is refused outright. But
    intake does not produce evidence; the designer does, on a later page, and an
    empty snapshot only says the table was empty at the moment the run started.
    Leaving the key unset lets stage 1 read the table when it actually runs.
    """
    from curriculum_agent.stages import intake

    monkeypatch.setattr(intake.ProgramRepository, "upsert", AsyncMock())
    monkeypatch.setattr(intake.EvidenceRepository, "list_by_program", AsyncMock(return_value=[]))

    state = await intake.run({"program_id": PROGRAM, "metadata": _metadata()})

    assert "raw_evidence" not in state


async def test_intake_still_passes_the_evidence_it_does_find(monkeypatch: pytest.MonkeyPatch):
    from curriculum_agent.stages import intake

    monkeypatch.setattr(intake.ProgramRepository, "upsert", AsyncMock())
    monkeypatch.setattr(
        intake.EvidenceRepository, "list_by_program", AsyncMock(return_value=[_evidence()])
    )

    state = await intake.run({"program_id": PROGRAM, "metadata": _metadata()})

    assert [e["evidence_id"] for e in state["raw_evidence"]] == ["E1"]
