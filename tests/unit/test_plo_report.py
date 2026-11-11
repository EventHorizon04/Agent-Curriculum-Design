from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from curriculum_agent.models import PLO, BloomLevel, KSECCategory, Need, SMARTCheck
from curriculum_agent.stages import plo_report as pr
from curriculum_agent.stages.plo_review_facts import need_demands, plo_fingerprint


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


@pytest.fixture(autouse=True)
def _no_stored_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The report reads every Need (for the excluded list); default to none."""
    monkeypatch.setattr(pr.NeedRepository, "list_by_program", AsyncMock(return_value=[]))


async def _run(monkeypatch: pytest.MonkeyPatch, state: dict) -> dict:
    """Run the stage with the PLO repository holding `state["plos"]` (the report
    reads storage, not the state)."""
    stored = [PLO.model_validate(d) for d in state.get("plos", [])]
    monkeypatch.setattr(pr.PLORepository, "list_by_program", AsyncMock(return_value=stored))
    return await pr.run(state)  # type: ignore[arg-type]


async def test_run_assembles_without_calling_an_llm(monkeypatch: pytest.MonkeyPatch):
    """The stage no longer classifies, so it must not reach the network at all."""
    monkeypatch.setattr(
        pr.NeedRepository, "list_active_by_program", AsyncMock(return_value=[_need("N1")])
    )
    monkeypatch.setattr(pr.PLOReportRepository, "upsert", AsyncMock())

    plo_dict = _plo("PLO1", ["N1"]).model_dump(mode="json")
    state = await _run(monkeypatch, {"program_id": "cs-test", "plos": [plo_dict]})

    assert state["report"]["counts"]["total"] == 1
    assert state["report"]["needs_by_id"]["N1"]["ksec_categories"] == ["S"]

    # Identity, not just equality: the input list already equals the
    # reconstructed one by value (nothing mutates it), so an `==` check would
    # stay green even if the `state["plos"] = report["plos"]` assignment were
    # deleted. `is` only holds if that assignment actually ran.
    assert state["plos"] is state["report"]["plos"]


async def test_report_counts_split_core_and_optional(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        pr.NeedRepository,
        "list_active_by_program",
        AsyncMock(return_value=[_need("N1"), _need("N2")]),
    )
    monkeypatch.setattr(pr.PLOReportRepository, "upsert", AsyncMock())

    state = await _run(
        monkeypatch,
        {
            "program_id": "cs-test",
            "plos": [
                _plo("PLO1", ["N1"]).model_dump(mode="json"),
                _plo("OPT1", ["N2"], optional=True).model_dump(mode="json"),
            ],
        },
    )

    assert state["report"]["counts"] == {
        "total": 2,
        "core": 1,
        "optional": 1,
        "escalated": 0,
        "stale": 0,
        "code_only": 0,
        "needs_not_synthesized": 0,
        "needs_excluded": 0,
    }


async def test_report_counts_surface_escalated_plos(monkeypatch: pytest.MonkeyPatch):
    """`escalated` exists to surface repair work at the checkpoint — pin it
    against a set that actually contains one, not just the all-zero case."""
    monkeypatch.setattr(
        pr.NeedRepository,
        "list_active_by_program",
        AsyncMock(return_value=[_need("N1"), _need("N2")]),
    )
    monkeypatch.setattr(pr.PLOReportRepository, "upsert", AsyncMock())

    state = await _run(
        monkeypatch,
        {
            "program_id": "cs-test",
            "plos": [
                _plo("PLO1", ["N1"]).model_dump(mode="json"),
                _plo("PLO2", ["N2"], escalated=True).model_dump(mode="json"),
            ],
        },
    )

    assert state["report"]["counts"] == {
        "total": 2,
        "core": 2,
        "optional": 0,
        "escalated": 1,
        "stale": 0,
        "code_only": 0,
        "needs_not_synthesized": 0,
        "needs_excluded": 0,
    }
    # Escalated PLOs must stay visible, never dropped from the assembled set.
    assert {p["plo_id"] for p in state["report"]["plos"]} == {"PLO1", "PLO2"}


async def test_unresolved_need_id_logs_a_warning_naming_the_plo(monkeypatch: pytest.MonkeyPatch):
    """A PLO citing a Need id the repository doesn't have would otherwise ship
    an untraceable, silently incomplete drill-down. This is the report stage's
    replacement for what the old classification path surfaced as
    method="fallback" — there is no classification step left to carry that
    signal, so the warning is the whole mechanism now."""
    monkeypatch.setattr(pr.NeedRepository, "list_active_by_program", AsyncMock(return_value=[]))
    monkeypatch.setattr(pr.PLOReportRepository, "upsert", AsyncMock())

    with patch.object(pr, "logger") as mock_logger:
        await _run(
            monkeypatch,
            {"program_id": "cs-test", "plos": [_plo("PLO1", ["ghost"]).model_dump(mode="json")]},
        )

    warnings = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert any("PLO1" in w and "ghost" in w for w in warnings)


async def test_run_without_plos_is_an_error(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(ValueError, match="run PLO synthesis first"):
        await _run(monkeypatch, {"program_id": "cs-test", "plos": []})


def test_plo_no_longer_carries_the_classification_fields():
    for gone in (
        "is_subject_specific",
        "classification",
        "classification_method",
        "classification_rationale_th",
    ):
        assert gone not in PLO.model_fields


async def test_the_report_no_longer_carries_a_review(monkeypatch: pytest.MonkeyPatch):
    """The QA review is stage 06 and runs after the report; the report neither
    reads nor returns one, even when an old one is on the state."""
    monkeypatch.setattr(
        pr.NeedRepository, "list_active_by_program", AsyncMock(return_value=[_need("N1")])
    )
    monkeypatch.setattr(pr.PLOReportRepository, "upsert", AsyncMock())
    state = await _run(
        monkeypatch,
        {
            "program_id": "cs-test",
            "plos": [_plo("PLO1", ["N1"]).model_dump(mode="json")],
            "plo_review": {"summary_th": "เก่า"},
        },
    )
    assert "review" not in state["report"]
    assert "review_stale" not in state["report"]


async def test_plo_report_stores_row_and_does_not_bulk_insert(monkeypatch: pytest.MonkeyPatch):
    upsert = AsyncMock()
    bulk_insert = AsyncMock()
    needs = [_need("N1")]
    plo = _plo("PLO1", ["N1"])
    monkeypatch.setattr(pr.NeedRepository, "list_active_by_program", AsyncMock(return_value=needs))
    monkeypatch.setattr(pr.PLOReportRepository, "upsert", upsert)
    monkeypatch.setattr(pr.PLORepository, "bulk_insert", bulk_insert)
    state = await _run(
        monkeypatch, {"program_id": "cs-test", "plos": [plo.model_dump(mode="json")]}
    )

    bulk_insert.assert_not_awaited()
    upsert.assert_awaited_once()
    row = upsert.await_args.args[0]
    assert row.program_id == "cs-test"
    assert row.report == state["report"]
    assert row.plo_fingerprint == plo_fingerprint([plo], need_demands(needs))
    assert row.created_at.tzinfo is None
    assert state["current_stage"] == "plo_report"


async def test_plo_report_reads_stored_not_state(monkeypatch: pytest.MonkeyPatch):
    """A statement edited while the session was suspended must reach the report."""
    monkeypatch.setattr(
        pr.NeedRepository, "list_active_by_program", AsyncMock(return_value=[_need("N1")])
    )
    monkeypatch.setattr(pr.PLOReportRepository, "upsert", AsyncMock())
    stored = _plo("PLO1", ["N1"]).model_copy(update={"statement_th": "วิเคราะห์ข้อมูลที่ผู้ออกแบบแก้แล้วได้"})
    monkeypatch.setattr(pr.PLORepository, "list_by_program", AsyncMock(return_value=[stored]))

    state = await pr.run(
        {"program_id": "cs-test", "plos": [_plo("PLO1", ["N1"]).model_dump(mode="json")]}
    )

    assert state["report"]["plos"][0]["statement_th"] == stored.statement_th
    assert state["plos"][0]["statement_th"] == stored.statement_th


def _excluded(nid: str, at: datetime, **kw) -> Need:
    return _need(nid).model_copy(update={"excluded_at": at, **kw})


async def _report_with(monkeypatch: pytest.MonkeyPatch, active: list[Need], every: list[Need]):
    monkeypatch.setattr(pr.NeedRepository, "list_active_by_program", AsyncMock(return_value=active))
    monkeypatch.setattr(pr.NeedRepository, "list_by_program", AsyncMock(return_value=every))
    monkeypatch.setattr(pr.PLOReportRepository, "upsert", AsyncMock())
    state = await _run(
        monkeypatch,
        {"program_id": "cs-test", "plos": [_plo("PLO1", ["N1"]).model_dump(mode="json")]},
    )
    return state["report"]


async def test_report_lists_excluded_needs(monkeypatch: pytest.MonkeyPatch):
    n1 = _need("N1")
    late = _excluded("N3", datetime(2026, 11, 5, 9, 0))
    early_b = _excluded("N2b", datetime(2026, 11, 1, 8, 0))
    early_a = _excluded("N2a", datetime(2026, 11, 1, 8, 0))
    report = await _report_with(monkeypatch, [n1], [n1, late, early_b, early_a])

    assert [x["need_id"] for x in report["needs_excluded"]] == ["N2a", "N2b", "N3"]
    first = report["needs_excluded"][0]
    assert set(first) == {
        "need_id",
        "statement_th",
        "ksec_categories",
        "demand_score",
        "excluded_at",
    }
    assert first["excluded_at"] == "2026-11-01T08:00:00"
    assert first["ksec_categories"] == ["S"]
    assert report["counts"]["needs_excluded"] == 3


async def test_merged_original_is_not_listed_as_excluded(monkeypatch: pytest.MonkeyPatch):
    n1 = _need("N1")
    merged_away = _excluded("O1", datetime(2026, 11, 1), merged_into="N1")
    report = await _report_with(monkeypatch, [n1], [n1, merged_away])

    assert report["needs_excluded"] == []
    assert report["counts"]["needs_excluded"] == 0


async def test_excluded_need_is_not_also_not_synthesized(monkeypatch: pytest.MonkeyPatch):
    n1, n2 = _need("N1"), _need("N2")
    gone = _excluded("X1", datetime(2026, 11, 1))
    report = await _report_with(monkeypatch, [n1, n2], [n1, n2, gone])

    assert report["needs_not_synthesized"] == ["N2"]
    assert [x["need_id"] for x in report["needs_excluded"]] == ["X1"]
    assert "X1" not in report["needs_by_id"]


async def test_report_without_exclusions_has_empty_list(monkeypatch: pytest.MonkeyPatch):
    n1 = _need("N1")
    report = await _report_with(monkeypatch, [n1], [n1])

    assert report["needs_excluded"] == []
    assert report["counts"]["needs_excluded"] == 0
