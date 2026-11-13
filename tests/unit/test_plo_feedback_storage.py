"""plo_feedback_actions: the trail of what the PLO review sent back (phase 4).

Same mocked session as test_superseded_plos.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from curriculum_agent.data.orm import PLOFeedbackActionTable
from curriculum_agent.data.repositories import (
    PLOFeedbackRepository,
    PLORepository,
    ProgramRepository,
    _row_to_dict,
)
from curriculum_agent.models import FeedbackAction
from tests.unit.test_superseded_plos import PID, _patched, _Session

T0 = datetime(2026, 11, 3, 12, 0, 0)


def _action(**kw: object) -> FeedbackAction:
    base: dict[str, object] = {
        "program_id": PID,
        "review_created_at": T0,
        "kind": "bloom",
        "outcome": "applied",
    }
    base.update(kw)
    return FeedbackAction.model_validate(base)


def test_feedback_defaults_and_utc_json() -> None:
    a = _action()
    assert a.plo_ids == [] and a.need_ids == []
    assert a.result_plo_id is None and a.result_statement_th is None
    assert a.result_bloom_level is None
    dumped = json.loads(a.model_dump_json())
    assert dumped["created_at"].endswith("+00:00")
    assert dumped["review_created_at"] == T0.replace(tzinfo=UTC).isoformat()


async def test_feedback_add_and_list_newest_first() -> None:
    older = _action(id="a", created_at=T0 - timedelta(hours=1), need_ids=["n1"])
    newer = _action(id="b", created_at=T0, plo_ids=["PLO1"], result_plo_id="PLO1")
    session = _Session()
    with _patched(session):
        await PLOFeedbackRepository().add([older, newer])
    rows = [r for r in session.added if isinstance(r, PLOFeedbackActionTable)]
    assert len(rows) == 2 and session.commits == 1

    listing = _Session(select_rows=[rows[1], rows[0]])
    with _patched(listing):
        out = await PLOFeedbackRepository().list_by_program(PID)
    assert [a.id for a in out] == ["b", "a"]
    assert out[0].plo_ids == ["PLO1"] and out[1].need_ids == ["n1"]
    assert (
        "order by plo_feedback_actions.created_at desc, plo_feedback_actions.id"
        in (listing.sql()[0])
    )
    assert _row_to_dict(rows[0])["program_id"] == PID


async def test_feedback_add_empty_is_a_noop() -> None:
    session = _Session()
    with _patched(session):
        await PLOFeedbackRepository().add([])
    assert session.commits == 0 and not session.added


async def test_delete_by_program_clears_feedback() -> None:
    session = _Session()
    with _patched(session):
        await PLORepository().delete_by_program(PID)
    assert any(s.startswith("delete from plo_feedback_actions") for s in session.sql())
    assert session.commits == 1


async def test_delete_cascade_clears_feedback() -> None:
    session = _Session()
    with _patched(session):
        await ProgramRepository().delete_cascade(PID)
    sql = session.sql()
    feedback_at = next(i for i, s in enumerate(sql) if s.startswith("delete from plo_feedback"))
    program_at = next(i for i, s in enumerate(sql) if s.startswith("delete from programs"))
    assert feedback_at < program_at
