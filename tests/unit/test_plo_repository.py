from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_agent.data.repositories import PLORepository


def _capturing_db(captured: list[object]) -> MagicMock:
    """A session that records the statement it was handed and returns nothing.

    The order has to be asserted on the query rather than on the rows: the
    session is a mock, so rows come back in whatever order the test put them in,
    and a test like that passes with the ORDER BY deleted."""
    session = AsyncMock()

    async def execute(statement: object) -> MagicMock:
        captured.append(statement)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    session.execute = execute
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def test_the_plo_list_is_ordered_core_first_then_numerically() -> None:
    """`plo_id` carries meaning — PLO1 is the outcome drafted from the
    most-demanded Need — and synthesis keeps that order through
    `asyncio.gather`. The read used to throw it away: no ORDER BY means heap
    order, and an UPDATE moves a row to the end of the heap, so editing one
    outcome reshuffled the exported มคอ.2 matrix and the UI list.
    """
    captured: list[object] = []
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_capturing_db(captured),
    ):
        await PLORepository().list_by_program("cs-test")

    assert len(captured) == 1
    sql = str(captured[0]).lower()
    order = sql.split("order by", 1)
    assert len(order) == 2, f"the PLO list is unordered: {sql}"
    clause = order[1]

    # is_optional first, or OPT1 sorts above PLO1 and the supplementary
    # outcomes lead the matrix.
    assert clause.index("is_optional") < clause.index("length(")
    # length before value, or PLO10 sorts between PLO1 and PLO2.
    assert clause.index("length(") < clause.rindex("plo_id")


# --------------------------- update_if_version ---------------------------


async def test_update_if_version_updates_only_the_expected_version_and_never_inserts() -> None:
    from tests.unit.test_superseded_plos import (  # noqa: PLC0415
        PID,
        _patched,
        _plo,
        _plo_row,
        _Session,
    )

    session = _Session(select_rows=[_plo_row("PLO1", "x")])  # rowcount 1
    with _patched(session):
        ok = await PLORepository().update_if_version(
            _plo("PLO1").model_copy(update={"version": 4}), expected_version=3
        )
    assert ok is True and session.commits == 1 and session.added == []
    (sql,) = session.sql()
    assert sql.startswith("update plos") and "version" in sql
    assert "program_id" in sql and "plo_id" in sql
    assert PID == "cs-test"


async def test_update_if_version_is_false_when_no_row_matches() -> None:
    from tests.unit.test_superseded_plos import _patched, _plo, _Session  # noqa: PLC0415

    session = _Session(select_rows=[])  # rowcount 0: gone, or the version moved
    with _patched(session):
        ok = await PLORepository().update_if_version(_plo("PLO1"), expected_version=1)
    assert ok is False and session.added == []
