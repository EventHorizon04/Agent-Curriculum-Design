from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory
from curriculum_agent.stages import need_combination as nc


def _skill(name: str, ksec: KSECCategory, sid: str, eid: str) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="cs-test",
        skill_name_th=name,
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=name,
        source_evidence_id=eid,
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


@pytest.fixture
def skills() -> list[ExtractedSkill]:
    return [
        _skill("เขียนโปรแกรมเว็บ", KSECCategory.SS, "S1", "E1"),
        _skill("ออกแบบฐานข้อมูล", KSECCategory.SS, "S2", "E1"),
        _skill("ทำงานเป็นทีม", KSECCategory.GS, "S3", "E2"),
        _skill("ยึดถือจรรยาบรรณ", KSECCategory.E, "S4", "E3"),
    ]


@pytest.fixture
def evidence() -> list[dict[str, str]]:
    return [
        {"evidence_id": "E1", "classification": "requirement", "stakeholder_type": "employer"},
        {"evidence_id": "E2", "classification": "need", "stakeholder_type": "alumni"},
        {"evidence_id": "E3", "classification": "want", "stakeholder_type": "community"},
    ]


def _patch_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cluster each bucket into singletons; summarize echoes the first skill name."""

    async def fake_cluster(names: list[str]) -> list[list[int]]:
        return [[i] for i in range(len(names))]

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc._NeedStatement(
            statement_th="สามารถทำงานตามที่ตลาดต้องการ", statement_en="Market capability"
        )

    monkeypatch.setattr(nc, "cluster_skill_names", fake_cluster)
    monkeypatch.setattr(nc, "complete_light", fake_summarize)


def _patch_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every persistence call the stage makes.

    `run` clears the program's previous Needs before inserting the new set, so a
    test stubbing only bulk_insert leaves the delete reaching a real database.
    """
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())


async def test_every_need_holds_exactly_one_ksec_tag(
    skills: list[ExtractedSkill], evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    _patch_llm(monkeypatch)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    needs = state["needs"]
    assert needs, "expected at least one Need"
    skills_by_id = {s.skill_id: s for s in skills}
    for need in needs:
        tags = {skills_by_id[sid].ksec_category.value for sid in need["member_skill_ids"]}
        assert len(tags) == 1
        assert tags == {need["ksec_category"]}


async def test_want_only_need_is_marked_optional(
    skills: list[ExtractedSkill], evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    _patch_llm(monkeypatch)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    ethics = [n for n in state["needs"] if n["ksec_category"] == "E"]
    assert ethics and all(n["is_optional"] for n in ethics)


async def test_freq_counts_mentions_not_unique_names(
    evidence: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch
):
    # Same capability named twice in one bucket, clustered together.
    dupes = [
        _skill("วิเคราะห์ข้อมูล", KSECCategory.SS, "S1", "E1"),
        _skill("วิเคราะห์ข้อมูล", KSECCategory.SS, "S2", "E2"),
    ]

    async def one_cluster(names: list[str]) -> list[list[int]]:
        return [list(range(len(names)))]

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc._NeedStatement(statement_th="วิเคราะห์ข้อมูลได้", statement_en="Analyse data")

    monkeypatch.setattr(nc, "cluster_skill_names", one_cluster)
    monkeypatch.setattr(nc, "complete_light", fake_summarize)
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in dupes],
        }
    )

    assert len(state["needs"]) == 1
    assert state["needs"][0]["freq"] == 2  # two mentions, one name


async def test_empty_skills_yields_no_needs(monkeypatch: pytest.MonkeyPatch):
    _patch_repo(monkeypatch)
    state = await nc.run(
        {"program_id": "cs-test", "classified_evidence": [], "extracted_skills": []}
    )
    assert state["needs"] == []


def _group(name: str, demand: float, eid: str) -> nc._Group:
    return nc._Group(
        ksec=KSECCategory.SS,
        skill_ids=[f"S-{name}"],
        evidence_ids=[eid],
        skill_names=[name],
        bloom_level=BloomLevel.APPLY,
        demand_score=demand,
        is_optional=False,
        classification_coverage={"need": 1},
        stakeholder_coverage={"employer": 1},
    )


def test_fuse_unions_evidence_and_takes_max_bloom():
    a = _group("a", 0.4, "E1")
    b = _group("b", 0.9, "E2").model_copy(update={"bloom_level": BloomLevel.CREATE})
    fused = nc._fuse([a, b])
    assert set(fused.evidence_ids) == {"E1", "E2"}
    assert fused.bloom_level is BloomLevel.CREATE
    assert fused.demand_score == 0.9
    assert sorted(fused.skill_ids) == ["S-a", "S-b"]


def test_fuse_by_demand_hits_the_limit_and_keeps_all_evidence():
    bucket = [_group(f"g{i}", i / 10, f"E{i}") for i in range(7)]
    fused = nc._fuse_by_demand(bucket, 3)
    assert len(fused) == 3
    all_evidence = {e for g in fused for e in g.evidence_ids}
    assert all_evidence == {f"E{i}" for i in range(7)}


async def test_merge_bucket_falls_back_when_llm_returns_wrong_count(
    monkeypatch: pytest.MonkeyPatch,
):
    bucket = [_group(f"g{i}", i / 10, f"E{i}") for i in range(5)]
    all_skill_ids = {sid for g in bucket for sid in g.skill_ids}
    all_evidence_ids = {eid for g in bucket for eid in g.evidence_ids}

    async def bad_merge(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc.MergeGroupsResponse(groups=[[0, 1, 2, 3, 4]])  # 1 group, asked for 2

    monkeypatch.setattr(nc, "complete_heavy", bad_merge)
    merged = await nc._merge_bucket(bucket, 2, KSECCategory.SS)
    assert len(merged) == 2
    # A fallback that truncates the ranked list instead of fusing (`return
    # ranked[:limit]`) still yields the right count here but silently drops
    # the surplus groups' evidence — exactly the traceability bug `_fuse`
    # exists to prevent. Every input id must survive into the output.
    assert {sid for g in merged for sid in g.skill_ids} == all_skill_ids
    assert {eid for g in merged for eid in g.evidence_ids} == all_evidence_ids


async def test_merge_bucket_falls_back_when_llm_raises(monkeypatch: pytest.MonkeyPatch):
    bucket = [_group(f"g{i}", i / 10, f"E{i}") for i in range(4)]
    all_skill_ids = {sid for g in bucket for sid in g.skill_ids}
    all_evidence_ids = {eid for g in bucket for eid in g.evidence_ids}

    async def boom(model, messages, **kw):  # noqa: ANN001, ANN003
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(nc, "complete_heavy", boom)
    merged = await nc._merge_bucket(bucket, 2, KSECCategory.SS)
    assert len(merged) == 2
    # Same traceability pin as the wrong-count test above: a truncating
    # fallback would still land on the right count while dropping evidence.
    assert {sid for g in merged for sid in g.skill_ids} == all_skill_ids
    assert {eid for g in merged for eid in g.evidence_ids} == all_evidence_ids


async def test_merge_bucket_uses_llm_grouping_when_count_matches(
    monkeypatch: pytest.MonkeyPatch,
):
    # Demand scores are deliberately distinct (no ties). Demand-ranked fusion
    # (_fuse_by_demand) would keep the two highest-demand groups ("a" 0.9 and
    # "c" 0.8) and fold the surplus into them by rank — pairing a-with-d and
    # c-with-b. The mocked LLM instead returns a-with-b and c-with-d, a
    # pairing demand-ranked fusion would never choose, so this test only
    # passes if the LLM grouping path actually ran. Do not "simplify" these
    # scores back to a tie — that lets the fallback produce the same shape
    # and hides a mutation that always skips the LLM path.
    bucket = [
        _group("a", 0.9, "E-a"),
        _group("b", 0.1, "E-b"),
        _group("c", 0.8, "E-c"),
        _group("d", 0.2, "E-d"),
    ]

    async def good_merge(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc.MergeGroupsResponse(groups=[[0, 1], [2, 3]])  # a+b, c+d

    monkeypatch.setattr(nc, "complete_heavy", good_merge)
    merged = await nc._merge_bucket(bucket, 2, KSECCategory.SS)
    assert len(merged) == 2
    actual_pairs = {frozenset(g.skill_names) for g in merged}
    assert actual_pairs == {frozenset({"a", "b"}), frozenset({"c", "d"})}
