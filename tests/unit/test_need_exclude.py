"""`Need.excluded_at` / `merged_by`: the designer's exclusion and who merged a Need."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from curriculum_agent.data.orm import NeedTable
from curriculum_agent.data.repositories import NeedRepository
from curriculum_agent.models import BloomLevel, Need
from curriculum_agent.stages import need_merge as nm

_NOW = datetime(2026, 11, 3, 9, 0, 0)


def _data(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "need_id": "N1",
        "program_id": "p",
        "statement_th": "ต้องการบัณฑิตที่ทำงานได้จริง",
        "ksec_categories": ["K"],
        "bloom_level": BloomLevel.APPLY,
        "member_skill_ids": ["S1"],
        "source_evidence_ids": ["E1"],
        "freq": 1,
        "demand_score": 0.5,
    }
    base.update(over)
    return base


def _need(nid: str, **over: Any) -> Need:
    return Need.model_validate(_data(need_id=nid, **over))


def _ctx(session: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def test_need_accepts_dict_without_new_fields() -> None:
    need = Need.model_validate(_data())
    assert need.excluded_at is None
    assert need.merged_by is None


async def test_list_active_skips_excluded() -> None:
    captured: list[object] = []
    session = AsyncMock()

    async def execute(statement: object) -> MagicMock:
        captured.append(statement)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    session.execute = execute
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        await NeedRepository().list_active_by_program("p")
    sql = str(captured[0]).lower()
    assert "merged_into is null" in sql
    assert "excluded_at is null" in sql


async def test_set_excluded_writes_and_clears_the_timestamp() -> None:
    row = NeedTable(**_need("N1").model_dump(mode="json"))
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        excluded = await NeedRepository().set_excluded("p", "N1", _NOW)
        restored = await NeedRepository().set_excluded("p", "N1", None)
    assert excluded.excluded_at == _NOW
    assert restored.excluded_at is None
    assert session.commit.await_count == 2


@pytest.mark.parametrize("found", ["missing", "other_program"])
async def test_set_excluded_unknown_need_raises_key_error(found: str) -> None:
    row = None
    if found == "other_program":
        row = NeedTable(**_need("N1", program_id="other").model_dump(mode="json"))
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    with (
        patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)),
        pytest.raises(KeyError),
    ):
        await NeedRepository().set_excluded("p", "N1", _NOW)
    session.commit.assert_not_awaited()


async def test_write_merge_links_originals_and_inserts_in_one_session() -> None:
    a, b = _need("A"), _need("B")
    merged = _need("M", merged_from=["A", "B"], merged_by="designer")
    rows = {n.need_id: NeedTable(**n.model_dump(mode="json")) for n in (a, b)}
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda _cls, key: rows[key])
    session.add = MagicMock()
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)
    ) as factory:
        written = await NeedRepository().write_merge("p", [a, b], merged)

    assert factory.call_count == 1
    assert rows["A"].merged_into == "M" and rows["B"].merged_into == "M"
    added = session.add.call_args.args[0]
    assert added.need_id == "M" and added.merged_by == "designer"
    session.commit.assert_awaited_once()
    assert written.need_id == "M"


async def test_delete_by_program_deletes_needs_scoped_to_the_program() -> None:
    captured: list[object] = []
    session = AsyncMock()

    async def execute(statement: object) -> MagicMock:
        captured.append(statement)
        return MagicMock(rowcount=3)

    session.execute = execute
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        assert await NeedRepository().delete_by_program("prog-1") == 3
    compiled = captured[0].compile(compile_kwargs={"literal_binds": True})  # type: ignore[attr-defined]
    sql = str(compiled).lower()
    assert sql.startswith("delete from needs")
    assert "program_id = 'prog-1'" in sql
    session.commit.assert_awaited_once()


def test_mark_merged_sets_parent() -> None:
    a, b, c = _need("A"), _need("B"), _need("C")
    merged = _need("M", merged_from=["A", "B"])
    out = nm.mark_merged([a, b, c], [merged])
    assert [n.need_id for n in out] == ["A", "B", "C"]
    assert out[0].merged_into == "M" and out[1].merged_into == "M"
    assert out[2] is c
