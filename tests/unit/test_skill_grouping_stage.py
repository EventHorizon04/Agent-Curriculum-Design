"""Agent 1 (`skill_grouping`) clusters and stores; Agent 2 (`need_combination`)
writes one Need per stored group, concurrently."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.config import settings
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    SkillGroup,
    StakeholderType,
)
from curriculum_agent.stages import need_combination as nc
from curriculum_agent.stages import skill_grouping as sg
from tests.support.needs import RATIONALE_TH

PROGRAM = "cs-test"


def _skill(sid: str, name: str, ksec: KSECCategory, eid: str = "E1") -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id=PROGRAM,
        skill_name_th=name,
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=name,
        source_evidence_id=eid,
        source_stakeholder_type=StakeholderType.EMPLOYER,
        classification="need",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


def _group(i: int) -> SkillGroup:
    return SkillGroup(
        group_id=f"G{i}",
        program_id=PROGRAM,
        ksec=KSECCategory.S,
        skill_ids=[f"S{i}"],
        evidence_ids=[f"E{i}"],
        skill_names=[f"ทักษะปฏิบัติ{i}"],
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
    )


def _statement() -> nc._NeedStatement:
    return nc._NeedStatement(
        statement_th="ต้องการบัณฑิตที่ออกแบบและดูแลระบบสารสนเทศขององค์กรให้ใช้งานได้จริง",
        statement_en="The market needs graduates who maintain information systems",
        rationale_th=RATIONALE_TH,
    )


def _stub_need_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())


async def test_grouping_never_mixes_buckets(monkeypatch: pytest.MonkeyPatch):
    skills = [
        _skill("S1", "เขียนโปรแกรมเว็บ", KSECCategory.S),
        _skill("S2", "ออกแบบฐานข้อมูล", KSECCategory.S),
        _skill("K1", "หลักการวิศวกรรมซอฟต์แวร์", KSECCategory.K),
        _skill("K2", "โครงสร้างข้อมูล", KSECCategory.K),
        _skill("C1", "ความรับผิดชอบต่อหน้าที่", KSECCategory.C),
    ]

    async def one_cluster(names, target=None, program_context=None):  # noqa: ANN001
        return [list(range(len(names)))]

    monkeypatch.setattr(sg, "cluster_skill_names", one_cluster)

    groups = await sg.build_skill_groups(PROGRAM, skills, {"E1": "employer"})

    by_id = {s.skill_id: s for s in skills}
    assert len(groups) == 3
    for g in groups:
        buckets = {
            "EC"
            if by_id[sid].ksec_category in (KSECCategory.E, KSECCategory.C)
            else by_id[sid].ksec_category.value
            for sid in g.skill_ids
        }
        assert len(buckets) == 1
        assert g.program_id == PROGRAM
        assert g.group_id


async def test_grouping_refuses_empty_skill_list_before_delete(monkeypatch: pytest.MonkeyPatch):
    loader = AsyncMock(return_value=[_skill("S1", "ออกแบบฐานข้อมูล", KSECCategory.S)])
    delete = AsyncMock()
    monkeypatch.setattr(sg.SkillRepository, "list_by_program", loader)
    monkeypatch.setattr(sg.SkillGroupRepository, "delete_by_program", delete)

    with pytest.raises(ValueError):
        await sg.run({"program_id": PROGRAM, "extracted_skills": []})

    delete.assert_not_awaited()
    loader.assert_not_awaited()


async def test_need_combination_reads_stored_groups_without_clustering(
    monkeypatch: pytest.MonkeyPatch,
):
    async def boom(*a, **kw):  # noqa: ANN002, ANN003
        raise AssertionError("need_combination must not cluster")

    monkeypatch.setattr(sg, "cluster_skill_names", boom)
    monkeypatch.setattr(nc, "complete_need_combination", AsyncMock(return_value=_statement()))
    _stub_need_repo(monkeypatch)
    groups = [_group(i) for i in range(3)]

    state = await nc.run(
        {"program_id": PROGRAM, "skill_groups": [g.model_dump(mode="json") for g in groups]}
    )

    assert [n["member_skill_ids"] for n in state["needs"]] == [g.skill_ids for g in groups]


async def test_need_combination_refuses_when_no_groups(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(nc.SkillGroupRepository, "list_by_program", AsyncMock(return_value=[]))
    delete = AsyncMock()
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", delete)

    with pytest.raises(ValueError) as err:
        await nc.run({"program_id": PROGRAM})

    assert str(err.value) == ("ยังไม่มีกลุ่มทักษะสำหรับโปรแกรมนี้ กรุณารันขั้นสกัดทักษะใหม่ก่อนรวมเป็น Need")
    delete.assert_not_awaited()


async def test_statement_calls_run_concurrently(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "llm_max_concurrency", 5)
    in_flight = 0
    peak = 0
    delays = iter([0.06, 0.03, 0.0])

    async def slow(model, messages, **kw):  # noqa: ANN001, ANN003
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(next(delays))
        in_flight -= 1
        return _statement()

    monkeypatch.setattr(nc, "complete_need_combination", slow)
    _stub_need_repo(monkeypatch)
    groups = [_group(i) for i in range(3)]

    state = await nc.run(
        {"program_id": PROGRAM, "skill_groups": [g.model_dump(mode="json") for g in groups]}
    )

    assert peak > 1
    # The first group finishes last, yet Need order is still group order.
    assert [n["member_skill_ids"] for n in state["needs"]] == [["S0"], ["S1"], ["S2"]]


async def test_one_failing_statement_falls_back_without_costing_the_others(
    monkeypatch: pytest.MonkeyPatch,
):
    calls = 0

    async def flaky(model, messages, **kw):  # noqa: ANN001, ANN003
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("endpoint down")
        return _statement()

    monkeypatch.setattr(nc, "complete_need_combination", flaky)
    _stub_need_repo(monkeypatch)
    groups = [_group(i) for i in range(3)]

    state = await nc.run(
        {"program_id": PROGRAM, "skill_groups": [g.model_dump(mode="json") for g in groups]}
    )

    marked = [n["statement_th"].startswith(nc._PROVIDER_MARKER_TH) for n in state["needs"]]
    assert marked == [False, True, False]


def _mixed_skills() -> list[ExtractedSkill]:
    return [
        _skill("S1", "เขียนโปรแกรมเว็บ", KSECCategory.S),
        _skill("S2", "ออกแบบฐานข้อมูล", KSECCategory.S),
        _skill("K1", "หลักการวิศวกรรมซอฟต์แวร์", KSECCategory.K),
        _skill("K2", "โครงสร้างข้อมูล", KSECCategory.K),
        _skill("C1", "ความรับผิดชอบต่อหน้าที่", KSECCategory.C),
    ]


def _shape(groups: list[SkillGroup]) -> list[tuple]:
    """Everything but the random group id: membership, order and scores."""
    return [
        (
            g.is_graduate,
            g.ksec,
            g.skill_ids,
            g.skill_names,
            g.skill_frequencies,
            g.evidence_ids,
            g.demand_score,
        )
        for g in groups
    ]


async def test_bucket_clustering_calls_overlap_and_groups_match_sequential(
    monkeypatch: pytest.MonkeyPatch,
):
    skills = _mixed_skills()
    in_flight = 0
    peak = 0
    all_started = asyncio.Event()

    async def answer(names, target=None, program_context=None):  # noqa: ANN001
        # One singleton group per name, reversed, so order is observable.
        return [[i] for i in reversed(range(len(names)))]

    async def sequential(names, target=None, program_context=None):  # noqa: ANN001
        return await answer(names, target, program_context)

    monkeypatch.setattr(settings, "llm_max_concurrency", 1)
    monkeypatch.setattr(sg, "cluster_skill_names", sequential)
    reference = await sg.build_skill_groups(PROGRAM, skills, {"E1": "employer"})
    assert len(reference) >= 3

    started = 0

    async def overlapping(names, target=None, program_context=None):  # noqa: ANN001
        nonlocal in_flight, peak, started
        in_flight += 1
        started += 1
        peak = max(peak, in_flight)
        if started >= 3:
            all_started.set()
        # Completes only once every bucket has started: a sequential loop would
        # wait here forever, so this fails by timeout rather than by luck.
        await asyncio.wait_for(all_started.wait(), timeout=2)
        in_flight -= 1
        return await answer(names, target, program_context)

    monkeypatch.setattr(settings, "llm_max_concurrency", 5)
    monkeypatch.setattr(sg, "cluster_skill_names", overlapping)
    concurrent = await sg.build_skill_groups(PROGRAM, skills, {"E1": "employer"})

    assert peak >= 3
    assert _shape(concurrent) == _shape(reference)


async def test_bucket_clustering_respects_the_concurrency_ceiling(
    monkeypatch: pytest.MonkeyPatch,
):
    in_flight = 0
    peak = 0

    async def counting(names, target=None, program_context=None):  # noqa: ANN001
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return [list(range(len(names)))]

    monkeypatch.setattr(settings, "llm_max_concurrency", 2)
    monkeypatch.setattr(sg, "cluster_skill_names", counting)
    await sg.build_skill_groups(PROGRAM, _mixed_skills(), {"E1": "employer"})
    assert peak == 2


async def test_a_failing_bucket_cancels_the_other_in_flight_buckets(
    monkeypatch: pytest.MonkeyPatch,
):
    started = 0
    cancelled = 0
    first_ran = asyncio.Event()

    async def one_fails(names, target=None, program_context=None):  # noqa: ANN001
        nonlocal started, cancelled
        started += 1
        if started == 1:
            first_ran.set()
            raise RuntimeError("clustering down")
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled += 1
            raise
        return [list(range(len(names)))]

    monkeypatch.setattr(settings, "llm_max_concurrency", 5)
    monkeypatch.setattr(sg, "cluster_skill_names", one_fails)
    with pytest.raises(RuntimeError, match="clustering down"):
        await sg.build_skill_groups(PROGRAM, _mixed_skills(), {"E1": "employer"})
    assert first_ran.is_set()
    assert started >= 3
    assert cancelled == started - 1
