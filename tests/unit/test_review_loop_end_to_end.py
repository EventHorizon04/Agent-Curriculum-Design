"""The review loop end to end, stubbed at the repositories (final review I5).

`test_plo_review_loop.py` fakes `send_back`; these run the real job body, the
real loop and the real send-back, with only the database, the reviewer
(`plo_review._review`) and the redraft replaced. The conftest `off` mode and the
review-chain recorder stay the default; each test here overrides them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.config import settings
from curriculum_agent.data.repositories import (
    NeedRepository,
    PLOFeedbackRepository,
    PLORepository,
    PLOReviewRepository,
    ProgramRepository,
)
from curriculum_agent.models import PLO, AlignmentFinding, FeedbackAction, PLOSetReview
from curriculum_agent.stages import plo_feedback as pf
from curriculum_agent.stages import plo_review as pr
from tests.support.jobs import InMemoryJobs, SpawnRecorder
from tests.unit.test_api_plos import _need, _plo, _program

client = TestClient(app)


def _review(n: int, **kw: Any) -> PLOSetReview:
    return PLOSetReview(
        program_id="cs-test",
        plo_fingerprint=f"f{n}",
        model="m",
        created_at=datetime(2026, 11, 5, 9, 0, n),
        reviewed_by="agent",
        agreement_threshold=2,
        **kw,
    )


class _World:
    """The stored program: six PLOs, their Needs, and every row written."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, reviews: list[PLOSetReview]) -> None:
        self.plos = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)]
        self.needs = [_need(f"N{i}") for i in range(1, 7)]
        self.reviews = list(reviews)
        self.stored_reviews: list[PLOSetReview] = []
        self.trail: list[FeedbackAction] = []  # rows written on their own
        self.replace_rows: list[FeedbackAction] = []  # rows written by the replace

        async def _list_plos(_self: object, _pid: str) -> list[PLO]:
            return list(self.plos)

        async def _list_needs(_self: object, _pid: str) -> list[Any]:
            return list(self.needs)

        async def _add(_self: object, rows: list[FeedbackAction]) -> None:
            self.trail.extend(rows)

        async def _upsert(_self: object, review: PLOSetReview) -> None:
            self.stored_reviews.append(review)

        async def _next_review(_pid: str, _plos: object) -> PLOSetReview:
            return self.reviews.pop(0)

        async def _redraft(
            _program: object,
            _pid: str,
            need_ids: list[str],
            *,
            note_th: str | None,
            cause: str,
            accept: Any = None,
            trail: Any = None,
        ) -> tuple[PLO, list[str]]:
            gone = [p.plo_id for p in self.plos if set(p.source_need_ids) & set(need_ids)]
            new = _plo(gone[0], need_ids).model_copy(update={"statement_th": "ร่างใหม่"})
            if trail is not None:
                self.replace_rows.append(trail(new))
            self.plos = [p for p in self.plos if p.plo_id not in gone] + [new]
            return new, gone

        monkeypatch.setattr(PLORepository, "list_by_program", _list_plos)
        monkeypatch.setattr(NeedRepository, "list_by_program", _list_needs)
        monkeypatch.setattr(NeedRepository, "list_active_by_program", _list_needs)
        monkeypatch.setattr(ProgramRepository, "get", AsyncMock(return_value=_program()))
        monkeypatch.setattr(PLOFeedbackRepository, "add", _add)
        monkeypatch.setattr(PLOReviewRepository, "upsert", _upsert)
        monkeypatch.setattr(PLOReviewRepository, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(pr, "PLOReviewRepository", PLOReviewRepository)
        monkeypatch.setattr(pr, "_review", _next_review)
        self.redraft = AsyncMock(side_effect=_redraft)
        monkeypatch.setattr(pf, "redraft_from_needs", self.redraft)
        monkeypatch.setattr(settings, "plo_review_send_back", True)
        monkeypatch.setattr(settings, "plo_review_max_rounds", 3)
        monkeypatch.setattr(settings, "plo_review_loop_timeout_seconds", 5400)


@pytest.mark.review_chain
def test_review_run_in_apply_mode_runs_the_loop_to_its_end(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    world = _World(
        monkeypatch,
        [
            _review(
                1, alignment=[AlignmentFinding(plo_id="PLO3", reason_th="ไม่ตรง", agreed_runs=2)]
            ),
            _review(2),  # the redrafted set passes
        ],
    )
    monkeypatch.setattr(settings, "plo_review_loop_mode", "apply")

    response = client.post("/programs/cs-test/plos/review/run")
    assert response.status_code == 202, response.text
    spawned.drain()

    job = jobs_store.rows[response.json()["job_id"]]
    assert job.status == "succeeded", job.error_th
    feedback = [FeedbackAction.model_validate(r) for r in job.result["feedback"]]
    assert [(r.kind, r.outcome, r.round) for r in feedback] == [
        ("alignment", "applied", 1),
        ("loop_end", "stopped", 2),
    ]
    assert feedback[-1].outcome_reason_th == "ผ่านการตรวจ — ไม่มีข้อที่ต้องแก้"
    # The applied row went in with its replace, the loop_end row on its own.
    assert [r.kind for r in world.replace_rows] == ["alignment"]
    assert [r.kind for r in world.trail] == ["loop_end"]
    assert [r.plo_fingerprint for r in world.stored_reviews] == ["f1", "f2"]
    assert job.result["review"]["plo_fingerprint"] == "f2"
    assert "cs-test" not in pr._REVIEW_IN_FLIGHT


async def test_graph_node_in_shadow_mode_reloads_the_plos_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(
        monkeypatch,
        [_review(1, alignment=[AlignmentFinding(plo_id="PLO3", reason_th="ไม่ตรง", agreed_runs=2)])],
    )
    monkeypatch.setattr(settings, "plo_review_loop_mode", "shadow")
    # The checkpoint copy differs from the store: the node must hand on the store's.
    # PLO2 was edited in the store after the state was copied; PLO3, which the
    # finding names, is the same in both.
    stale_copy = list(world.plos)
    world.plos[1] = world.plos[1].model_copy(update={"statement_th": "แก้ไว้ในฐานข้อมูล"})

    state = await pr.run(
        {"program_id": "cs-test", "plos": [p.model_dump(mode="json") for p in stale_copy]}
    )

    assert state["current_stage"] == "plo_review"
    assert state["plo_review"] is not None and state["plo_review"]["plo_fingerprint"] == "f1"
    assert [PLO.model_validate(p) for p in state["plos"]] == world.plos
    assert state["plos"][1]["statement_th"] == "แก้ไว้ในฐานข้อมูล"
    world.redraft.assert_not_awaited()  # shadow plans, never redrafts
    assert [(r.kind, r.outcome) for r in world.trail] == [
        ("alignment", "planned"),
        ("loop_end", "stopped"),
    ]
    assert "cs-test" not in pr._REVIEW_IN_FLIGHT
