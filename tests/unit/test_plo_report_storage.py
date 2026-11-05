"""plo_reports and plos.designer_edited_at (phase 6): the repository side.

Same mocked session as test_superseded_plos.py.
"""

from __future__ import annotations

from datetime import datetime

from curriculum_agent.data.orm import PLOReportTable, PLOTable
from curriculum_agent.data.repositories import (
    PLOReportRepository,
    PLORepository,
    ProgramRepository,
    _row_to_dict,
)
from curriculum_agent.models import PLOReport
from tests.unit.test_superseded_plos import PID, _patched, _plo, _Session

T0 = datetime(2026, 11, 5, 9, 30, 0)


def _report(**kw: object) -> PLOReport:
    base: dict[str, object] = {
        "program_id": PID,
        "plo_fingerprint": "f" * 64,
        "created_at": T0,
        "report": {"summary_th": "ภาพรวม", "plos": [{"plo_id": "PLO1"}]},
    }
    base.update(kw)
    return PLOReport(**base)  # type: ignore[arg-type]


async def test_bulk_insert_round_trips_designer_edited_at() -> None:
    plo = _plo("PLO1").model_copy(update={"designer_edited_at": T0})
    session = _Session()
    with _patched(session):
        await PLORepository().bulk_insert([plo])
    (row,) = [a for a in session.added if isinstance(a, PLOTable)]
    # The ORM DateTime column rejects the ISO string model_dump(mode="json") makes.
    assert row.designer_edited_at == T0
    assert isinstance(row.designer_edited_at, datetime)

    session = _Session(select_rows=[row])
    with _patched(session):
        (back,) = await PLORepository().list_by_program(PID)
    assert back.designer_edited_at == T0
    assert back.model_dump(mode="json")["designer_edited_at"] == "2026-11-05T09:30:00+00:00"


async def test_bulk_insert_updating_an_existing_row_hands_it_a_datetime() -> None:
    existing = PLOTable(**_plo("PLO1").model_dump(mode="json"))
    session = _Session()
    session.mock.get.return_value = existing
    plo = _plo("PLO1").model_copy(update={"designer_edited_at": T0})
    with _patched(session):
        await PLORepository().bulk_insert([plo])
    assert existing.designer_edited_at == T0


async def test_bulk_insert_without_an_edit_stores_none() -> None:
    session = _Session()
    with _patched(session):
        await PLORepository().bulk_insert([_plo("PLO1")])
    (row,) = [a for a in session.added if isinstance(a, PLOTable)]
    assert row.designer_edited_at is None


async def test_replace_hands_the_orm_a_datetime_and_snapshots_json_safely() -> None:
    old = PLOTable(**_plo("PLO1").model_dump(mode="json"))
    old.designer_edited_at = T0
    session = _Session(select_rows=[old])
    new = _plo("PLO1").model_copy(update={"designer_edited_at": T0})
    with _patched(session):
        await PLORepository().replace(PID, ["PLO1"], [new])
    (added,) = [a for a in session.added if isinstance(a, PLOTable)]
    assert added.designer_edited_at == T0
    (history,) = [a for a in session.added if not isinstance(a, PLOTable)]
    # JSONB snapshot: a datetime object would not serialise.
    assert history.snapshot["designer_edited_at"] == T0.isoformat()


async def test_plo_report_upsert_get_replace() -> None:
    session = _Session()
    with _patched(session):
        await PLOReportRepository().upsert(_report())
    (row,) = [a for a in session.added if isinstance(a, PLOReportTable)]
    assert (row.program_id, row.plo_fingerprint, row.created_at) == (PID, "f" * 64, T0)
    assert row.report == {"summary_th": "ภาพรวม", "plos": [{"plo_id": "PLO1"}]}

    session = _Session()
    session.mock.get.return_value = row
    with _patched(session):
        got = await PLOReportRepository().get(PID)
    assert got == _report()

    # A second upsert replaces the stored row in place rather than adding one.
    session = _Session()
    session.mock.get.return_value = row
    later = datetime(2026, 11, 5, 10, 0, 0)
    with _patched(session):
        await PLOReportRepository().upsert(
            _report(plo_fingerprint="a" * 64, created_at=later, report={"summary_th": "ใหม่"})
        )
    assert not session.added
    assert (row.plo_fingerprint, row.created_at, row.report) == (
        "a" * 64,
        later,
        {"summary_th": "ใหม่"},
    )
    assert session.commits == 1


async def test_plo_report_get_is_none_when_absent() -> None:
    session = _Session()
    with _patched(session):
        assert await PLOReportRepository().get(PID) is None


def test_plo_report_json_carries_the_offset() -> None:
    assert _report().model_dump(mode="json")["created_at"] == "2026-11-05T09:30:00+00:00"


async def test_plo_report_delete_by_program() -> None:
    session = _Session()
    with _patched(session):
        await PLOReportRepository().delete_by_program(PID)
    assert any(s.startswith("delete from plo_reports") for s in session.sql())
    assert session.commits == 1


async def test_delete_by_program_clears_plo_reports() -> None:
    session = _Session()
    with _patched(session):
        await PLORepository().delete_by_program(PID)
    assert any(s.startswith("delete from plo_reports") for s in session.sql())
    assert session.commits == 1


async def test_delete_cascade_clears_plo_reports() -> None:
    session = _Session()
    with _patched(session):
        await ProgramRepository().delete_cascade(PID)
    sql = session.sql()
    report_at = next(i for i, s in enumerate(sql) if s.startswith("delete from plo_reports"))
    program_at = next(i for i, s in enumerate(sql) if s.startswith("delete from programs"))
    assert report_at < program_at


def test_row_dict_has_the_report_columns() -> None:
    row = PLOReportTable(program_id=PID, plo_fingerprint="x", created_at=T0, report={})
    assert set(_row_to_dict(row)) == {"program_id", "plo_fingerprint", "created_at", "report"}
