from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.models import JobInfo
from tests.support.jobs import InMemoryJobs

client = TestClient(app)


def _put(store: InMemoryJobs, job_id: str, program_id: str, status: str, minute: int) -> None:
    store.rows[job_id] = JobInfo(
        job_id=job_id,
        program_id=program_id,
        kind="plo_report",
        status=status,  # type: ignore[arg-type]
        created_at=datetime(2026, 10, 8, 3, minute),
    )


def test_list_jobs_newest_first_with_labels(jobs_store: InMemoryJobs) -> None:
    _put(jobs_store, "a", "p", "succeeded", 1)
    _put(jobs_store, "b", "p", "running", 2)
    _put(jobs_store, "c", "other", "running", 3)
    body = client.get("/programs/p/jobs").json()
    assert [j["job_id"] for j in body] == ["b", "a"]
    assert all(j["label_th"] for j in body)
    active = client.get("/programs/p/jobs?active=true").json()
    assert [j["job_id"] for j in active] == ["b"]


def test_get_one_job_and_404_across_programs(jobs_store: InMemoryJobs) -> None:
    _put(jobs_store, "a", "p", "succeeded", 1)
    assert client.get("/programs/p/jobs/a").json()["status"] == "succeeded"
    assert client.get("/programs/other/jobs/a").status_code == 404
    assert client.get("/programs/p/jobs/missing").status_code == 404
