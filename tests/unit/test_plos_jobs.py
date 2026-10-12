"""The four PLO routes answer 202 and run their work as a background job.

Preconditions (404 / 422 / 503 / 401) stay synchronous and create no job row;
the work itself runs when the recorded job body is drained. Every success test
drains and asserts on the outcome: an undrained body is closed silently at
teardown, so a 202-only assertion would pass over a work closure that does
nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.config import settings
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    JobInfo,
    KSECCategory,
    Need,
    PLOSetReview,
    ProgramMetadata,
    SMARTCheck,
)
from curriculum_agent.stages.plo_review import ReviewAlreadyRunning
from curriculum_agent.stages.plo_review_facts import need_demands, plo_fingerprint
from curriculum_agent.stages.plo_synthesis import SynthesisAlreadyRunning
from tests.support.jobs import InMemoryJobs, SpawnRecorder

client = TestClient(app)

BASE = "/programs/cs-test/plos"
NOTE = "เน้นทักษะด้าน AI"
NO_PLOS_TH = "ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน"

# (url, job kind, params a bare POST records)
ROUTES = [
    (f"{BASE}/run", "plo_synthesis", {"note_th": None, "run_validation": True}),
    (f"{BASE}/report/run", "plo_report", {}),
    (f"{BASE}/review/run", "plo_review", {}),
    (f"{BASE}/PLO1/revalidate", "plo_revalidate", {"plo_id": "PLO1"}),
]
ROUTE_IDS = ["plo_synthesis", "plo_report", "plo_review", "plo_revalidate"]


def _program() -> ProgramMetadata:
    return ProgramMetadata(
        program_id="cs-test",
        name_th="วิทยาการคอมพิวเตอร์",
        name_en="Computer Science",
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
        program_goals_th=["เป้าหมายหลักสูตรที่ 1"],
        program_objectives_th=["ผลิตบัณฑิตที่มีทักษะด้านซอฟต์แวร์"],
    )


def _need() -> Need:
    return Need(
        need_id="N1",
        program_id="cs-test",
        statement_th="ต้องการบัณฑิตที่ออกแบบซอฟต์แวร์ตามความต้องการของธุรกิจได้",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.CREATE,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=1,
        demand_score=0.8,
    )


def _plo() -> PLO:
    return PLO(
        plo_id="PLO1",
        program_id="cs-test",
        statement_th="ออกแบบและพัฒนาซอฟต์แวร์ที่มีคุณภาพได้",
        bloom_level=BloomLevel.CREATE,
        action_verb_th="ออกแบบ",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=["N1"],
        source_evidence_ids=["E1"],
        rationale_th="ทักษะหลักที่นายจ้างต้องการ",
    )


def _review() -> PLOSetReview:
    return PLOSetReview(
        program_id="cs-test",
        plo_fingerprint=plo_fingerprint([_plo()], need_demands([_need()])),
        model="m",
        created_at=datetime(2026, 10, 8),
        summary_th="ดีแล้ว",
    )


class _Env:
    """Every boundary the four routes reach, patched where the routes look them up."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.program = AsyncMock(return_value=_program())
        self.needs = AsyncMock(return_value=[_need()])
        self.plos = AsyncMock(return_value=[_plo()])
        self.bulk_insert = AsyncMock()
        monkeypatch.setattr(plos_route.ProgramRepository, "get", self.program)
        monkeypatch.setattr(plos_route.NeedRepository, "list_by_program", self.needs)
        # On the class, never the module-level `_repo` instance (see test_api_plos).
        monkeypatch.setattr(plos_route.PLORepository, "list_by_program", self.plos)
        monkeypatch.setattr(plos_route.PLORepository, "bulk_insert", self.bulk_insert)
        # The set review is off in every test by default (tests/conftest.py); the
        # review route and the report's `review_enabled` need it on to be exercised.
        monkeypatch.setattr(settings, "plo_review_provider", "openrouter")

        async def synth_run(state: dict[str, Any]) -> dict[str, Any]:
            return {**state, "plos": [_plo().model_dump(mode="json")]}

        async def review_run(state: dict[str, Any]) -> dict[str, Any]:
            return {**state, "plo_review": None}  # the report must never call this

        async def report_run(state: dict[str, Any]) -> dict[str, Any]:
            return {
                **state,
                "report": {
                    "plos": state["plos"],
                    "counts": {"total": len(state["plos"])},
                    "needs_by_id": {"N1": _need().model_dump(mode="json")},
                    "needs_not_synthesized": [],
                },
            }

        async def validate(draft: Any, **kwargs: Any) -> PLO:
            return _plo().model_copy(
                update={"smart_validated_by": "agent", "smart_diagnosis_th": "ตรวจแล้วผ่าน"}
            )

        self.synth = AsyncMock(side_effect=synth_run)
        self.review_run = AsyncMock(side_effect=review_run)
        self.report = AsyncMock(side_effect=report_run)
        self.fresh_review = AsyncMock(return_value=_review())
        self.validate = AsyncMock(side_effect=validate)
        monkeypatch.setattr("curriculum_agent.stages.plo_synthesis.run", self.synth)
        monkeypatch.setattr("curriculum_agent.stages.plo_review.run", self.review_run)
        monkeypatch.setattr("curriculum_agent.stages.plo_report.run", self.report)
        monkeypatch.setattr("curriculum_agent.stages.plo_review.fresh_review", self.fresh_review)
        monkeypatch.setattr(
            "curriculum_agent.stages.plo_synthesis.validate_and_build", self.validate
        )

    def untouched(self) -> bool:
        """True when no stage-level work has started."""
        return not any(
            m.await_count
            for m in (self.synth, self.review_run, self.report, self.fresh_review, self.validate)
        )


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> _Env:
    return _Env(monkeypatch)


def _put_running(store: InMemoryJobs, program_id: str = "cs-test") -> None:
    store.rows["already"] = JobInfo(
        job_id="already",
        program_id=program_id,
        kind="needs_pipeline",
        status="running",
        created_at=datetime(2026, 10, 8, 3, 0),
    )


def _finish(r: Any, jobs_store: InMemoryJobs, spawned: SpawnRecorder) -> JobInfo:
    assert r.status_code == 202, r.text
    spawned.drain()
    return jobs_store.rows[r.json()["job_id"]]


# --- 202, then the work runs when the job body is drained --------------------


@pytest.mark.parametrize(("url", "kind", "params"), ROUTES, ids=ROUTE_IDS)
def test_run_answers_202_with_the_kind_and_has_not_started_the_work(
    url: str,
    kind: str,
    params: dict[str, Any],
    env: _Env,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    r = client.post(url)

    assert r.status_code == 202, r.text
    body = r.json()
    assert body["kind"] == kind
    assert body["status"] == "running"
    assert body["params"] == params
    assert body["label_th"]
    # Answered before the stage ran: that is the whole point of the job.
    assert env.untouched()
    assert len(spawned.coros) == 1

    spawned.drain()

    job = jobs_store.rows[body["job_id"]]
    assert job.status == "succeeded", job.error_th
    assert not env.untouched()


def test_synthesis_result_is_the_old_list_of_plos(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    job = _finish(client.post(f"{BASE}/run"), jobs_store, spawned)

    env.synth.assert_awaited_once()
    assert isinstance(job.result, list)
    assert [p["plo_id"] for p in job.result] == ["PLO1"]
    assert job.result[0]["statement_th"] == _plo().statement_th


def test_report_result_is_the_old_report_payload(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    job = _finish(client.post(f"{BASE}/report/run"), jobs_store, spawned)

    env.report.assert_awaited_once()
    assert set(job.result) == {"plos", "counts", "needs_by_id", "needs_not_synthesized"}
    assert [p["plo_id"] for p in job.result["plos"]] == ["PLO1"]
    assert job.result["needs_by_id"]["N1"]["need_id"] == "N1"


def test_the_report_job_never_runs_the_review(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    job = _finish(client.post(f"{BASE}/report/run"), jobs_store, spawned)

    assert job.status == "succeeded"
    env.review_run.assert_not_awaited()
    env.fresh_review.assert_not_awaited()
    for key in ("review", "review_stale", "review_enabled"):
        assert key not in job.result


def test_review_with_the_slot_off_is_still_a_job(
    env: _Env,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    monkeypatch.setattr(settings, "plo_review_provider", "")

    r = client.post(f"{BASE}/review/run")

    assert r.status_code == 202
    job = _finish(r, jobs_store, spawned)
    assert job.status == "succeeded", job.error_th
    env.fresh_review.assert_awaited_once()
    assert job.result["review_enabled"] is False


def test_review_result_is_the_old_review_body(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    job = _finish(client.post(f"{BASE}/review/run"), jobs_store, spawned)

    env.fresh_review.assert_awaited_once()
    assert job.result["review"]["summary_th"] == "ดีแล้ว"
    assert job.result["stale"] is False
    assert job.result["review_enabled"] is True


def test_revalidate_result_is_the_old_plo_body_and_it_is_stored(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    job = _finish(client.post(f"{BASE}/PLO1/revalidate"), jobs_store, spawned)

    env.validate.assert_awaited_once()
    assert job.result["plo_id"] == "PLO1"
    assert job.result["smart_validated_by"] == "agent"
    assert job.result["version"] == _plo().version + 1
    env.bulk_insert.assert_awaited_once()


# --- the synthesis switch and the note travel through the job ----------------


def test_run_validation_false_is_recorded_and_reaches_the_stage_state(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    r = client.post(f"{BASE}/run", json={"run_validation": False})

    assert r.status_code == 202, r.text
    assert r.json()["params"]["run_validation"] is False
    spawned.drain()

    assert env.synth.await_args.args[0]["run_validation"] is False


def test_the_default_run_leaves_the_switch_out_of_the_stage_state(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    r = client.post(f"{BASE}/run", json={})

    assert r.json()["params"] == {"note_th": None, "run_validation": True}
    spawned.drain()

    assert "run_validation" not in env.synth.await_args.args[0]
    assert "designer_note" not in env.synth.await_args.args[0]


def test_the_note_is_recorded_and_reaches_the_stage_state(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    r = client.post(f"{BASE}/run", json={"note_th": NOTE})

    assert r.json()["params"] == {"note_th": NOTE, "run_validation": True}
    spawned.drain()

    assert env.synth.await_args.args[0]["designer_note"] == NOTE


# --- preconditions stay synchronous and create no job row --------------------


def _assert_no_job(jobs_store: InMemoryJobs, spawned: SpawnRecorder, env: _Env) -> None:
    assert jobs_store.rows == {}
    assert spawned.coros == []
    assert env.untouched()


def test_synthesis_unknown_program_is_a_synchronous_404(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    env.program.return_value = None

    r = client.post(f"{BASE}/run")

    assert r.status_code == 404
    _assert_no_job(jobs_store, spawned, env)


def test_synthesis_without_needs_is_a_synchronous_422(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    env.needs.return_value = []

    r = client.post(f"{BASE}/run")

    assert r.status_code == 422
    assert "Need" in r.json()["detail"]
    _assert_no_job(jobs_store, spawned, env)


@pytest.mark.parametrize("url", [f"{BASE}/report/run", f"{BASE}/review/run"])
def test_report_and_review_without_plos_are_a_synchronous_422(
    url: str, env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    env.plos.return_value = []

    r = client.post(url)

    assert r.status_code == 422
    assert r.json()["detail"] == NO_PLOS_TH
    _assert_no_job(jobs_store, spawned, env)


def test_revalidate_unknown_program_is_a_synchronous_404(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    env.program.return_value = None

    r = client.post(f"{BASE}/PLO1/revalidate")

    assert r.status_code == 404
    _assert_no_job(jobs_store, spawned, env)


def test_revalidate_unknown_plo_is_a_synchronous_404(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    r = client.post(f"{BASE}/PLO9/revalidate")

    assert r.status_code == 404
    _assert_no_job(jobs_store, spawned, env)


def test_revalidate_with_the_needs_gone_is_a_synchronous_422(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    env.needs.return_value = []

    r = client.post(f"{BASE}/PLO1/revalidate")

    assert r.status_code == 422
    assert "Need" in r.json()["detail"]
    _assert_no_job(jobs_store, spawned, env)


def test_revalidate_still_requires_the_api_key_when_one_is_configured(
    env: _Env,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    monkeypatch.setattr(settings, "api_key", SecretStr("right-key"))

    r = client.post(f"{BASE}/PLO1/revalidate")

    assert r.status_code == 401
    _assert_no_job(jobs_store, spawned, env)

    ok = client.post(f"{BASE}/PLO1/revalidate", headers={"X-API-Key": "right-key"})
    assert ok.status_code == 202, ok.text
    spawned.drain()


# --- failures inside the work become failed jobs with the Thai text ----------


def test_a_database_error_from_the_review_fails_the_job_with_its_message(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    env.fresh_review.side_effect = RuntimeError("db")

    job = _finish(client.post(f"{BASE}/review/run"), jobs_store, spawned)

    assert job.status == "failed"
    assert job.error_th == "db"


def test_a_review_already_running_inside_the_job_fails_the_job_with_its_message(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    env.fresh_review.side_effect = ReviewAlreadyRunning("กำลังตรวจชุด PLO ของโปรแกรมนี้อยู่")

    job = _finish(client.post(f"{BASE}/review/run"), jobs_store, spawned)

    assert job.status == "failed"
    assert job.error_th == "กำลังตรวจชุด PLO ของโปรแกรมนี้อยู่"


def test_a_synthesis_already_running_inside_the_job_fails_the_job_not_the_request(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    """The route no longer maps the stage's refusal to a 409: the job rule refuses
    a second run first, and should the stage's own guard ever fire inside a job it
    is that job's failure, with the stage's own Thai message."""
    env.synth.side_effect = SynthesisAlreadyRunning("กำลังสังเคราะห์ PLO อยู่ — รอให้รอบเดิมเสร็จก่อน")

    r = client.post(f"{BASE}/run")
    assert r.status_code == 202
    spawned.drain()

    job = jobs_store.rows[r.json()["job_id"]]
    assert job.status == "failed"
    assert job.error_th == "กำลังสังเคราะห์ PLO อยู่ — รอให้รอบเดิมเสร็จก่อน"


def test_a_revalidation_that_produced_nothing_fails_the_job_and_stores_nothing(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    env.validate.side_effect = None
    env.validate.return_value = None

    job = _finish(client.post(f"{BASE}/PLO1/revalidate"), jobs_store, spawned)

    assert job.status == "failed"
    assert job.error_th == "ตรวจ SMART ไม่สำเร็จ กรุณาลองใหม่"
    env.bulk_insert.assert_not_awaited()


def test_a_failing_stage_fails_the_job_not_the_request(
    env: _Env, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    env.synth.side_effect = RuntimeError("endpoint down")

    job = _finish(client.post(f"{BASE}/run"), jobs_store, spawned)

    assert job.status == "failed"
    assert job.error_th == "endpoint down"


# --- one active writer per program -------------------------------------------


@pytest.mark.parametrize(("url", "kind", "params"), ROUTES, ids=ROUTE_IDS)
def test_a_busy_program_answers_409_with_a_thai_string(
    url: str,
    kind: str,
    params: dict[str, Any],
    env: _Env,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    _put_running(jobs_store)

    r = client.post(url)

    assert r.status_code == 409
    assert isinstance(r.json()["detail"], str)
    assert r.json()["detail"]
    assert list(jobs_store.rows) == ["already"]
    assert spawned.coros == []
    assert env.untouched()


@pytest.mark.parametrize(("url", "kind", "params"), ROUTES, ids=ROUTE_IDS)
def test_another_programs_running_job_does_not_block(
    url: str,
    kind: str,
    params: dict[str, Any],
    env: _Env,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    _put_running(jobs_store, program_id="some-other-program")

    r = client.post(url)

    assert r.status_code == 202, r.text
    spawned.drain()
