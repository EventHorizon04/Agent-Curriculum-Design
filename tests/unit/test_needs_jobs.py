"""The three needs routes answer 202 and run their stage as a background job.

Preconditions (404 program, 422 no evidence / no skills) stay synchronous and
create no job row; the stage itself runs when the recorded job body is drained.
Every success test drains and asserts on the outcome: an undrained body is
closed silently at teardown, so a 202-only assertion would pass over a work
closure that does nothing.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    JobInfo,
    KSECCategory,
    Need,
    ProgramMetadata,
    StakeholderEvidence,
)
from tests.support.jobs import InMemoryJobs, SpawnRecorder

client = TestClient(app)

NOTE = "เน้นทักษะด้าน AI"

# (url, job kind, the list key the old response body carried)
ROUTES = [
    ("/programs/cs-test/needs/run", "needs_pipeline", "needs"),
    ("/programs/cs-test/needs/skills/run", "skill_extraction", "skills"),
    ("/programs/cs-test/needs/combine/run", "need_combination", "needs"),
]
ROUTE_IDS = ["needs_pipeline", "skill_extraction", "need_combination"]


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


def _skill() -> ExtractedSkill:
    return ExtractedSkill(
        skill_id="S1",
        program_id="cs-test",
        skill_name_th="วิเคราะห์ข้อมูลขนาดใหญ่",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        evidence_span_th="ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้",
        source_evidence_id="E1",
        source_stakeholder_type="employer",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.75,
    )


def _need() -> Need:
    return Need(
        need_id="N1",
        program_id="cs-test",
        statement_th="สามารถวิเคราะห์ข้อมูลขนาดใหญ่เพื่อหา insight ทางธุรกิจ",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=1,
        demand_score=0.7,
    )


def _evidence() -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id="E1",
        program_id="cs-test",
        stakeholder_type="employer",
        source_name="JD",
        raw_text_th="ต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้",
        classification="general",
    )


class _Stages:
    """The two stage `run` functions, patched where the routes import them."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.seen_by_skills: dict[str, object] = {}
        self.seen_by_needs: dict[str, object] = {}
        self.seen_by_grouping: dict[str, object] = {}

        async def fake_skills(state: dict[str, object]) -> dict[str, object]:
            self.seen_by_skills.update(state)
            return {
                **state,
                "extracted_skills": [_skill().model_dump(mode="json")],
                "dropped_ungrounded_count": 2,
            }

        async def fake_needs(state: dict[str, object]) -> dict[str, object]:
            self.seen_by_needs.update(state)
            return {
                **state,
                "needs": [_need().model_dump(mode="json")],
                "dropped_ungrounded_count": 3,
            }

        async def fake_grouping(state: dict[str, object]) -> dict[str, object]:
            self.seen_by_grouping.update(state)
            return {**state, "skill_groups": []}

        self.skills = AsyncMock(side_effect=fake_skills)
        self.grouping = AsyncMock(side_effect=fake_grouping)
        self.needs = AsyncMock(side_effect=fake_needs)
        monkeypatch.setattr("curriculum_agent.stages.skill_extraction.run", self.skills)
        monkeypatch.setattr("curriculum_agent.stages.skill_grouping.run", self.grouping)
        monkeypatch.setattr("curriculum_agent.stages.need_combination.run", self.needs)

    def for_url(self, url: str) -> AsyncMock:
        return self.needs if url.endswith("combine/run") else self.skills


@pytest.fixture
def stages(monkeypatch: pytest.MonkeyPatch) -> _Stages:
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[_evidence()])
    )
    monkeypatch.setattr(
        needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[_skill()])
    )
    return _Stages(monkeypatch)


def _put_running(store: InMemoryJobs, program_id: str = "cs-test") -> None:
    store.rows["already"] = JobInfo(
        job_id="already",
        program_id=program_id,
        kind="plo_synthesis",
        status="running",
        created_at=datetime(2026, 10, 8, 3, 0),
    )


@pytest.mark.parametrize(("url", "kind", "key"), ROUTES, ids=ROUTE_IDS)
def test_run_answers_202_and_runs_the_stage_in_the_background(
    url: str,
    kind: str,
    key: str,
    stages: _Stages,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    r = client.post(url)

    assert r.status_code == 202, r.text
    body = r.json()
    assert body["kind"] == kind
    assert body["status"] == "running"
    assert body["label_th"]
    # Answered before the stage ran: that is the whole point of the job.
    assert not stages.skills.await_count
    assert not stages.needs.await_count

    spawned.drain()

    stages.for_url(url).assert_awaited_once()
    job = jobs_store.rows[body["job_id"]]
    assert job.status == "succeeded"
    assert key in job.result
    assert "dropped_ungrounded_count" in job.result


def test_needs_run_result_is_the_old_need_run_result_body(
    stages: _Stages, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    r = client.post("/programs/cs-test/needs/run")
    spawned.drain()

    # Both stages ran, in order, and the result carries the second one's Needs
    # and the drop count of the state it left behind.
    stages.skills.assert_awaited_once()
    stages.grouping.assert_awaited_once()
    stages.needs.assert_awaited_once()
    assert "extracted_skills" in stages.seen_by_needs
    job = jobs_store.rows[r.json()["job_id"]]
    assert [n["need_id"] for n in job.result["needs"]] == ["N1"]
    assert job.result["dropped_ungrounded_count"] == 3


def test_skills_run_result_is_the_old_skill_run_result_body(
    stages: _Stages, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    r = client.post("/programs/cs-test/needs/skills/run")
    spawned.drain()

    # The stored Needs are left alone: this route stops before need_combination,
    # but the groups are rebuilt so they never lag behind the skills.
    stages.grouping.assert_awaited_once()
    stages.needs.assert_not_awaited()
    job = jobs_store.rows[r.json()["job_id"]]
    assert [s["skill_id"] for s in job.result["skills"]] == ["S1"]
    assert job.result["dropped_ungrounded_count"] == 2


def test_combine_run_result_is_the_old_need_run_result_body(
    stages: _Stages, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    r = client.post("/programs/cs-test/needs/combine/run")
    spawned.drain()

    stages.skills.assert_not_awaited()
    stages.grouping.assert_not_awaited()
    # Agent 2 loads the stored groups itself.
    assert "skill_groups" not in stages.seen_by_needs
    assert "extracted_skills" not in stages.seen_by_needs
    assert "classified_evidence" not in stages.seen_by_needs
    job = jobs_store.rows[r.json()["job_id"]]
    assert [n["need_id"] for n in job.result["needs"]] == ["N1"]
    assert job.result["dropped_ungrounded_count"] == 3


@pytest.mark.parametrize(("url", "kind", "key"), ROUTES, ids=ROUTE_IDS)
def test_a_failing_stage_fails_the_job_not_the_request(
    url: str,
    kind: str,
    key: str,
    stages: _Stages,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    stages.for_url(url).side_effect = RuntimeError("endpoint down")

    r = client.post(url)
    assert r.status_code == 202
    spawned.drain()

    job = jobs_store.rows[r.json()["job_id"]]
    assert job.status == "failed"
    assert job.error_th == "endpoint down"


# --- preconditions stay synchronous and create no job row -------------------


@pytest.mark.parametrize("url", [ROUTES[0][0], ROUTES[1][0]], ids=ROUTE_IDS[:2])
def test_no_evidence_is_a_synchronous_422_and_no_job(
    url: str,
    monkeypatch: pytest.MonkeyPatch,
    stages: _Stages,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[])
    )

    r = client.post(url)

    assert r.status_code == 422
    assert "evidence" in r.json()["detail"]
    assert jobs_store.rows == {}
    assert spawned.coros == []


def test_no_skills_is_a_synchronous_422_and_no_job(
    monkeypatch: pytest.MonkeyPatch,
    stages: _Stages,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    monkeypatch.setattr(needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[]))

    r = client.post("/programs/cs-test/needs/combine/run")

    assert r.status_code == 422
    assert "ทักษะ" in r.json()["detail"]
    assert jobs_store.rows == {}
    assert spawned.coros == []


@pytest.mark.parametrize(("url", "kind", "key"), ROUTES, ids=ROUTE_IDS)
def test_unknown_program_is_a_synchronous_404_and_no_job(
    url: str,
    kind: str,
    key: str,
    monkeypatch: pytest.MonkeyPatch,
    stages: _Stages,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=None))

    r = client.post(url)

    assert r.status_code == 404
    assert jobs_store.rows == {}
    assert spawned.coros == []


# --- one active writer per program ------------------------------------------


@pytest.mark.parametrize(("url", "kind", "key"), ROUTES, ids=ROUTE_IDS)
def test_a_busy_program_answers_409_with_a_thai_string(
    url: str,
    kind: str,
    key: str,
    stages: _Stages,
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


@pytest.mark.parametrize(("url", "kind", "key"), ROUTES, ids=ROUTE_IDS)
def test_another_programs_running_job_does_not_block(
    url: str,
    kind: str,
    key: str,
    stages: _Stages,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    _put_running(jobs_store, program_id="some-other-program")

    r = client.post(url)

    assert r.status_code == 202
    spawned.drain()


# --- the designer's note -----------------------------------------------------


@pytest.mark.parametrize(("url", "kind", "key"), ROUTES, ids=ROUTE_IDS)
def test_the_note_is_recorded_in_params_and_reaches_the_stage_state(
    url: str,
    kind: str,
    key: str,
    stages: _Stages,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    r = client.post(url, json={"note_th": NOTE})

    assert r.status_code == 202
    assert r.json()["params"] == {"note_th": NOTE}
    spawned.drain()

    first_stage = stages.needs if url.endswith("combine/run") else stages.skills
    assert first_stage.await_args.args[0]["designer_note"] == NOTE


@pytest.mark.parametrize(("url", "kind", "key"), ROUTES, ids=ROUTE_IDS)
def test_no_body_records_a_null_note_and_sets_no_designer_note(
    url: str,
    kind: str,
    key: str,
    stages: _Stages,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
) -> None:
    r = client.post(url)

    assert r.status_code == 202
    assert r.json()["params"] == {"note_th": None}
    spawned.drain()

    first_stage = stages.needs if url.endswith("combine/run") else stages.skills
    assert "designer_note" not in first_stage.await_args.args[0]
