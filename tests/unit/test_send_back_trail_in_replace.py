"""An applied send-back's trail row is written in the replace transaction (final review I4).

`replace` used to commit inside `redraft_from_needs` and `_record` wrote the row
afterwards, so the loop's `asyncio.timeout` landing between the two left a
changed PLO with no trail row. Now `redraft_from_needs(trail=...)` hands the row
to `PLORepository.replace(trail_row=...)`, which inserts it beside the delete and
the insert; `_record` only keeps and logs a row already written.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.data.orm import PLOFeedbackActionTable
from curriculum_agent.data.repositories import PLOChangedDuringRedraft, PLORepository
from curriculum_agent.models import PLO, AlignmentFinding, FeedbackAction
from curriculum_agent.stages import plo_feedback as pf
from curriculum_agent.stages.plo_redraft import redraft_from_needs
from tests.unit.test_api_plos import _need, _plo, _program
from tests.unit.test_plo_feedback import _Env, _review
from tests.unit.test_plo_redraft import _install
from tests.unit.test_superseded_plos import PID, _patched, _plo_row, _Session
from tests.unit.test_superseded_plos import _plo as _stored_plo


def _row(**kw: object) -> FeedbackAction:
    base: dict[str, object] = {
        "program_id": PID,
        "review_created_at": datetime(2026, 11, 5),
        "kind": "alignment",
        "outcome": "applied",
        "result_plo_id": "PLO1",
    }
    base.update(kw)
    return FeedbackAction(**base)  # type: ignore[arg-type]


def _trail_rows(session: _Session) -> list[PLOFeedbackActionTable]:
    return [a for a in session.added if isinstance(a, PLOFeedbackActionTable)]


# --------------------------- PLORepository.replace ---------------------------


async def test_replace_writes_the_trail_row_in_its_own_transaction() -> None:
    session = _Session(select_rows=[_plo_row("PLO1", "ออกแบบระบบ ก ได้")])
    row = _row()
    with _patched(session):
        await PLORepository().replace(
            PID, ["PLO1"], [_stored_plo("PLO1", "ออกแบบระบบรวมได้")], cause="review", trail_row=row
        )
    (written,) = _trail_rows(session)
    assert written.id == row.id and written.outcome == "applied"
    assert session.commits == 1  # one commit carries the delete, the insert and the row


async def test_a_failure_inside_replace_writes_neither_the_plo_nor_the_row() -> None:
    session = _Session(select_rows=[_plo_row("PLO1", "ออกแบบระบบ ก ได้")])
    session.mock.get = AsyncMock(side_effect=RuntimeError("insert failed"))
    with _patched(session), pytest.raises(RuntimeError):
        await PLORepository().replace(
            PID,
            ["PLO1"],
            [_stored_plo("PLO1", "ออกแบบระบบรวมได้")],
            cause="review",
            trail_row=_row(),
        )
    assert session.commits == 0  # the delete, the history and the row roll back together


async def test_a_refused_replace_adds_no_trail_row() -> None:
    session = _Session(select_rows=[_plo_row("PLO1", "แก้ด้วยมือ")])
    with _patched(session), pytest.raises(PLOChangedDuringRedraft):
        await PLORepository().replace(
            PID,
            ["PLO1"],
            [_stored_plo("PLO1", "ออกแบบระบบรวมได้")],
            cause="review",
            expect={"PLO1": "ออกแบบระบบ ก ได้"},
            trail_row=_row(),
        )
    assert session.added == [] and session.commits == 0


# --------------------------- redraft_from_needs(trail=...) ---------------------------


async def test_redraft_hands_the_trail_row_to_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    needs = [_need(f"N{i}") for i in range(1, 7)]
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)]
    draft = _plo("PLO2", ["N2"])
    replace, _ = _install(monkeypatch, needs, existing, draft)
    seen: list[PLO] = []

    def trail(plo: PLO) -> FeedbackAction:
        seen.append(plo)
        return _row(result_plo_id=plo.plo_id)

    await redraft_from_needs(
        _program(), "cs-test", ["N2"], note_th=None, cause="review", trail=trail
    )

    assert seen == [draft.model_copy(update={"version": 2})]
    row = replace.await_args.kwargs["trail_row"]
    assert isinstance(row, FeedbackAction) and row.result_plo_id == "PLO2"


async def test_the_designer_route_passes_no_trail_row(monkeypatch: pytest.MonkeyPatch) -> None:
    needs = [_need(f"N{i}") for i in range(1, 7)]
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)]
    replace, _ = _install(monkeypatch, needs, existing, _plo("PLO2", ["N2"]))
    await redraft_from_needs(_program(), "cs-test", ["N2"], note_th=None, cause="designer")
    assert "trail_row" not in replace.await_args.kwargs


# --------------------------- send-back ---------------------------


def _real_redraft(monkeypatch: pytest.MonkeyPatch, env: _Env, replace_effect: object) -> AsyncMock:
    monkeypatch.setattr(pf, "redraft_from_needs", redraft_from_needs)
    replace, _ = _install(
        monkeypatch,
        [_need(f"N{i}") for i in range(1, 7)],
        env.plos,
        _plo("PLO3", ["N3"]).model_copy(update={"statement_th": "ร่างใหม่ PLO3"}),
    )
    replace.side_effect = replace_effect
    return replace


async def test_the_applied_row_goes_to_replace_and_is_not_written_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _Env(monkeypatch, [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)])
    replace = _real_redraft(monkeypatch, env, None)
    finding = AlignmentFinding(plo_id="PLO3", reason_th="ไม่ตรง", agreed_runs=2)

    (action,) = await pf.send_back("cs-test", _review(alignment=[finding]), env.initial)

    assert action.outcome == "applied" and action.result_plo_id == "PLO3"
    assert replace.await_args.kwargs["trail_row"] is action
    env.trail.add.assert_not_awaited()


async def test_a_failed_replace_leaves_only_the_failed_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _Env(monkeypatch, [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)])
    _real_redraft(monkeypatch, env, RuntimeError("db down"))
    finding = AlignmentFinding(plo_id="PLO3", reason_th="ไม่ตรง", agreed_runs=2)

    (action,) = await pf.send_back("cs-test", _review(alignment=[finding]), env.initial)

    assert action.outcome == "failed"
    # Only the failed row, written on its own; no applied row anywhere.
    assert [c.args[0] for c in env.trail.add.await_args_list] == [[action]]
