"""`copied_from` says which program a copy was made from.

It lives on ProgramMetadata (the stored entity), never on ProgramCreateRequest
(what a client sends), so no client can claim a program is a copy. It is not a
foreign key: deleting the source must leave its copies alone.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.data.orm import ProgramTable
from curriculum_agent.data.repositories import ProgramRepository
from curriculum_agent.models import ProgramCreateRequest, ProgramMetadata, ProgramSummary

client = TestClient(app)


def test_the_column_is_nullable_text_with_no_foreign_key() -> None:
    col = ProgramTable.__table__.columns["copied_from"]
    assert col.nullable is True
    assert not col.foreign_keys


def test_the_entity_carries_it_and_the_request_does_not() -> None:
    assert "copied_from" in ProgramMetadata.model_fields
    assert ProgramMetadata.model_fields["copied_from"].default is None
    assert "copied_from" not in ProgramCreateRequest.model_fields
    assert "copied_from" in ProgramSummary.model_fields


def test_the_migration_adds_and_drops_the_column() -> None:
    path = next(Path("migrations/versions").glob("*_program_copied_from.py"))
    spec = importlib.util.spec_from_file_location("m", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    op = MagicMock()
    with patch.dict("sys.modules", {"alembic.op": op}):
        spec.loader.exec_module(module)
        module.op = op
        module.upgrade()
        module.downgrade()
    assert module.down_revision == "117059107855"
    added = op.add_column.call_args
    assert added.args[0] == "programs"
    assert added.args[1].name == "copied_from"
    assert added.args[1].nullable is True
    op.drop_column.assert_called_once_with("programs", "copied_from")


def _mock_db(
    programs: list[ProgramTable],
    sessions: list,
    *,
    evidence: list[str] | None = None,
    skills: list[str] | None = None,
    needs: list[str] | None = None,
    plos: list[str] | None = None,
) -> MagicMock:
    """AsyncSessionLocal mock replaying list_all's queries in the order it runs
    them: programs, sessions, then the program ids owning rows in each of the
    four artifact tables progress is derived from. Copied from the `_mock_db`
    helper in tests/unit/test_program_repository.py."""

    def _result(rows: object) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            _result(programs),
            _result(sessions),
            _result(evidence or []),
            _result(skills or []),
            _result(needs or []),
            _result(plos or []),
        ]
    )
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


async def test_list_all_carries_copied_from() -> None:
    row = ProgramTable(
        program_id="program-2-run-1",
        name_th="",
        name_en="",
        field="การท่องเที่ยว",
        degree_level="bachelor",
        duration_years=4,
        faculty="คณะ",
        university="มหาวิทยาลัย",
        program_goals_th=[],
        program_objectives_th=[],
        created_at=datetime(2026, 10, 6),
        copied_from="program-2",
    )
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db([row], []),
    ):
        summaries = await ProgramRepository().list_all()
    assert summaries[0].copied_from == "program-2"


def test_put_keeps_copied_from(monkeypatch) -> None:  # noqa: ANN001
    """PUT rebuilds ProgramMetadata from a ProgramCreateRequest, which has no
    copied_from — without carrying it over, editing a copy's metadata would
    erase where it came from."""
    from curriculum_agent.api.routes import programs as programs_route

    existing = ProgramMetadata(
        program_id="program-2-run-1",
        field="การท่องเที่ยว",
        degree_level="bachelor",
        duration_years=4,
        faculty="คณะ",
        university="มหาวิทยาลัย",
        copied_from="program-2",
    )
    upsert = AsyncMock()
    monkeypatch.setattr(programs_route.ProgramRepository, "get", AsyncMock(return_value=existing))
    monkeypatch.setattr(programs_route.ProgramRepository, "upsert", upsert)
    app.state.graph = MagicMock(aupdate_state=AsyncMock())

    body = existing.model_dump(mode="json", include=set(ProgramCreateRequest.model_fields))
    response = client.put("/programs/program-2-run-1", json=body)

    assert response.status_code == 200
    assert upsert.await_args.args[0].copied_from == "program-2"
