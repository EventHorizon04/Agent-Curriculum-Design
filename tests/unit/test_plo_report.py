from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import PLO, BloomLevel, KSECCategory, Need, SMARTCheck
from curriculum_agent.stages import plo_report as pr


def _need(nid: str, ksec: KSECCategory = KSECCategory.S) -> Need:
    return Need(
        need_id=nid,
        program_id="cs-test",
        statement_th=f"ตลาดต้องการ {nid}",
        ksec_category=ksec,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.7,
    )


def _plo(pid: str, need_ids: list[str], *, optional: bool = False) -> PLO:
    return PLO(
        plo_id=pid,
        program_id="cs-test",
        statement_th=f"วิเคราะห์งาน {pid} เพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=need_ids,
        source_evidence_ids=[f"E-{n}" for n in need_ids],
        rationale_th="ตรงกับความต้องการของตลาด",
        is_optional=optional,
    )


async def test_run_assembles_without_calling_an_llm(monkeypatch: pytest.MonkeyPatch):
    """The stage no longer classifies, so it must not reach the network at all."""
    monkeypatch.setattr(pr.NeedRepository, "list_by_program", AsyncMock(return_value=[_need("N1")]))
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", AsyncMock())

    state = await pr.run(
        {"program_id": "cs-test", "plos": [_plo("PLO1", ["N1"]).model_dump(mode="json")]}
    )

    assert state["report"]["counts"]["total"] == 1
    assert state["report"]["needs_by_id"]["N1"]["ksec_category"] == "S"


async def test_report_counts_split_core_and_optional(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        pr.NeedRepository, "list_by_program", AsyncMock(return_value=[_need("N1"), _need("N2")])
    )
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", AsyncMock())

    state = await pr.run(
        {
            "program_id": "cs-test",
            "plos": [
                _plo("PLO1", ["N1"]).model_dump(mode="json"),
                _plo("OPT1", ["N2"], optional=True).model_dump(mode="json"),
            ],
        }
    )

    assert state["report"]["counts"] == {"total": 2, "core": 1, "optional": 1, "escalated": 0}


async def test_run_without_plos_is_an_error(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ValueError, match="run PLO synthesis first"):
        await pr.run({"program_id": "cs-test", "plos": []})


def test_plo_no_longer_carries_the_classification_fields():
    for gone in (
        "is_subject_specific",
        "classification",
        "classification_method",
        "classification_rationale_th",
    ):
        assert gone not in PLO.model_fields
