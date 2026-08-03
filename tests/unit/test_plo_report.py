from __future__ import annotations

from unittest.mock import AsyncMock, patch

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


def _plo(pid: str, need_ids: list[str], *, optional: bool = False, escalated: bool = False) -> PLO:
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
        smart_escalated=escalated,
    )


async def test_run_assembles_without_calling_an_llm(monkeypatch: pytest.MonkeyPatch):
    """The stage no longer classifies, so it must not reach the network at all."""
    monkeypatch.setattr(pr.NeedRepository, "list_by_program", AsyncMock(return_value=[_need("N1")]))
    bulk_insert = AsyncMock()
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", bulk_insert)

    plo_dict = _plo("PLO1", ["N1"]).model_dump(mode="json")
    state = await pr.run({"program_id": "cs-test", "plos": [plo_dict]})

    assert state["report"]["counts"]["total"] == 1
    assert state["report"]["needs_by_id"]["N1"]["ksec_category"] == "S"

    # The stage still persists the (unchanged) PLOs on every run — that write is
    # what keeps a checkpoint replay idempotent even if the resumed state's PLOs
    # were never actually committed. Deleting the bulk_insert call or the
    # state["plos"] assignment below must not leave this test green.
    bulk_insert.assert_awaited_once()
    # Identity, not just equality: the input list already equals the
    # reconstructed one by value (nothing mutates it), so an `==` check would
    # stay green even if the `state["plos"] = report["plos"]` assignment were
    # deleted. `is` only holds if that assignment actually ran.
    assert state["plos"] is state["report"]["plos"]


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


async def test_report_counts_surface_escalated_plos(monkeypatch: pytest.MonkeyPatch):
    """`escalated` exists to surface repair work at the checkpoint — pin it
    against a set that actually contains one, not just the all-zero case."""
    monkeypatch.setattr(
        pr.NeedRepository, "list_by_program", AsyncMock(return_value=[_need("N1"), _need("N2")])
    )
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", AsyncMock())

    state = await pr.run(
        {
            "program_id": "cs-test",
            "plos": [
                _plo("PLO1", ["N1"]).model_dump(mode="json"),
                _plo("PLO2", ["N2"], escalated=True).model_dump(mode="json"),
            ],
        }
    )

    assert state["report"]["counts"] == {"total": 2, "core": 2, "optional": 0, "escalated": 1}
    # Escalated PLOs must stay visible, never dropped from the assembled set.
    assert {p["plo_id"] for p in state["report"]["plos"]} == {"PLO1", "PLO2"}


async def test_unresolved_need_id_logs_a_warning_naming_the_plo(monkeypatch: pytest.MonkeyPatch):
    """A PLO citing a Need id the repository doesn't have would otherwise ship
    an untraceable, silently incomplete drill-down. This is the report stage's
    replacement for what the old classification path surfaced as
    method="fallback" — there is no classification step left to carry that
    signal, so the warning is the whole mechanism now."""
    monkeypatch.setattr(pr.NeedRepository, "list_by_program", AsyncMock(return_value=[]))
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", AsyncMock())

    with patch.object(pr, "logger") as mock_logger:
        await pr.run(
            {"program_id": "cs-test", "plos": [_plo("PLO1", ["ghost"]).model_dump(mode="json")]}
        )

    warnings = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert any("PLO1" in w and "ghost" in w for w in warnings)


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
