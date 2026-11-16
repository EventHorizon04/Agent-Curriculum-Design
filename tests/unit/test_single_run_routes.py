"""The run routes dispatch on `agent_mode`: a single program starts the single-agent
halves, a multi program behaves exactly as before."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.api.routes import sessions as sessions_route
from curriculum_agent.data.repositories import PLORepository
from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    ProgramMetadata,
    SessionInfo,
    SMARTCheck,
    StakeholderEvidence,
)
from curriculum_agent.stages.plo_review_facts import need_set_fingerprint
from curriculum_agent.stages.single_needs import SingleNeedsResult
from curriculum_agent.stages.single_plos import SinglePlosResult
from tests.support.jobs import InMemoryJobs, SpawnRecorder
from tests.unit.test_needs_jobs import _put_running

client = TestClient(app)
PID = "cs-test"
SINGLE_SESSION_TH = "หลักสูตรโหมด single ใช้การรันทีละขั้นจากหน้าเว็บ ไม่ใช้ session"


def _program(mode: str) -> ProgramMetadata:
    return ProgramMetadata(
        program_id=PID,
        field="Computer Science",
        degree_level="bachelor",
        duration_years=4,
        faculty="วิศวกรรมศาสตร์",
        university="มหาวิทยาลัยทดสอบ",
        agent_mode=mode,  # type: ignore[arg-type]
    )


def _need() -> Need:
    return Need(
        need_id="N1",
        program_id=PID,
        statement_th="สามารถวิเคราะห์ข้อมูลขนาดใหญ่เพื่อหา insight ทางธุรกิจ",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=1,
        demand_score=0.7,
    )


def _plo() -> PLO:
    return PLO(
        plo_id="PLO1",
        program_id=PID,
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


def _evidence() -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id="E1",
        program_id=PID,
        stakeholder_type="employer",
        source_name="JD",
        raw_text_th="ต้องการผู้ที่วิเคราะห์ข้อมูลได้",
        classification="general",
    )


class _Stages:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.single_needs = AsyncMock(
            return_value=SingleNeedsResult(
                needs=[_need()],
                stop_reason="finished",
                turns=1,
                dropped_evidence_count=0,
                unread_evidence_ids=[],
                uncited_evidence_ids=[],
                unnoted_evidence_ids=[],
            )
        )
        self.single_plos = AsyncMock(
            return_value=SinglePlosResult(
                plos=[_plo()],
                stop_reason="finished",
                turns=1,
                dropped_evidence_count=0,
                opened_evidence_ids=[],
                uncited_core_need_ids=[],
            )
        )
        self.skill_extraction = AsyncMock(side_effect=lambda s: {**s, "extracted_skills": []})
        self.skill_grouping = AsyncMock(side_effect=lambda s: {**s, "skill_groups": []})
        self.need_combination = AsyncMock(side_effect=lambda s: {**s, "needs": []})
        self.plo_synthesis = AsyncMock(side_effect=lambda s: {**s, "plos": []})
        report = {
            "plos": [_plo().model_dump(mode="json")],
            "counts": {"K": 0, "S": 1, "E": 0, "C": 0},
            "needs_by_id": {},
            "needs_not_synthesized": [],
        }
        self.plo_report = AsyncMock(side_effect=lambda s: {**s, "report": report})
        for target, mock in {
            "single_needs.run_single_needs": self.single_needs,
            "single_plos.run_single_plos": self.single_plos,
            "skill_extraction.run": self.skill_extraction,
            "skill_grouping.run": self.skill_grouping,
            "need_combination.run": self.need_combination,
            "plo_synthesis.run": self.plo_synthesis,
            "plo_report.run": self.plo_report,
        }.items():
            monkeypatch.setattr(f"curriculum_agent.stages.{target}", mock)


@pytest.fixture
def stages(monkeypatch: pytest.MonkeyPatch) -> _Stages:
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[_evidence()])
    )
    monkeypatch.setattr(needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        needs_route.SkillGroupRepository, "list_by_program", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_active_by_program", AsyncMock(return_value=[_need()])
    )
    monkeypatch.setattr(PLORepository, "list_by_program", AsyncMock(return_value=[_plo()]))
    return _Stages(monkeypatch)


@pytest.fixture
def set_mode(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    def _set(mode: str) -> None:
        get = AsyncMock(return_value=_program(mode))
        monkeypatch.setattr(needs_route.ProgramRepository, "get", get)
        monkeypatch.setattr(plos_route.ProgramRepository, "get", get)
        monkeypatch.setattr(sessions_route.ProgramRepository, "get", get)

    return _set


@pytest.fixture
def single_program(set_mode: Callable[[str], None]) -> None:
    set_mode("single")


@pytest.fixture
def multi_program(set_mode: Callable[[str], None]) -> None:
    set_mode("multi")


@pytest.mark.parametrize("url", ["needs/run", "needs/combine/run"])
def test_needs_run_on_a_single_program_starts_single_needs_and_chains_nothing(
    url: str,
    single_program: None,
    stages: _Stages,
    spawned: SpawnRecorder,
    jobs_store: InMemoryJobs,
) -> None:
    r = client.post(f"/programs/{PID}/{url}")
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "single_needs"
    spawned.drain()
    stages.single_needs.assert_awaited_once_with(PID, None)
    stages.skill_extraction.assert_not_awaited()
    stages.need_combination.assert_not_awaited()
    assert [j.kind for j in jobs_store.rows.values()] == ["single_needs"]
    assert next(iter(jobs_store.rows.values())).status == "succeeded"


def test_needs_run_on_a_multi_program_is_unchanged(
    multi_program: None, stages: _Stages, spawned: SpawnRecorder
) -> None:
    assert client.post(f"/programs/{PID}/needs/run").json()["kind"] == "skill_extraction"
    spawned.drain()
    stages.single_needs.assert_not_awaited()
    stages.need_combination.assert_awaited_once()


def test_single_needs_run_without_evidence_is_422_and_makes_no_job(
    single_program: None,
    stages: _Stages,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
) -> None:
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[])
    )
    assert client.post(f"/programs/{PID}/needs/run").status_code == 422
    assert client.post(f"/programs/{PID}/needs/combine/run").status_code == 422
    assert jobs_store.rows == {}


def test_single_needs_run_while_busy_is_409(
    single_program: None, stages: _Stages, jobs_store: InMemoryJobs
) -> None:
    _put_running(jobs_store, PID)
    assert client.post(f"/programs/{PID}/needs/run").status_code == 409


def test_skill_run_on_a_single_program_is_refused(
    single_program: None, stages: _Stages, jobs_store: InMemoryJobs
) -> None:
    r = client.post(f"/programs/{PID}/needs/skills/run")
    assert r.status_code == 409
    assert "single" in r.json()["detail"]
    assert jobs_store.rows == {}


def test_plos_run_on_a_single_program_starts_single_plos_without_a_review(
    single_program: None,
    stages: _Stages,
    spawned: SpawnRecorder,
    review_chain_calls: list[tuple[str, bool]],
) -> None:
    r = client.post(f"/programs/{PID}/plos/run", json={"note_th": "โน้ต", "run_validation": False})
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "single_plos"
    spawned.drain()
    stages.single_plos.assert_awaited_once_with(PID, note_th="โน้ต")
    stages.plo_synthesis.assert_not_awaited()
    assert review_chain_calls == []


def test_plos_run_on_a_single_program_records_the_approved_need_set(
    single_program: None, stages: _Stages, spawned: SpawnRecorder, jobs_store: InMemoryJobs
) -> None:
    r = client.post(f"/programs/{PID}/plos/run", json={"note_th": "โน้ต"})
    assert r.status_code == 202, r.text
    params = next(iter(jobs_store.rows.values())).params
    assert params == {
        "note_th": "โน้ต",
        "approved_need_ids": ["N1"],
        "need_fingerprint": need_set_fingerprint([_need()]),
    }


def test_plos_run_on_a_multi_program_still_chains_the_review(
    multi_program: None,
    stages: _Stages,
    spawned: SpawnRecorder,
    review_chain_calls: list[tuple[str, bool]],
) -> None:
    assert client.post(f"/programs/{PID}/plos/run", json={}).json()["kind"] == "plo_synthesis"
    spawned.drain()
    stages.single_plos.assert_not_awaited()
    assert review_chain_calls == [(PID, False)]


def test_single_plos_run_without_active_needs_is_422(
    single_program: None, stages: _Stages, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_active_by_program", AsyncMock(return_value=[])
    )
    assert client.post(f"/programs/{PID}/plos/run", json={}).status_code == 422


def test_rerun_of_the_needs_half_leaves_plos_alone(
    single_program: None,
    stages: _Stages,
    spawned: SpawnRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete = AsyncMock()
    monkeypatch.setattr(PLORepository, "delete_by_program", delete)
    client.post(f"/programs/{PID}/needs/run")
    spawned.drain()
    delete.assert_not_awaited()


def test_report_runs_for_a_single_program_with_no_review(
    single_program: None,
    stages: _Stages,
    spawned: SpawnRecorder,
    jobs_store: InMemoryJobs,
    review_chain_calls: list[tuple[str, bool]],
) -> None:
    r = client.post(f"/programs/{PID}/plos/report/run")
    assert r.status_code == 202, r.text
    assert r.json()["kind"] == "plo_report"
    spawned.drain()
    stages.plo_report.assert_awaited_once()
    assert jobs_store.rows[r.json()["job_id"]].status == "succeeded"
    assert review_chain_calls == []


def test_session_for_a_single_program_is_refused(single_program: None, stages: _Stages) -> None:
    r = client.post(f"/programs/{PID}/sessions/")
    assert r.status_code == 409
    assert r.json()["detail"] == SINGLE_SESSION_TH


def test_session_approve_for_a_single_program_is_refused(
    single_program: None, stages: _Stages, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 11, 14)
    session = SessionInfo(
        session_id="s1",
        program_id=PID,
        thread_id=f"{PID}:s1",
        status="suspended",
        created_at=now,
        updated_at=now,
    )
    monkeypatch.setattr(sessions_route.SessionRepository, "get", AsyncMock(return_value=session))
    r = client.post(f"/programs/{PID}/sessions/s1/approve")
    assert r.status_code == 409
    assert r.json()["detail"] == SINGLE_SESSION_TH


def test_review_run_on_a_single_program_is_409_and_makes_no_job(
    single_program: None,
    stages: _Stages,
    jobs_store: InMemoryJobs,
    review_chain_calls: list[tuple[str, bool]],
) -> None:
    r = client.post(f"/programs/{PID}/plos/review/run")
    assert r.status_code == 409
    assert r.json()["detail"] == "หลักสูตรโหมด single ไม่มีขั้นตรวจคุณภาพและการส่งกลับ"
    assert jobs_store.rows == {} and review_chain_calls == []


@pytest.mark.review_chain
async def test_the_review_chain_refuses_to_start_for_a_single_program(
    single_program: None, stages: _Stages, jobs_store: InMemoryJobs
) -> None:
    assert await plos_route._start_review_job(PID, or_409=False) is None
    assert jobs_store.rows == {}


@pytest.mark.parametrize("url", ["needs/run", "needs/combine/run"])
def test_needs_run_on_a_single_program_passes_the_note(
    url: str,
    single_program: None,
    stages: _Stages,
    spawned: SpawnRecorder,
    jobs_store: InMemoryJobs,
) -> None:
    r = client.post(f"/programs/{PID}/{url}", json={"note_th": "เน้นภาคปฏิบัติ"})
    assert r.status_code == 202, r.text
    spawned.drain()
    stages.single_needs.assert_awaited_once_with(PID, "เน้นภาคปฏิบัติ")
    assert next(iter(jobs_store.rows.values())).params == {"note_th": "เน้นภาคปฏิบัติ"}
