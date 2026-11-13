"""llm_usage: storage and SQL-side summary (phase 5). Session is a mock."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

from curriculum_agent.data.orm import LLMUsageTable
from curriculum_agent.data.repositories import LLMUsageRepository, ProgramRepository
from curriculum_agent.models import LLMUsage
from tests.unit.test_superseded_plos import PID, _patched, _Session

T0 = datetime(2026, 11, 3, 12, 0, 0)


class _SummarySession(_Session):
    """Answers the three grouped SELECTs in order with fixed `.all()` rows."""

    def __init__(
        self,
        slot_rows: list[tuple[Any, ...]],
        job_rows: list[tuple[Any, ...]],
        session_rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        super().__init__()
        self._answers = [slot_rows, job_rows, session_rows or []]

    async def _execute(self, statement: Any) -> MagicMock:
        self.statements.append(statement)
        result = MagicMock()
        result.all.return_value = self._answers.pop(0)
        return result


def test_usage_defaults_and_utc_json() -> None:
    u = LLMUsage(slot="extraction", created_at=T0)
    assert u.program_id is None and u.job_id is None and u.session_id is None
    assert u.reasoning_tokens is None and u.ok is True and u.id
    assert json.loads(u.model_dump_json())["created_at"] == T0.replace(tzinfo=UTC).isoformat()


async def test_add_writes_one_row_and_commits() -> None:
    session = _Session()
    with _patched(session):
        await LLMUsageRepository().add(
            LLMUsage(slot="clustering", program_id=PID, prompt_tokens=5, ok=False)
        )
    rows = [r for r in session.added if isinstance(r, LLMUsageTable)]
    assert len(rows) == 1 and session.commits == 1
    assert rows[0].slot == "clustering" and rows[0].ok is False and rows[0].prompt_tokens == 5


async def test_summary_groups_in_sql_and_sums_per_slot_and_job() -> None:
    slot_rows = [
        ("clustering", 1, 0, 100, 10, 0, 500),
        ("extraction", 4, 1, 400, 40, None, 2000),  # null reasoning sum reads as 0
    ]
    job_rows = [
        ("j-old", "need_combination", "clustering", T0, 1, 0, 100, 10, 0, 500),
        ("j-new", "skill_extraction", "clustering", T0 + timedelta(hours=1), 0, 0, 0, 0, 0, 0),
        (
            "j-new",
            "skill_extraction",
            "extraction",
            T0 + timedelta(minutes=30),
            4,
            1,
            400,
            40,
            None,
            2000,
        ),
    ]
    session_rows = [
        ("s-old", "plo_synthesis", T0 + timedelta(hours=2), 2, 0, 50, 5, 0, 300),
        ("s-new", "validation", T0 + timedelta(hours=5), 1, 1, 10, 1, 0, 100),
        ("s-new", "extraction", T0 + timedelta(hours=4), 3, 0, 30, 3, None, 200),
    ]
    session = _SummarySession(slot_rows, job_rows, session_rows)
    with _patched(session):
        out = await LLMUsageRepository().summary(PID)

    sql = session.sql()
    assert len(sql) == 3 and all("group by" in s for s in sql)
    assert "left outer join jobs" in sql[1] and "job_id is not null" in sql[1]
    assert "job_id is null" in sql[2] and "session_id is not null" in sql[2]
    assert "join" not in sql[2]

    assert [x.session_id for x in out.by_session] == ["s-new", "s-old"]  # newest first
    newest = out.by_session[0]
    assert newest.started == T0 + timedelta(hours=4)  # earliest row across its slots
    assert [s.slot for s in newest.by_slot] == ["validation", "extraction"]
    assert newest.total.calls == 4 and newest.total.failed_calls == 1

    assert [s.slot for s in out.by_slot] == ["clustering", "extraction"]
    assert out.total.calls == 5 and out.total.failed_calls == 1
    assert out.total.prompt_tokens == 500 and out.total.completion_tokens == 50
    assert out.total.reasoning_tokens == 0 and out.total.latency_ms == 2500

    assert [j.job_id for j in out.by_job] == ["j-new", "j-old"]  # newest first
    new = out.by_job[0]
    assert new.kind == "skill_extraction"
    assert new.started == T0 + timedelta(minutes=30)  # earliest row across its slots
    assert [s.slot for s in new.by_slot] == ["clustering", "extraction"]
    assert new.total.calls == 4 and new.total.reasoning_tokens == 0
    assert out.by_job[1].kind == "need_combination"


async def test_summary_of_a_program_with_no_rows_is_empty() -> None:
    with _patched(_SummarySession([], [])):
        out = await LLMUsageRepository().summary(PID)
    assert out.total.calls == 0 and out.by_slot == [] and out.by_job == []


async def test_delete_cascade_clears_usage_before_the_program() -> None:
    session = _Session()
    with _patched(session):
        await ProgramRepository().delete_cascade(PID)
    sql = session.sql()
    usage_at = next(i for i, s in enumerate(sql) if s.startswith("delete from llm_usage"))
    program_at = next(i for i, s in enumerate(sql) if s.startswith("delete from programs"))
    assert usage_at < program_at
