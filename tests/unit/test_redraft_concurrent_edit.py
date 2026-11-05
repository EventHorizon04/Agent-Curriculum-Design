"""A hand edit made while a redraft is drafting is not deleted (final review I1).

`redraft_from_needs` reads the set, drafts for up to minutes, then `replace`
deletes what it read. `PUT /plos/{id}` is not blocked meanwhile, so `replace`
takes `expect` (plo_id -> the statement read before the draft) and re-reads
each superseded row inside its own transaction; a row that moved refuses the
whole write. The session is the recording mock of test_superseded_plos.py.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.data.orm import PLOFeedbackActionTable, PLOTable, SupersededPLOTable
from curriculum_agent.data.repositories import (
    NeedRepository,
    PLOChangedDuringRedraft,
    PLORepository,
)
from curriculum_agent.models import PLO, AlignmentFinding
from curriculum_agent.stages import plo_feedback as pf
from curriculum_agent.stages.plo_redraft import (
    REASON_CHANGED_DURING_REDRAFT,
    redraft_from_needs,
)
from tests.unit.test_api_plos import _need, _plo, _program, client
from tests.unit.test_plo_feedback import _Env, _review
from tests.unit.test_superseded_plos import PID, _patched, _plo_row, _Session
from tests.unit.test_superseded_plos import _plo as _stored_plo

CHANGED = "PLO นี้ถูกแก้ระหว่างร่างใหม่ — ไม่เขียนทับ"


def _edited_row(plo_id: str, statement: str) -> PLOTable:
    row = _plo_row(plo_id, statement)
    row.designer_edited_at = datetime(2026, 11, 5, 9, 0)
    return row


def _deletes(session: _Session) -> list[str]:
    return [s for s in session.sql() if s.startswith("delete")]


async def _replace(
    session: _Session, expect: dict[str, str] | None, *, cause: str = "review", **kw: Any
) -> int:
    with _patched(session):
        return await PLORepository().replace(
            PID,
            ["PLO1"],
            [_stored_plo("PLO1", "ออกแบบระบบรวมได้")],
            cause=cause,
            expect=expect,
            **kw,
        )


# --------------------------- PLORepository.replace ---------------------------


def test_the_reason_text_is_exact() -> None:
    assert REASON_CHANGED_DURING_REDRAFT == CHANGED


async def test_an_unchanged_row_is_replaced() -> None:
    session = _Session(select_rows=[_plo_row("PLO1", "ออกแบบระบบ ก ได้")])
    await _replace(session, {"PLO1": "ออกแบบระบบ ก ได้"})
    assert session.commits == 1 and len(_deletes(session)) == 1


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param([_plo_row("PLO1", "แก้ด้วยมือ")], id="statement-changed"),
        pytest.param([], id="row-gone"),
        pytest.param([_edited_row("PLO1", "ออกแบบระบบ ก ได้")], id="designer-edited"),
    ],
)
async def test_a_moved_row_refuses_and_writes_nothing(rows: list[PLOTable]) -> None:
    session = _Session(select_rows=rows)
    with pytest.raises(PLOChangedDuringRedraft):
        await _replace(session, {"PLO1": "ออกแบบระบบ ก ได้"})
    assert session.commits == 0
    assert _deletes(session) == [] and session.added == []


async def test_a_designer_edited_row_is_the_designers_to_replace() -> None:
    """The designer's own merge may replace a hand-edited PLO; only `review` may not."""
    session = _Session(select_rows=[_edited_row("PLO1", "ออกแบบระบบ ก ได้")])
    await _replace(session, {"PLO1": "ออกแบบระบบ ก ได้"}, cause="designer")
    assert session.commits == 1


async def test_the_check_reads_before_it_deletes_in_the_same_transaction() -> None:
    session = _Session(select_rows=[_plo_row("PLO1", "ออกแบบระบบ ก ได้")])
    await _replace(session, {"PLO1": "ออกแบบระบบ ก ได้"})
    sql = session.sql()
    select_at = next(i for i, s in enumerate(sql) if s.startswith("select"))
    assert select_at < next(i for i, s in enumerate(sql) if s.startswith("delete"))
    assert "for update" in sql[select_at]


# --------------------------- send-back: skipped, nothing replaced ---------------------------


def _wire_real_redraft(
    monkeypatch: pytest.MonkeyPatch, env: _Env, session: _Session, edit_to: str
) -> AsyncMock:
    """Real `redraft_from_needs` and real `replace`; the draft step stands in for
    the LLM and, while it "runs", the designer's PUT lands on PLO3."""
    monkeypatch.setattr(pf, "redraft_from_needs", redraft_from_needs)
    monkeypatch.setattr(
        NeedRepository,
        "list_by_program",
        AsyncMock(return_value=[_need(f"N{i}") for i in range(1, 7)]),
    )
    monkeypatch.setattr(PLORepository, "list_by_program", AsyncMock(side_effect=env._list))

    async def _draft(*_a: object, **_k: object) -> PLO:
        session.select_rows = [_plo_row("PLO3", edit_to)]  # the PUT, mid-draft
        return _plo("PLO3", ["N3"]).model_copy(update={"statement_th": "ร่างใหม่ PLO3"})

    synth = AsyncMock(side_effect=_draft)
    monkeypatch.setattr("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", synth)
    return synth


async def test_send_back_skips_a_plo_edited_mid_draft_and_replaces_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _Env(monkeypatch, [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)])
    session = _Session(select_rows=[_plo_row("PLO3", env.plos[2].statement_th)])
    synth = _wire_real_redraft(monkeypatch, env, session, "แก้ด้วยมือระหว่างร่าง")
    finding = AlignmentFinding(plo_id="PLO3", reason_th="ไม่ตรง", agreed_runs=2)

    with _patched(session):
        (action,) = await pf.send_back("cs-test", _review(alignment=[finding]), env.initial)

    synth.assert_awaited_once()
    assert (action.outcome, action.outcome_reason_th) == ("skipped", CHANGED)
    assert session.commits == 0 and _deletes(session) == []
    assert not any(
        isinstance(a, PLOTable | SupersededPLOTable | PLOFeedbackActionTable) for a in session.added
    )
    # The skipped row is written on its own, as every non-applied row is.
    assert [c.args[0] for c in env.trail.add.await_args_list] == [[action]]


# --------------------------- the designer's route: 409 ---------------------------


def test_from_needs_answers_409_when_a_plo_is_edited_mid_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)]
    session = _Session(select_rows=[_plo_row("PLO1", existing[0].statement_th)])
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        NeedRepository,
        "list_by_program",
        AsyncMock(return_value=[_need(f"N{i}") for i in range(1, 7)]),
    )
    monkeypatch.setattr(PLORepository, "list_by_program", AsyncMock(return_value=existing))

    async def _draft(*_a: object, **_k: object) -> PLO:
        session.select_rows = [_plo_row("PLO1", "แก้ด้วยมือระหว่างร่าง")]
        return _plo("PLO1", ["N1", "N2"])

    monkeypatch.setattr(
        "curriculum_agent.stages.plo_synthesis.synthesize_from_needs",
        AsyncMock(side_effect=_draft),
    )

    with _patched(session):
        response = client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == CHANGED
    assert session.commits == 0 and _deletes(session) == []
