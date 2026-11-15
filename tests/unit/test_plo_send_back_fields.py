"""PLO.designer_sent_back_at / designer_send_back_reason_th: the storage side."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from curriculum_agent.data.orm import PLOTable
from curriculum_agent.data.repositories import (
    PLOChangedDuringRedraft,
    PLORepository,
    _row_to_dict,
)
from tests.unit.test_superseded_plos import PID, _patched, _plo, _plo_row, _Session

T0 = datetime(2026, 11, 15, 9, 30, 0)
REASON = "ช่วยเขียนให้วัดผลได้"


async def test_both_fields_round_trip_through_the_row_mapping() -> None:
    plo = _plo("PLO1").model_copy(
        update={"designer_sent_back_at": T0, "designer_send_back_reason_th": REASON}
    )
    session = _Session()
    with _patched(session):
        await PLORepository().bulk_insert([plo])
    (row,) = [a for a in session.added if isinstance(a, PLOTable)]
    assert row.designer_sent_back_at == T0 and isinstance(row.designer_sent_back_at, datetime)
    assert row.designer_send_back_reason_th == REASON
    session = _Session(select_rows=[row])
    with _patched(session):
        (back,) = await PLORepository().list_by_program(PID)
    assert back.designer_sent_back_at == T0
    assert back.designer_send_back_reason_th == REASON
    assert _row_to_dict(row)["designer_send_back_reason_th"] == REASON


def test_json_carries_the_offset() -> None:
    plo = _plo("PLO1").model_copy(update={"designer_sent_back_at": T0})
    assert plo.model_dump(mode="json")["designer_sent_back_at"] == "2026-11-15T09:30:00+00:00"
    assert _plo("PLO1").model_dump(mode="json")["designer_sent_back_at"] is None


async def _replace(session: _Session, cause: str) -> int:
    with _patched(session):
        return await PLORepository().replace(
            PID, ["PLO1"], [_plo("PLO1")], cause=cause, expect={"PLO1": 1}
        )


def _row(**changes: Any) -> PLOTable:
    row = _plo_row("PLO1", "ออกแบบระบบ ก ได้")
    for key, value in changes.items():
        setattr(row, key, value)
    return row


async def test_review_replace_over_a_sent_back_row_raises() -> None:
    session = _Session(select_rows=[_row(designer_sent_back_at=T0)])
    with pytest.raises(PLOChangedDuringRedraft):
        await _replace(session, "review")
    assert session.commits == 0


async def test_send_back_replace_over_a_hand_edited_row_is_allowed() -> None:
    session = _Session(select_rows=[_row(designer_edited_at=T0)])
    await _replace(session, "send_back")
    assert session.commits == 1
