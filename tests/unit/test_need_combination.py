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


async def test_no_upper_cap_on_core_needs(monkeypatch: pytest.MonkeyPatch):
    """One KSEC bucket producing more than the old 10-Need cap must not be merged down.

    Project policy dropped MAX_NEEDS: every core group clustering finds becomes its
    own Need, regardless of how many that is.
    """
    many_skills = [_skill(f"ทักษะที่ {i}", KSECCategory.SS, f"S{i}", "E1") for i in range(15)]
    evidence = [
        {"evidence_id": "E1", "classification": "requirement", "stakeholder_type": "employer"}
    ]

    _patch_llm(monkeypatch)  # clusters each name into its own singleton
    _patch_repo(monkeypatch)

    state = await nc.run(
        {
            "program_id": "cs-test",
            "classified_evidence": evidence,
            "extracted_skills": [s.model_dump(mode="json") for s in many_skills],
        }
    )

    assert len(state["needs"]) == 15
