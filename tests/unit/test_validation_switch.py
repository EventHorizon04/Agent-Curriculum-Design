"""A per-run switch for the SMART validation agent.

The designer compares synthesis with and without the agent. `.env`
(`VALIDATION_PROVIDER=`) could already turn it off, but only with a restart,
and PowerShell's `$env:X = ""` deletes the variable instead of emptying it. So
`POST /plos/run` takes `run_validation`, which reaches `run_smart_agent` as
`enabled`. Two invariants: the `.env` switch still wins (a request cannot turn
on an agent with no endpoint), and the pure-code gate runs either way.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.config import settings as live_settings
from curriculum_agent.models import BloomLevel, KSECCategory, Need, ProgramMetadata
from curriculum_agent.stages import plo_synthesis as ps
from curriculum_agent.stages import smart_agent as sa
from curriculum_agent.stages.smart_agent_tools import ToolBudget, ValidationContext
from tests.support.jobs import InMemoryJobs, SpawnRecorder
from tests.support.smart_agent import set_agent

client = TestClient(app)

_META = ProgramMetadata(
    program_id="cs-test",
    name_th="วิทยาการคอมพิวเตอร์",
    name_en="Computer Science",
    field="วิทยาการคอมพิวเตอร์",
    degree_level="bachelor",
    duration_years=4,
    faculty="คณะวิทยาศาสตร์",
    university="มหาวิทยาลัยทดสอบ",
)


def _need(need_id: str = "N1") -> Need:
    return Need(
        need_id=need_id,
        program_id="cs-test",
        statement_th=f"ต้องการบัณฑิตที่ทำงานด้าน {need_id} ได้ตามมาตรฐานอุตสาหกรรม",
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.CREATE,
        member_skill_ids=[f"S-{need_id}"],
        source_evidence_ids=[f"E-{need_id}"],
        freq=1,
        demand_score=0.8,
    )


def _draft(statement_th: str = "ออกแบบระบบสารสนเทศตามมาตรฐานอุตสาหกรรมได้") -> ps._PLODraft:
    return ps._PLODraft(
        statement_th=statement_th,
        bloom_level=BloomLevel.CREATE,
        action_verb_th="ออกแบบ",
        source_need_ids=["N1"],
        rationale_th="ทักษะที่ตลาดต้องการ",
    )


class _FakeIndex:
    """An EvidenceIndex stand-in that never has to be read in these tests."""

    async def get(self, evidence_id: str) -> Any:
        return None


def _ctx_for(draft: ps._PLODraft | None = None) -> ValidationContext:
    """Built the same way `tests/unit/test_smart_agent.py`'s `_ctx` helper
    builds it — copied rather than imported across test modules."""
    draft = draft or _draft()
    needs = [_need()]
    return ValidationContext(
        program_id="cs-test",
        plo_id="PLO1",
        draft=draft,
        authoritative_need_ids=tuple(n.need_id for n in needs),
        known_need_ids=frozenset(n.need_id for n in needs),
        needs_by_id={n.need_id: n for n in needs},
        cited_evidence_ids=frozenset(e for n in needs for e in n.source_evidence_ids),
        siblings=[],
        evidence_index=_FakeIndex(),  # type: ignore[arg-type]
        budget=ToolBudget(),
    )


async def _must_not_be_called(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("the validation agent ran on a run that switched it off")


# --------------------------- run_smart_agent ---------------------------


async def test_enabled_false_skips_the_agent_without_calling_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_settings, "validation_provider", "openrouter")
    monkeypatch.setattr(sa, "complete_validation", _must_not_be_called)
    ctx = _ctx_for(_draft())

    result = await sa.run_smart_agent(_draft(), ctx, _META, enabled=False)

    assert result.reason is sa.ValidationReason.SKIPPED
    assert result.ran is False
    assert result.soft_findings == []
    assert "ปิดการตรวจในรอบนี้" in result.diagnosis_th


async def test_the_env_switch_wins_over_a_request_to_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_settings, "validation_provider", "")
    monkeypatch.setattr(sa, "complete_validation", _must_not_be_called)

    result = await sa.run_smart_agent(_draft(), _ctx_for(_draft()), _META, enabled=True)

    assert result.reason is sa.ValidationReason.DISABLED


# --------------------------- validate_and_build ---------------------------


async def test_validate_and_build_passes_the_switch_to_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = set_agent(monkeypatch)
    await ps.validate_and_build(
        _draft(),
        metadata=_META,
        needs=[_need()],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
        run_validation=False,
    )
    assert stub.enabled_flags == [False]


async def test_the_code_gate_still_escalates_when_the_agent_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Immutable rule 5: skipping the agent never skips `hard_failures`."""
    monkeypatch.setattr(live_settings, "validation_provider", "openrouter")
    monkeypatch.setattr(sa, "complete_validation", _must_not_be_called)
    bad = _draft("ออกแบบระบบสารสนเทศที่ผู้ใช้เข้าใจได้ตามมาตรฐานอุตสาหกรรม")

    plo = await ps.validate_and_build(
        bad,
        metadata=_META,
        needs=[_need()],
        program_id="cs-test",
        plo_id="PLO1",
        known_need_ids={"N1"},
        run_validation=False,
    )

    assert plo is not None
    assert plo.smart_escalated is True
    assert plo.smart_validated_by == "code_only"


# --------------------------- stage ---------------------------


async def test_the_stage_reads_the_switch_from_state(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = set_agent(monkeypatch)
    monkeypatch.setattr(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(ps, "draft_from_needs", AsyncMock(return_value=_draft()))

    await ps.run(
        {
            "program_id": "cs-test",
            "metadata": _META.model_dump(mode="json"),
            "needs": [_need().model_dump(mode="json")],
            "run_validation": False,
        }
    )

    assert stub.enabled_flags and all(flag is False for flag in stub.enabled_flags)


async def test_the_stage_validates_when_the_key_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = set_agent(monkeypatch)
    monkeypatch.setattr(ps.PLORepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(ps.PLORepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(ps, "draft_from_needs", AsyncMock(return_value=_draft()))

    await ps.run(
        {
            "program_id": "cs-test",
            "metadata": _META.model_dump(mode="json"),
            "needs": [_need().model_dump(mode="json")],
        }
    )

    assert stub.enabled_flags and all(flag is True for flag in stub.enabled_flags)


# --------------------------- routes ---------------------------


def _route_env(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_META))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    run = AsyncMock(return_value={"plos": []})
    monkeypatch.setattr(ps, "run", run)
    return run


def test_run_route_puts_the_switch_in_state_only_when_off(
    monkeypatch: pytest.MonkeyPatch, jobs_store: InMemoryJobs, spawned: SpawnRecorder
) -> None:
    run = _route_env(monkeypatch)

    resp = client.post("/programs/cs-test/plos/run", json={"run_validation": False})
    assert resp.status_code == 202
    assert resp.json()["params"]["run_validation"] is False
    spawned.drain()
    assert run.await_args.args[0]["run_validation"] is False

    # A finished job frees the program, so the next run is accepted.
    resp = client.post("/programs/cs-test/plos/run", json={})
    assert resp.status_code == 202
    assert resp.json()["params"]["run_validation"] is True
    spawned.drain()
    assert "run_validation" not in run.await_args.args[0]

    resp = client.post("/programs/cs-test/plos/run")
    assert resp.status_code == 202
    assert resp.json()["params"]["run_validation"] is True
    spawned.drain()
    assert "run_validation" not in run.await_args.args[0]
    assert run.await_count == 3
    assert all(job.status == "succeeded" for job in jobs_store.rows.values())


def test_validation_status_reports_on_and_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_META))

    monkeypatch.setattr(live_settings, "validation_provider", "openrouter")
    monkeypatch.setattr(live_settings, "validation_model", "z-ai/glm-5.3-flash")
    on = client.get("/programs/cs-test/plos/validation")
    assert on.status_code == 200
    assert on.json() == {"enabled": True, "model": "z-ai/glm-5.3-flash"}

    monkeypatch.setattr(live_settings, "validation_provider", "")
    off = client.get("/programs/cs-test/plos/validation")
    assert off.json() == {"enabled": False, "model": ""}


def test_validation_status_404s_for_an_unknown_program(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=None))
    assert client.get("/programs/nope/plos/validation").status_code == 404
