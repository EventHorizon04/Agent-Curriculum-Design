from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from curriculum_agent.data import repositories
from curriculum_agent.data.orm import ProgramTable, SessionTable
from curriculum_agent.data.repositories import ProgramRepository
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    PLOSetReview,
    SMARTCheck,
)
from curriculum_agent.stages.plo_review_facts import need_demands, plo_fingerprint

_REAL_CURRENT_REVIEW_LOOKUP = repositories._programs_with_a_current_review


@pytest.fixture(autouse=True)
def _no_real_review_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """list_all asks the repositories whether a stored QA review is current; the
    session mocks below only answer its own queries, so default that to "none"."""
    monkeypatch.setattr(
        repositories, "_programs_with_a_current_review", AsyncMock(return_value=set())
    )


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


def _mock_db(
    programs: list[ProgramTable],
    sessions: list[SessionTable],
    *,
    evidence: list[str] | None = None,
    skills: list[str] | None = None,
    needs: list[str] | None = None,
    plos: list[str] | None = None,
) -> MagicMock:
    """AsyncSessionLocal mock replaying list_all's queries in the order it runs
    them: programs, sessions, then the program ids owning rows in each of the
    four artifact tables progress is derived from."""

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


async def test_list_all_empty() -> None:
    repo = ProgramRepository()
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_mock_db([], [])
    ):
        result = await repo.list_all()
    assert result == []


async def test_list_all_bare_program_reports_intake() -> None:
    """A program with nothing under it has still completed intake — the program
    row is intake's output."""
    repo = ProgramRepository()
    programs = [_program_row("cs", datetime(2026, 7, 1))]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, []),
    ):
        result = await repo.list_all()
    assert len(result) == 1
    assert result[0].program_id == "cs"
    assert result[0].current_stage == "intake"
    assert result[0].session_status is None


async def test_list_all_reports_progress_made_without_any_session() -> None:
    """The regression: the per-stage REST routes the stage pages call write no
    session row, so progress read off the session table was permanently absent
    for a designer working page by page, and the rail showed nothing reached."""
    repo = ProgramRepository()
    programs = [_program_row("cs", datetime(2026, 7, 1))]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, [], evidence=["cs"], skills=["cs"], needs=["cs"]),
    ):
        result = await repo.list_all()
    assert result[0].current_stage == "need_analysis"
    assert result[0].session_status is None


async def test_list_all_prefers_stored_rows_over_what_a_session_claims() -> None:
    """A session records where its own run stopped, which is not the same as how
    far the program got — deleting a program's PLOs must move progress back."""
    repo = ProgramRepository()
    programs = [_program_row("cs", datetime(2026, 7, 1))]
    sessions = [
        _session_row("s1", "cs", "plo_report", "completed", datetime(2026, 7, 2, 10, 0)),
    ]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, sessions, evidence=["cs"]),
    ):
        result = await repo.list_all()
    assert result[0].current_stage == "stakeholder_needs"


async def test_list_all_takes_session_status_from_the_latest_session() -> None:
    repo = ProgramRepository()
    programs = [_program_row("cs", datetime(2026, 7, 1))]
    sessions = [
        _session_row("s1", "cs", "intake", "completed", datetime(2026, 7, 1, 10, 0)),
        _session_row("s2", "cs", "plo_synthesis", "suspended", datetime(2026, 7, 2, 10, 0)),
    ]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, sessions, plos=["cs"]),
    ):
        result = await repo.list_all()
    assert result[0].session_status == "suspended"
    assert result[0].current_stage == "plo_synthesis"


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


def _plo(plo_id: str = "PLO1") -> PLO:
    return PLO(
        plo_id=plo_id,
        program_id="cs",
        statement_th="วิเคราะห์งานเพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=["N1"],
        source_evidence_ids=["E1"],
        rationale_th="ตรงกับความต้องการของตลาด",
    )


def _need() -> Need:
    return Need(
        need_id="N1",
        program_id="cs",
        statement_th="ต้องการบัณฑิตที่วิเคราะห์ข้อมูลธุรกิจเพื่อตัดสินใจได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=1,
        demand_score=0.7,
    )


def _review_with(fingerprint: str) -> PLOSetReview:
    return PLOSetReview(
        program_id="cs",
        plo_fingerprint=fingerprint,
        model="m",
        created_at=datetime(2026, 10, 12),
        summary_th="ดีแล้ว",
    )


def _stored(monkeypatch: pytest.MonkeyPatch, review: object) -> None:
    """Make the real `_programs_with_a_current_review` read one program's rows."""
    # Put back the real helper the autouse stub replaced; it is what is under test.
    monkeypatch.setattr(
        repositories, "_programs_with_a_current_review", _REAL_CURRENT_REVIEW_LOOKUP
    )
    review_repo = MagicMock()
    review_repo.return_value.get = (
        AsyncMock(side_effect=review)
        if isinstance(review, Exception)
        else AsyncMock(return_value=review)
    )
    plo_repo = MagicMock()
    plo_repo.return_value.list_by_program = AsyncMock(return_value=[_plo()])
    need_repo = MagicMock()
    need_repo.return_value.list_active_by_program = AsyncMock(return_value=[_need()])
    monkeypatch.setattr(repositories, "PLOReviewRepository", review_repo)
    monkeypatch.setattr(repositories, "PLORepository", plo_repo)
    monkeypatch.setattr(repositories, "NeedRepository", need_repo)


async def _stage_of_cs_with_plos() -> str:
    programs = [_program_row("cs", datetime(2026, 7, 1))]
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_mock_db(programs, [], plos=["cs"]),
    ):
        result = await ProgramRepository().list_all()
    return result[0].current_stage


async def test_list_all_reports_plo_review_for_a_current_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _review_with(plo_fingerprint([_plo()], need_demands([_need()])))
    _stored(monkeypatch, current)
    assert await _stage_of_cs_with_plos() == "plo_review"


async def test_list_all_reports_plo_synthesis_for_a_stale_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stored(monkeypatch, _review_with("not-this-set"))
    assert await _stage_of_cs_with_plos() == "plo_synthesis"


async def test_list_all_survives_a_review_read_that_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stored(monkeypatch, RuntimeError("db down"))
    assert await _stage_of_cs_with_plos() == "plo_synthesis"


async def test_delete_cascade_deletes_tables_in_fk_safe_order() -> None:
    """skills must be deleted before evidence: SkillTable.source_evidence_id
    is a FK into EvidenceTable. Everything else has no cross-dependency."""
    repo = ProgramRepository()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=1) for _ in range(14)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        result = await repo.delete_cascade("cs")

    assert result is True
    executed_sql = [str(c.args[0]) for c in mock_session.execute.call_args_list]
    assert executed_sql[0].startswith("DELETE FROM skill_groups")
    assert executed_sql[1].startswith("DELETE FROM skills")
    assert executed_sql[2].startswith("DELETE FROM needs")
    assert executed_sql[3].startswith("DELETE FROM superseded_plos")
    assert executed_sql[4].startswith("DELETE FROM plo_feedback_actions")
    assert executed_sql[5].startswith("DELETE FROM llm_usage")
    assert executed_sql[6].startswith("DELETE FROM plos")
    assert executed_sql[7].startswith("DELETE FROM plo_reviews")
    assert executed_sql[8].startswith("DELETE FROM plo_reports")
    assert executed_sql[9].startswith("DELETE FROM checkpoints")
    assert executed_sql[10].startswith("DELETE FROM sessions")
    assert executed_sql[11].startswith("DELETE FROM jobs")
    assert executed_sql[12].startswith("DELETE FROM evidence")
    assert executed_sql[13].startswith("DELETE FROM programs")


async def test_delete_cascade_returns_false_when_program_missing() -> None:
    repo = ProgramRepository()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=0) for _ in range(14)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        result = await repo.delete_cascade("missing")

    assert result is False


async def test_delete_cascade_commits_once() -> None:
    repo = ProgramRepository()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=1) for _ in range(14)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        await repo.delete_cascade("cs")

    mock_session.commit.assert_awaited_once()


def _get_db(row: ProgramTable | None) -> MagicMock:
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=row)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


async def test_get_reads_a_missing_scope_statement_back_as_an_empty_string() -> None:
    """The column is nullable — every program created before the scope guard has
    NULL there — while the Pydantic side says `str = ""`.

    Left as None it reaches the extraction cache key through str() and hashes the
    literal "None", which is a different key from the empty one. Every pre-scope
    program would then quietly get a cache namespace of its own and re-extract its
    whole corpus, and the resemblance to a correct key is what would make it hard
    to spot.
    """
    row = _program_row("cs", datetime(2026, 7, 1))
    row.scope_th = None

    repo = ProgramRepository()
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_get_db(row)):
        program = await repo.get("cs")

    assert program is not None
    assert program.scope_th == ""


async def test_get_returns_a_stored_scope_statement_unchanged() -> None:
    scope = "หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจ การล่ามการเจรจา และการตรวจแก้งานแปล"
    row = _program_row("cs", datetime(2026, 7, 1))
    row.scope_th = scope

    repo = ProgramRepository()
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_get_db(row)):
        program = await repo.get("cs")

    assert program is not None
    assert program.scope_th == scope
