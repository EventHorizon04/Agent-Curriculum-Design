from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from curriculum_agent.api.routes.plos import router
from curriculum_agent.config import settings
from curriculum_agent.graph import DESIGNER_STAGES, REVIEW_NODE_STAGE, build_graph
from curriculum_agent.models import PLO, BloomLevel, JobInfo, PLOSetReview, SMARTCheck
from curriculum_agent.stages import plo_report
from curriculum_agent.stages.plo_review import ReviewAlreadyRunning
from curriculum_agent.stages.plo_review_facts import plo_fingerprint
from tests.support.jobs import InMemoryJobs, SpawnRecorder

app = FastAPI()
app.include_router(router, prefix="/programs/{program_id}/plos")
client = TestClient(app)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
_PLO = PLO(
    plo_id="PLO1",
    program_id="p1",
    statement_th="แปลเอกสารธุรกิจ",
    bloom_level=BloomLevel.APPLY,
    action_verb_th="แปล",
    smart_check=_SMART,
    source_need_ids=["c1"],
    source_evidence_ids=["e1"],
    rationale_th="เหตุผล",
)


def _run_job(resp, jobs_store: InMemoryJobs, spawned: SpawnRecorder) -> JobInfo:
    """The report and review routes answer 202 and do their work in a job body.
    Run it - inside the caller's patches, so it sees them - and hand back the job."""
    assert resp.status_code == 202, resp.text
    spawned.drain()
    return jobs_store.rows[resp.json()["job_id"]]


def _review(fingerprint: str) -> PLOSetReview:
    return PLOSetReview(
        program_id="p1",
        plo_fingerprint=fingerprint,
        model="m",
        created_at=datetime(2026, 10, 5),
        summary_th="ดีแล้ว",
    )


# ------------------------------ graph ------------------------------


def test_plo_review_sits_between_the_plo_checkpoint_and_the_report() -> None:
    graph = build_graph().get_graph()
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("review_plos_node", "plo_review") in edges
    assert ("plo_review", "plo_report") in edges
    assert ("review_plos_node", "plo_report") not in edges


def test_plo_review_is_not_a_designer_stage_or_a_checkpoint() -> None:
    assert "plo_review" not in DESIGNER_STAGES
    assert "plo_review" not in REVIEW_NODE_STAGE


# ------------------------------ report ------------------------------


async def test_the_report_carries_the_review_and_whether_it_is_stale() -> None:
    state = {
        "program_id": "p1",
        "plos": [_PLO.model_dump(mode="json")],
        "plo_review": _review("not-this-set").model_dump(mode="json"),
    }
    with (
        patch.object(plo_report, "NeedRepository") as needs,
        patch.object(plo_report, "PLORepository") as plos_repo,
    ):
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        plos_repo.return_value.bulk_insert = AsyncMock()
        out = await plo_report.run(state)
    assert out["report"]["review"]["summary_th"] == "ดีแล้ว"
    assert out["report"]["review_stale"] is True


async def test_a_report_without_a_review_says_so() -> None:
    state = {"program_id": "p1", "plos": [_PLO.model_dump(mode="json")]}
    with (
        patch.object(plo_report, "NeedRepository") as needs,
        patch.object(plo_report, "PLORepository") as plos_repo,
    ):
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        plos_repo.return_value.bulk_insert = AsyncMock()
        out = await plo_report.run(state)
    assert out["report"]["review"] is None
    assert out["report"]["review_stale"] is False


# ------------------------------ routes ------------------------------


def test_report_route_runs_the_review_first(jobs_store, spawned) -> None:
    review_run = AsyncMock(
        side_effect=lambda s: {
            **s,
            "plo_review": _review(plo_fingerprint([_PLO], {})).model_dump(mode="json"),
        }
    )
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.run", review_run),
        patch.object(plo_report, "NeedRepository") as needs,
        patch.object(plo_report, "PLORepository") as plos_repo,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        plos_repo.return_value.bulk_insert = AsyncMock()
        resp = client.post("/programs/p1/plos/report/run")
        job = _run_job(resp, jobs_store, spawned)
    assert job.status == "succeeded", job.error_th
    body = job.result
    assert body["review"]["summary_th"] == "ดีแล้ว"
    assert body["review_stale"] is False
    assert body["review_enabled"] is False  # conftest kill switch
    review_run.assert_awaited_once()


def test_report_route_re_reads_the_plos_after_the_review_call(jobs_store, spawned) -> None:
    """The review call can run for up to plo_review_timeout_seconds (180s) —
    long enough for a PUT edit, a merge, or a re-synthesis to land on this
    program while it is in flight. The route must persist and report what is
    actually stored afterwards (set B), not the snapshot it read before
    starting the review (set A) — otherwise plo_report.bulk_insert reverts
    whatever changed in the meantime."""
    plo_b = _PLO.model_copy(update={"statement_th": "แปลเอกสารราชการ"})
    review_run = AsyncMock(
        side_effect=lambda s: {
            **s,
            "plo_review": _review(plo_fingerprint([_PLO], {})).model_dump(mode="json"),
        }
    )
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.run", review_run),
        patch.object(plo_report, "NeedRepository") as needs,
        patch.object(plo_report, "PLORepository") as plos_repo,
    ):
        repo.list_by_program = AsyncMock(side_effect=[[_PLO], [plo_b]])
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        bulk_insert = AsyncMock()
        plos_repo.return_value.bulk_insert = bulk_insert
        resp = client.post("/programs/p1/plos/report/run")
        job = _run_job(resp, jobs_store, spawned)
    assert job.status == "succeeded", job.error_th
    assert repo.list_by_program.await_count == 2
    body = job.result
    assert [p["statement_th"] for p in body["plos"]] == ["แปลเอกสารราชการ"]
    inserted = bulk_insert.await_args.args[0]
    assert [p.statement_th for p in inserted] == ["แปลเอกสารราชการ"]
    # The review was built from set A's fingerprint; what was actually
    # persisted is set B, so the review is reported stale.
    assert body["review_stale"] is True


def test_report_job_fails_when_the_re_read_finds_nothing(jobs_store, spawned) -> None:
    """The precondition read found PLOs, so the request is accepted; the re-read
    after the review found none, so the job fails with the 422's own text."""
    review_run = AsyncMock(side_effect=lambda s: {**s, "plo_review": None})
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.run", review_run),
    ):
        repo.list_by_program = AsyncMock(side_effect=[[_PLO], []])
        resp = client.post("/programs/p1/plos/report/run")
        job = _run_job(resp, jobs_store, spawned)
    assert job.status == "failed"
    assert job.error_th == "ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน"


def test_report_route_review_enabled_true_when_the_slot_is_on(
    monkeypatch, jobs_store, spawned
) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    review_run = AsyncMock(side_effect=lambda s: {**s, "plo_review": None})
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.run", review_run),
        patch.object(plo_report, "NeedRepository") as needs,
        patch.object(plo_report, "PLORepository") as plos_repo,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        plos_repo.return_value.bulk_insert = AsyncMock()
        resp = client.post("/programs/p1/plos/report/run")
        job = _run_job(resp, jobs_store, spawned)
    assert job.status == "succeeded", job.error_th
    assert job.result["review_enabled"] is True


def test_get_review_reports_staleness() -> None:
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.api.routes.plos.PLOReviewRepository") as rr,
        patch("curriculum_agent.api.routes.plos.NeedRepository") as needs,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        rr.return_value.get = AsyncMock(return_value=_review("old"))
        resp = client.get("/programs/p1/plos/review")
    assert resp.status_code == 200
    assert resp.json()["stale"] is True


def test_get_review_with_none_stored() -> None:
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.api.routes.plos.PLOReviewRepository") as rr,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        rr.return_value.get = AsyncMock(return_value=None)
        resp = client.get("/programs/p1/plos/review")
    # conftest's kill switch has the slot off for every test, so review_enabled
    # reads false here — it answers "is the slot on", independent of whether a
    # row was ever stored.
    assert resp.json() == {"review": None, "stale": False, "review_enabled": False}


def test_get_review_review_enabled_true_when_the_slot_is_on(monkeypatch) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.api.routes.plos.PLOReviewRepository") as rr,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        rr.return_value.get = AsyncMock(return_value=None)
        resp = client.get("/programs/p1/plos/review")
    assert resp.json()["review_enabled"] is True


def test_get_review_guards_a_storage_read_failure() -> None:
    """A raise from PLOReviewRepository().get must not 500 the whole route —
    GET /review answers review=None, stale=False rather than losing the page."""
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.api.routes.plos.PLOReviewRepository") as rr,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        rr.return_value.get = AsyncMock(side_effect=RuntimeError("db down"))
        resp = client.get("/programs/p1/plos/review")
    assert resp.status_code == 200
    assert resp.json() == {"review": None, "stale": False, "review_enabled": False}


def test_review_run_422_without_plos() -> None:
    with patch("curriculum_agent.api.routes.plos._repo") as repo:
        repo.list_by_program = AsyncMock(return_value=[])
        assert client.post("/programs/p1/plos/review/run").status_code == 422


def test_review_run_503_when_switched_off() -> None:
    # conftest switches the slot off for every test.
    with patch("curriculum_agent.api.routes.plos._repo") as repo:
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        resp = client.post("/programs/p1/plos/review/run")
    assert resp.status_code == 503


def test_review_run_job_fails_when_the_review_failed(monkeypatch, jobs_store, spawned) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.fresh_review", AsyncMock(return_value=None)),
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        job = _run_job(client.post("/programs/p1/plos/review/run"), jobs_store, spawned)
    assert job.status == "failed"
    assert job.error_th == "ตรวจชุด PLO ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง"


def test_review_run_409_while_a_job_is_running_on_the_program(
    monkeypatch, jobs_store, spawned
) -> None:
    """The refusal a second review used to get from the stage's own guard is now
    the job rule's: one active writer per program, answered before any work."""
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    jobs_store.rows["already"] = JobInfo(
        job_id="already",
        program_id="p1",
        kind="plo_review",
        status="running",
        created_at=datetime(2026, 10, 8, 3, 0),
    )
    fresh = AsyncMock(return_value=_review(plo_fingerprint([_PLO], {})))
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.fresh_review", fresh),
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        resp = client.post("/programs/p1/plos/review/run")
    assert resp.status_code == 409
    assert isinstance(resp.json()["detail"], str)
    assert list(jobs_store.rows) == ["already"]
    assert spawned.coros == []
    fresh.assert_not_awaited()


def test_review_run_job_fails_with_the_stage_message_when_its_own_guard_fires(
    monkeypatch, jobs_store, spawned
) -> None:
    """Should the stage's single-flight guard ever fire inside a job, it is that
    job's failure - with the stage's own Thai message - not a request error."""
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch(
            "curriculum_agent.stages.plo_review.fresh_review",
            AsyncMock(side_effect=ReviewAlreadyRunning("กำลังตรวจ")),
        ),
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        job = _run_job(client.post("/programs/p1/plos/review/run"), jobs_store, spawned)
    assert job.status == "failed"
    assert job.error_th == "กำลังตรวจ"


def test_review_run_returns_the_fresh_review(monkeypatch, jobs_store, spawned) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    fresh = _review(plo_fingerprint([_PLO], {}))
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.fresh_review", AsyncMock(return_value=fresh)),
        patch("curriculum_agent.api.routes.plos.NeedRepository") as needs,
    ):
        repo.list_by_program = AsyncMock(return_value=[_PLO])
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        resp = client.post("/programs/p1/plos/review/run")
        job = _run_job(resp, jobs_store, spawned)
    assert job.status == "succeeded", job.error_th
    body = job.result
    assert body["review"]["summary_th"] == "ดีแล้ว" and body["stale"] is False
    assert body["review_enabled"] is True


def test_review_run_reports_staleness_from_the_set_read_after_the_call(
    monkeypatch, jobs_store, spawned
) -> None:
    """fresh_review answers the call it made against the PLOs it was handed, but
    the stale flag must reflect whatever is stored by the time the route
    answers — a merge or an edit could have landed while the (up to 180s) call
    was in flight. Second list_by_program call returns a different set from the
    first, so the review's own fingerprint (set A) is now stale against it."""
    monkeypatch.setattr(settings, "plo_review_provider", "openrouter")
    plo_b = _PLO.model_copy(update={"statement_th": "แปลเอกสารราชการ"})
    fresh = _review(plo_fingerprint([_PLO], {}))
    with (
        patch("curriculum_agent.api.routes.plos._repo") as repo,
        patch("curriculum_agent.stages.plo_review.fresh_review", AsyncMock(return_value=fresh)),
        patch("curriculum_agent.api.routes.plos.NeedRepository") as needs,
    ):
        repo.list_by_program = AsyncMock(side_effect=[[_PLO], [plo_b]])
        needs.return_value.list_by_program = AsyncMock(return_value=[])
        resp = client.post("/programs/p1/plos/review/run")
        job = _run_job(resp, jobs_store, spawned)
    assert job.status == "succeeded", job.error_th
    assert job.result["stale"] is True
