"""superseded_plos: PLORepository.replace snapshots what it removes.

The session is a mock, as in test_plo_repository.py: statements are recorded and
compiled rather than run, and rows written by `session.add` are fed back to the
read side so the round trip through `list_by_program` is still exercised.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from curriculum_agent.data.orm import PLOTable, SupersededPLOTable
from curriculum_agent.data.repositories import (
    PLORepository,
    ProgramRepository,
    SupersededPLORepository,
    _row_to_dict,
)
from curriculum_agent.models import PLO, SMARTCheck

PID = "cs-test"


def _plo(plo_id: str, statement: str = "ออกแบบระบบสารสนเทศสำหรับองค์กรได้") -> PLO:
    return PLO(
        plo_id=plo_id,
        program_id=PID,
        statement_th=statement,
        bloom_level="create",
        action_verb_th="ออกแบบ",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=["nd-1"],
        source_evidence_ids=["ev-1"],
        rationale_th="เหตุผล",
    )


def _plo_row(plo_id: str, statement: str) -> PLOTable:
    return PLOTable(**_plo(plo_id, statement).model_dump(mode="json"))


class _Session:
    """Records statements and adds; `select_rows` answers any SELECT."""

    def __init__(self, select_rows: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.select_rows = select_rows or []
        self.commits = 0

        self.mock = AsyncMock()
        self.mock.execute = self._execute
        self.mock.add = self.added.append
        self.mock.get = AsyncMock(return_value=None)
        self.mock.commit = self._commit

    async def _commit(self) -> None:
        self.commits += 1

    async def _execute(self, statement: Any) -> MagicMock:
        self.statements.append(statement)
        result = MagicMock()
        result.scalars.return_value.all.return_value = self.select_rows
        result.rowcount = len(self.select_rows)
        return result

    def sql(self) -> list[str]:
        return [
            str(s.compile(dialect=postgresql.dialect())).lower().replace("\n", " ")
            for s in self.statements
        ]


@contextmanager
def _patched(session: _Session) -> Iterator[None]:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session.mock)
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=ctx):
        yield


async def _replace(rows: list[PLOTable], remove: list[str], add: list[PLO]) -> _Session:
    session = _Session(select_rows=rows)
    with _patched(session):
        await PLORepository().replace(PID, remove, add)
    return session


async def _list(history: list[SupersededPLOTable]) -> list[Any]:
    session = _Session(select_rows=history)
    with _patched(session):
        return await SupersededPLORepository().list_by_program(PID)


async def test_replace_snapshots_removed_plos() -> None:
    stored = [_plo_row("PLO1", "ออกแบบระบบ ก ได้"), _plo_row("PLO2", "ออกแบบระบบ ข ได้")]
    session = await _replace(stored, ["PLO1", "PLO2"], [_plo("PLO1", "ออกแบบระบบรวมได้")])

    history = [a for a in session.added if isinstance(a, SupersededPLOTable)]
    assert len(history) == 2
    assert session.commits == 1
    # History is read before the rows are deleted, in the same session.
    sql = session.sql()
    select_at = next(i for i, s in enumerate(sql) if s.startswith("select"))
    delete_at = next(i for i, s in enumerate(sql) if s.startswith("delete"))
    assert select_at < delete_at

    listed = await _list(history)
    assert len(listed) == 2
    assert {s.superseded_by for s in listed} == {"PLO1"}
    assert {s.plo.plo_id for s in listed} == {"PLO1", "PLO2"}
    assert {s.plo.statement_th for s in listed} == {"ออกแบบระบบ ก ได้", "ออกแบบระบบ ข ได้"}
    assert {s.program_id for s in listed} == {PID}
    assert len({s.id for s in listed}) == 2


async def test_replace_with_nothing_removed_writes_no_history() -> None:
    session = await _replace([], [], [_plo("PLO1")])
    assert not [a for a in session.added if isinstance(a, SupersededPLOTable)]
    assert not any("superseded_plos" in s for s in session.sql())


async def test_replace_with_nothing_added_writes_no_history() -> None:
    session = await _replace([_plo_row("PLO1", "ออกแบบระบบ ก ได้")], ["PLO1"], [])
    assert not [a for a in session.added if isinstance(a, SupersededPLOTable)]


async def test_delete_by_program_clears_history() -> None:
    session = _Session()
    with _patched(session):
        await PLORepository().delete_by_program(PID)
    sql = session.sql()
    assert any(s.startswith("delete from superseded_plos") for s in sql)
    assert session.commits == 1


async def test_delete_cascade_clears_history() -> None:
    session = _Session()
    with _patched(session):
        await ProgramRepository().delete_cascade(PID)
    sql = session.sql()
    assert any(s.startswith("delete from superseded_plos") for s in sql)
    # Before the program row, which its foreign key points at.
    history_at = next(i for i, s in enumerate(sql) if s.startswith("delete from superseded_plos"))
    program_at = next(i for i, s in enumerate(sql) if s.startswith("delete from programs"))
    assert history_at < program_at


def _history_row(row_id: str, snapshot: dict[str, Any], at: datetime) -> SupersededPLOTable:
    return SupersededPLOTable(
        id=row_id,
        program_id=PID,
        plo_id=snapshot.get("plo_id", "PLO1"),
        snapshot=snapshot,
        superseded_by="PLO1",
        superseded_at=at,
    )


async def test_list_skips_snapshot_that_no_longer_validates() -> None:
    at = datetime(2026, 11, 3, 12, 0, 0)
    good = _history_row("h-1", _row_to_dict(_plo_row("PLO2", "ออกแบบระบบ ข ได้")), at)
    bad = _history_row("h-2", {"plo_id": "PLO3", "statement_th": "ขาดทุกอย่าง"}, at)
    listed = await _list([bad, good])
    assert [s.id for s in listed] == ["h-1"]


async def test_list_is_ordered_newest_first_in_the_query() -> None:
    session = _Session()
    with _patched(session):
        await SupersededPLORepository().list_by_program(PID)
    sql = session.sql()[0]
    # One merge stamps every row with the same superseded_at; plo_id breaks the tie.
    assert (
        "order by superseded_plos.superseded_at desc, "
        "length(superseded_plos.plo_id), superseded_plos.plo_id"
    ) in sql


async def test_list_keeps_the_order_the_database_returned() -> None:
    now = datetime(2026, 11, 3, 12, 0, 0)
    snap = _row_to_dict(_plo_row("PLO1", "ออกแบบระบบ ก ได้"))
    rows = [
        _history_row("new", snap, now),
        _history_row("old", snap, now - timedelta(hours=1)),
    ]
    assert [s.id for s in await _list(rows)] == ["new", "old"]


async def test_replace_records_cause_review() -> None:
    session = _Session(select_rows=[_plo_row("PLO1", "ออกแบบระบบ ก ได้")])
    with _patched(session):
        await PLORepository().replace(PID, ["PLO1"], [_plo("PLO1")], cause="review")
    history = [a for a in session.added if isinstance(a, SupersededPLOTable)]
    assert [h.cause for h in history] == ["review"]
    assert [s.cause for s in await _list(history)] == ["review"]


async def test_replace_default_cause_designer() -> None:
    session = await _replace([_plo_row("PLO1", "ออกแบบระบบ ก ได้")], ["PLO1"], [_plo("PLO1")])
    history = [a for a in session.added if isinstance(a, SupersededPLOTable)]
    assert [h.cause for h in history] == ["designer"]


async def test_list_reads_legacy_null_cause_as_none() -> None:
    snap = _row_to_dict(_plo_row("PLO1", "ออกแบบระบบ ก ได้"))
    row = _history_row("old", snap, datetime(2026, 11, 3))
    assert [s.cause for s in await _list([row])] == [None]
