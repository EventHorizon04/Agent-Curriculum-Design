from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from curriculum_agent.models import NOTE_MAX_CHARS, PLO
from curriculum_agent.stages import plo_send_back as sb
from curriculum_agent.stages.plo_redraft import RedraftFailed, RedraftRefused
from curriculum_agent.stages.plo_send_back import (
    PloSendBackItem,
    PloSendBackRequest,
    send_back_plos,
)
from tests.unit.test_api_plos import _plo, _program


def _items(*pairs: tuple[str, str]) -> list[PloSendBackItem]:
    return [PloSendBackItem(plo_id=p, reason_th=r) for p, r in pairs]


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> list[PLO]:
    rows = [_plo("PLO1", ["N1"]), _plo("PLO2", ["N2", "N3"])]
    monkeypatch.setattr(sb.PLORepository, "list_by_program", AsyncMock(return_value=rows))
    return rows


def test_item_strips_and_bounds_reason() -> None:
    assert PloSendBackItem(plo_id="PLO1", reason_th="  ปรับ  ").reason_th == "ปรับ"
    with pytest.raises(ValidationError):
        PloSendBackItem(plo_id="PLO1", reason_th="   ")
    with pytest.raises(ValidationError):
        PloSendBackItem(plo_id="PLO1", reason_th="ก" * (NOTE_MAX_CHARS + 1))


def test_request_needs_items_and_unique_ids() -> None:
    with pytest.raises(ValidationError):
        PloSendBackRequest(items=[])
    with pytest.raises(ValidationError):
        PloSendBackRequest(items=_items(("PLO1", "ก"), ("PLO1", "ข")))


async def test_runs_in_order_with_needs_note_cause_and_stamped_drafter(
    stored: list[PLO], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    drafted = _plo("PLO1", ["N1"]).model_copy(update={"statement_th": "ออกแบบระบบใหม่ได้"})
    base = AsyncMock(return_value=drafted)

    async def fake_redraft(program, program_id, need_ids, *, note_th, cause, drafter):  # noqa: ANN001
        draft = await drafter("prog", ["n"], program_id, {"N1"}, "PLO1", note_th=note_th)
        calls.append({"need_ids": need_ids, "note_th": note_th, "cause": cause, "draft": draft})
        return draft, ["PLO1"]

    monkeypatch.setattr(sb, "redraft_from_needs", fake_redraft)
    result = await send_back_plos(
        _program(), "cs-test", _items(("PLO2", "ข"), ("PLO1", "ก")), drafter=base
    )

    assert [c["need_ids"] for c in calls] == [["N2", "N3"], ["N1"]]
    assert [c["note_th"] for c in calls] == ["ข", "ก"]
    assert {c["cause"] for c in calls} == {"send_back"}
    first = calls[0]["draft"]
    assert first.designer_send_back_reason_th == "ข"
    assert first.designer_sent_back_at is not None
    assert first.designer_sent_back_at.tzinfo is None
    assert [o.status for o in result.outcomes] == ["rewritten", "rewritten"]
    assert result.outcomes[0].result_statement_th == "ออกแบบระบบใหม่ได้"
    assert result.outcomes[0].result_plo_id == "PLO1"


async def test_missing_refused_failed_do_not_stop_later_items(
    stored: list[PLO], monkeypatch: pytest.MonkeyPatch
) -> None:
    outcomes = iter(
        [RedraftRefused(422, "Need นี้ถูกตัดออกแล้ว"), RedraftFailed(), (_plo("PLO2", ["N2"]), [])]
    )

    async def fake_redraft(*args, **kwargs):  # noqa: ANN002, ANN003
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o

    monkeypatch.setattr(sb, "redraft_from_needs", fake_redraft)
    result = await send_back_plos(
        _program(),
        "cs-test",
        _items(("PLO9", "ก"), ("PLO1", "ข"), ("PLO2", "ค"), ("PLO1", "ง")),
        drafter=AsyncMock(),
    )
    got = [(o.plo_id, o.status, o.detail_th) for o in result.outcomes]
    assert got == [
        ("PLO9", "refused", "ไม่พบ PLO นี้แล้ว — ชุด PLO เปลี่ยนไป"),
        ("PLO1", "refused", "Need นี้ถูกตัดออกแล้ว"),
        ("PLO2", "failed", "AI เขียนข้อนี้ใหม่ไม่สำเร็จ"),
        ("PLO1", "rewritten", ""),
    ]


async def test_http_and_generic_errors_fail_one_item_not_the_job(
    stored: list[PLO], monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    outcomes = iter(
        [
            HTTPException(502, "ไม่ได้ PLO กลับมา"),
            RuntimeError("provider down"),
            (_plo("PLO2", ["N2"]), []),
        ]
    )

    async def fake_redraft(*args, **kwargs):  # noqa: ANN002, ANN003
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o

    monkeypatch.setattr(sb, "redraft_from_needs", fake_redraft)
    result = await send_back_plos(
        _program(),
        "cs-test",
        _items(("PLO1", "ก"), ("PLO2", "ข")),
        drafter=AsyncMock(),
    )
    # a third item would be needed for the success; reuse PLO1 twice is not allowed
    # by the request model, but the function itself takes any sequence
    result2 = await send_back_plos(
        _program(), "cs-test", _items(("PLO2", "ค")), drafter=AsyncMock()
    )
    got = [(o.plo_id, o.status, o.detail_th) for o in result.outcomes]
    assert got == [
        ("PLO1", "failed", "ไม่ได้ PLO กลับมา"),
        ("PLO2", "failed", "AI เขียนข้อนี้ใหม่ไม่สำเร็จ"),
    ]
    assert result2.outcomes[0].status == "rewritten"
