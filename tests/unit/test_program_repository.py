from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_agent.data.orm import ProgramTable, SessionTable
from curriculum_agent.data.repositories import ProgramRepository


def _program_row(program_id: str, created_at: datetime) -> ProgramTable:
    return ProgramTable(
        program_id=program_id,
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="CS",
        degree_level="bachelor",
        duration_years=4,
        faculty="Engineering",
        university="Test University",
        program_goals_th=["เป้าหมาย 1"],
        program_objectives_th=["objective 1"],
        created_at=created_at,
    )


def _session_row(
    session_id: str, program_id: str, stage: str | None, status: str, created_at: datetime
) -> SessionTable:
    return SessionTable(
        session_id=session_id,
        program_id=program_id,
        thread_id=f"{program_id}:{session_id}",
        status=status,
        current_stage=stage,
        created_at=created_at,
        updated_at=created_at,
    )


def _mock_db(programs: list[ProgramTable], sessions: list[SessionTable]) -> MagicMock:
    """AsyncSessionLocal mock whose execute() returns programs then sessions."""
    prog_result = MagicMock()
    prog_result.scalars.return_value.all.return_value = programs
    sess_result = MagicMock()
    sess_result.scalars.return_value.all.return_value = sessions

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[prog_result, sess_result])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


async def test_list_all_empty() -> None:
    repo = ProgramRepository()
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_mock_db([], [])
    ):
        result = await repo.list_all()
    assert result == []


async def test_list_all_program_without_session_has_null_stage() -> None:
    repo = ProgramRepository()
    programs = [_program_row("cs", datetime(2026, 7, 1))]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, []),
    ):
        result = await repo.list_all()
    assert len(result) == 1
    assert result[0].program_id == "cs"
    assert result[0].current_stage is None
    assert result[0].session_status is None


async def test_list_all_uses_latest_session_per_program() -> None:
    repo = ProgramRepository()
    programs = [_program_row("cs", datetime(2026, 7, 1))]
    sessions = [
        _session_row("s1", "cs", "intake", "completed", datetime(2026, 7, 1, 10, 0)),
        _session_row("s2", "cs", "plo_synthesis", "suspended", datetime(2026, 7, 2, 10, 0)),
    ]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, sessions),
    ):
        result = await repo.list_all()
    assert result[0].current_stage == "plo_synthesis"
    assert result[0].session_status == "suspended"


async def test_list_all_preserves_program_order() -> None:
    """Rows come back in query order (created_at DESC handled by SQL)."""
    repo = ProgramRepository()
    programs = [
        _program_row("newer", datetime(2026, 7, 2)),
        _program_row("older", datetime(2026, 7, 1)),
    ]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, []),
    ):
        result = await repo.list_all()
    assert [p.program_id for p in result] == ["newer", "older"]


async def test_delete_cascade_deletes_tables_in_fk_safe_order() -> None:
    """skills must be deleted before evidence: SkillTable.source_evidence_id
    is a FK into EvidenceTable. Everything else has no cross-dependency."""
    repo = ProgramRepository()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=1) for _ in range(7)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        result = await repo.delete_cascade("cs")

    assert result is True
    executed_sql = [str(c.args[0]) for c in mock_session.execute.call_args_list]
    assert executed_sql[0].startswith("DELETE FROM skills")
    assert executed_sql[1].startswith("DELETE FROM needs")
    assert executed_sql[2].startswith("DELETE FROM plos")
    assert executed_sql[3].startswith("DELETE FROM checkpoints")
    assert executed_sql[4].startswith("DELETE FROM sessions")
    assert executed_sql[5].startswith("DELETE FROM evidence")
    assert executed_sql[6].startswith("DELETE FROM programs")


async def test_delete_cascade_returns_false_when_program_missing() -> None:
    repo = ProgramRepository()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=0) for _ in range(7)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        result = await repo.delete_cascade("missing")

    assert result is False


async def test_delete_cascade_commits_once() -> None:
    repo = ProgramRepository()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=1) for _ in range(7)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        await repo.delete_cascade("cs")

    mock_session.commit.assert_awaited_once()
