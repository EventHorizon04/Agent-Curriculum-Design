from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.models import (
    NOTE_MAX_CHARS,
    PLO,
    BloomLevel,
    ExtractedSkill,
    JobInfo,
    KSECCategory,
    Need,
    ProgramMetadata,
    SMARTCheck,
    StakeholderEvidence,
)
from curriculum_agent.stages import skill_extraction
from tests.support.jobs import InMemoryJobs, SpawnRecorder


@pytest.fixture(autouse=True)
def _grouping_passes_state_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the routes, not about clustering: the grouping stage
    the routes now call after extraction is a pass-through unless a test says
    otherwise."""

    async def passthrough(state):  # noqa: ANN001, ANN202
        return state

    monkeypatch.setattr("curriculum_agent.stages.skill_grouping.run", passthrough)


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


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(needs_route.router, prefix="/programs/{program_id}/needs")
    app.include_router(plos_route.router, prefix="/programs/{program_id}/plos")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _finish(response: Response, jobs_store: InMemoryJobs, spawned: SpawnRecorder) -> JobInfo:
    """The three needs routes answer 202 and run their stage as a job body. Run
    that body to completion — inside the caller's patches, which is why this is
    awaited there and not at teardown — and hand back the finished job."""
    assert response.status_code == 202, response.text
    await spawned.coros.pop(0)
    job = jobs_store.rows[response.json()["job_id"]]
    assert job.status == "succeeded", job.error_th
    return job


async def test_list_needs_returns_repository_rows(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.get("/programs/cs-test/needs/")
    assert response.status_code == 200
    body = response.json()
    assert [n["need_id"] for n in body] == ["N1"]
    assert body[0]["ksec_categories"] == ["S"]


async def test_list_skills_exposes_span_and_importance(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[_skill()])
    )
    response = await client.get("/programs/cs-test/needs/skills")
    assert response.status_code == 200
    row = response.json()[0]
    assert row["evidence_span_th"] == "ต้องวิเคราะห์ข้อมูลขนาดใหญ่ได้"
    assert row["importance_score"] == 0.75


async def test_trace_returns_404_for_unknown_need(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.get("/programs/cs-test/needs/does-not-exist/trace")
    assert response.status_code == 404


async def test_run_rejects_program_without_evidence(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[])
    )
    response = await client.post("/programs/cs-test/needs/run")
    assert response.status_code == 422
    assert "evidence" in response.json()["detail"]


async def test_run_returns_404_for_missing_program(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Mirrors plos.py's run_plo_synthesis: a missing program is a 404 looked up
    before anything else, not a 422 blaming the evidence."""
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[_evidence()])
    )
    response = await client.post("/programs/unknown-program/needs/run")
    assert response.status_code == 404


async def test_from_needs_rejects_fewer_than_two_needs(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    # One Need already becomes a PLO through the normal 1:1 path.
    #
    # N1 is mocked as a real, known Need so that if the min_length=2 guard were
    # dropped, request validation would let this single id through the handler,
    # the need-lookup would find it, and the response would NOT be 422 with a
    # "too_short" body error — proving this 422 comes from the count guard, not
    # from an unrelated failure (e.g. an unknown-need or missing-program error).
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.post("/programs/cs-test/plos/from-needs", json={"need_ids": ["N1"]})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["type"] == "too_short"


async def test_from_needs_rejects_unknown_need_ids(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    response = await client.post(
        "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "ghost"]}
    )
    assert response.status_code == 422
    assert "ghost" in response.json()["detail"]


async def test_from_needs_returns_404_for_missing_program(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    # When program does not exist, endpoint returns 404, not 422 blaming the Needs.
    # This test pins the correct check order: program lookup first.
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=None))
    response = await client.post(
        "/programs/unknown-program/plos/from-needs", json={"need_ids": ["N1", "N2"]}
    )
    assert response.status_code == 404
    assert "หลักสูตร" in response.json()["detail"]


# --- designer note on the three stage endpoints ---

NOTE = "เน้นทักษะด้าน AI และการวิเคราะห์ข้อมูลขนาดใหญ่"


def _evidence() -> StakeholderEvidence:
    return StakeholderEvidence(
        evidence_id="E1",
        program_id="cs-test",
        stakeholder_type="employer",
        source_name="JD",
        raw_text_th="ต้องการผู้ที่วิเคราะห์ข้อมูลขนาดใหญ่ได้",
        classification="general",
    )


def _stub_need_stages(seen: dict[str, object]):
    """Patch the POST /needs/run chain so need_combination.run is a recording
    stand-in, but skill_extraction.run genuinely executes.

    The note-forwarding contract this route relies on is that skill_extraction.run
    mutates its input state dict in place and returns that same object — nothing
    in the route re-merges keys between stages. A pass-through stub for
    skill_extraction cannot prove that; it would still pass if a future rewrite
    made the stage return a fresh dict instead. So here only the stage's own
    dependencies are mocked (the LLM cache, the extraction call, the skill
    repository — the same seam test_skill_extraction_cache.py and
    test_skill_dedupe.py mock), and the real `skill_extraction.run` runs against
    the one evidence item `_evidence()` provides.
    """

    async def fake_needs(state):
        seen.update(state)
        return {**state, "needs": [], "dropped_ungrounded_count": 0}

    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(return_value=None)  # always miss, force the "extraction" below
    fake_cache.set = AsyncMock()

    async def fake_complete_extraction(response_model, messages, **kwargs):
        # One grounded skill, quoting the evidence text verbatim so
        # skill_extraction's groundedness check (is_grounded) accepts it.
        return skill_extraction._ExtractedSkillsResponse(
            skills=[
                skill_extraction._SkillItem(
                    skill_name_th="วิเคราะห์ข้อมูลขนาดใหญ่",
                    ksec_category="S",
                    bloom_level="analyze",
                    evidence_span_th=_evidence().raw_text_th,
                    confidence=0.9,
                )
            ]
        )

    return (
        patch.object(skill_extraction, "LLMCacheRepository", return_value=fake_cache),
        patch.object(skill_extraction, "complete_extraction", side_effect=fake_complete_extraction),
        patch.object(skill_extraction, "SkillRepository", return_value=AsyncMock()),
        patch("curriculum_agent.stages.need_combination.run", new=fake_needs),
    )


async def test_needs_run_carries_the_note_into_the_stage_state(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
):
    seen: dict[str, object] = {}
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        needs_route.EvidenceRepository,
        "list_by_program",
        AsyncMock(return_value=[_evidence()]),
    )
    cache_patch, complete_patch, repo_patch, needs_patch = _stub_need_stages(seen)
    with cache_patch, complete_patch, repo_patch, needs_patch:
        response = await client.post("/programs/cs-test/needs/run", json={"note_th": NOTE})
        await _finish(response, jobs_store, spawned)

    assert seen["designer_note"] == NOTE


async def test_needs_run_still_works_with_no_body_at_all(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
):
    """The live frontend posts no body. That must keep working."""
    seen: dict[str, object] = {}
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        needs_route.EvidenceRepository,
        "list_by_program",
        AsyncMock(return_value=[_evidence()]),
    )
    cache_patch, complete_patch, repo_patch, needs_patch = _stub_need_stages(seen)
    with cache_patch, complete_patch, repo_patch, needs_patch:
        response = await client.post("/programs/cs-test/needs/run")
        await _finish(response, jobs_store, spawned)

    assert "designer_note" not in seen


async def test_needs_run_rejects_an_over_length_note(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        needs_route.EvidenceRepository,
        "list_by_program",
        AsyncMock(return_value=[_evidence()]),
    )
    response = await client.post(
        "/programs/cs-test/needs/run", json={"note_th": "ก" * (NOTE_MAX_CHARS + 1)}
    )
    assert response.status_code == 422


async def test_needs_run_passes_program_field_into_extraction_prompt(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
):
    """Pins the Important-1 fix: run_need_pipeline must load the program and put
    its metadata into the pipeline state, or skill_extraction.run falls back to
    `metadata = state.get("metadata") or {}` and field_th resolves to "" for
    every program on this route — silently starving the is_field_relevant
    judgment of the one fact it needs.

    Asserting only that the state dict carries a "metadata" key would not catch
    that regression (a state with metadata={} still has the key); this asserts
    on the actual prompt messages built for the model, which is where the
    finding says the value must land.
    """
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        needs_route.EvidenceRepository,
        "list_by_program",
        AsyncMock(return_value=[_evidence()]),
    )

    captured: dict[str, object] = {}

    async def fake_complete_extraction(response_model, messages, **kwargs):
        captured["messages"] = messages
        return skill_extraction._ExtractedSkillsResponse(
            skills=[
                skill_extraction._SkillItem(
                    skill_name_th="วิเคราะห์ข้อมูลขนาดใหญ่",
                    ksec_category="S",
                    bloom_level="analyze",
                    evidence_span_th=_evidence().raw_text_th,
                    confidence=0.9,
                )
            ]
        )

    fake_cache = AsyncMock()
    fake_cache.get = AsyncMock(return_value=None)
    fake_cache.set = AsyncMock()

    async def fake_needs(state):
        return {**state, "needs": [], "dropped_ungrounded_count": 0}

    with (
        patch.object(skill_extraction, "LLMCacheRepository", return_value=fake_cache),
        patch.object(skill_extraction, "complete_extraction", side_effect=fake_complete_extraction),
        patch.object(skill_extraction, "SkillRepository", return_value=AsyncMock()),
        patch("curriculum_agent.stages.need_combination.run", new=fake_needs),
    ):
        response = await client.post("/programs/cs-test/needs/run")
        await _finish(response, jobs_store, spawned)

    user_message = captured["messages"][1]["content"]
    assert _program().field in user_message


async def test_plos_run_carries_the_note_into_the_stage_state(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
):
    seen: dict[str, object] = {}

    async def fake_run(state):
        seen.update(state)
        return {**state, "plos": []}

    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_active_by_program", AsyncMock(return_value=[_need()])
    )
    with patch("curriculum_agent.stages.plo_synthesis.run", new=fake_run):
        response = await client.post("/programs/cs-test/plos/run", json={"note_th": NOTE})
        await _finish(response, jobs_store, spawned)

    assert seen["designer_note"] == NOTE


async def test_plos_run_still_works_with_no_body_at_all(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
):
    seen: dict[str, object] = {}

    async def fake_run(state):
        seen.update(state)
        return {**state, "plos": []}

    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_active_by_program", AsyncMock(return_value=[_need()])
    )
    with patch("curriculum_agent.stages.plo_synthesis.run", new=fake_run):
        response = await client.post("/programs/cs-test/plos/run")
        await _finish(response, jobs_store, spawned)

    assert "designer_note" not in seen


async def test_from_needs_passes_the_note_to_synthesis(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, object] = {}
    second = _need().model_copy(update={"need_id": "N2"})

    async def fake_synth(
        metadata, needs, program_id, known, plo_id, *, note_th=None, siblings=(), **kw
    ):
        captured["note_th"] = note_th
        captured["sibling_ids"] = [s.plo_id for s in siblings]
        return None  # the 502 path — this test only cares what synthesis was told

    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository,
        "list_by_program",
        AsyncMock(return_value=[_need(), second]),
    )
    monkeypatch.setattr(plos_route.PLORepository, "list_by_program", AsyncMock(return_value=[]))
    with patch("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", new=fake_synth):
        response = await client.post(
            "/programs/cs-test/plos/from-needs",
            json={"need_ids": ["N1", "N2"], "note_th": NOTE},
        )

    assert response.status_code == 502
    assert captured["note_th"] == NOTE


# --- split re-run: skills-only and combine-only entry points ---------------


async def test_skills_run_does_not_invoke_need_combination(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
):
    """The whole point of the split: re-extracting skills must leave the stored
    Needs alone. If this route ever chained into need_combination again, a
    designer who wanted only fresh skills would silently lose their reviewed
    Needs."""
    called = False

    async def fake_needs(state):
        nonlocal called
        called = True
        return state

    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[_evidence()])
    )
    cache_patch, complete_patch, repo_patch, _ = _stub_need_stages({})
    with (
        cache_patch,
        complete_patch,
        repo_patch,
        patch("curriculum_agent.stages.need_combination.run", new=fake_needs),
    ):
        response = await client.post("/programs/cs-test/needs/skills/run")
        job = await _finish(response, jobs_store, spawned)

    assert called is False
    assert job.result["skills"][0]["skill_name_th"] == "วิเคราะห์ข้อมูลขนาดใหญ่"


async def test_skills_run_carries_the_note_into_the_stage_state(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
):
    seen: dict[str, object] = {}
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[_evidence()])
    )

    real_run = skill_extraction.run

    async def recording_run(state):
        seen.update(state)
        return await real_run(state)

    cache_patch, complete_patch, repo_patch, _ = _stub_need_stages({})
    with (
        cache_patch,
        complete_patch,
        repo_patch,
        patch("curriculum_agent.stages.skill_extraction.run", new=recording_run),
    ):
        response = await client.post("/programs/cs-test/needs/skills/run", json={"note_th": NOTE})
        await _finish(response, jobs_store, spawned)

    assert seen["designer_note"] == NOTE


async def test_skills_run_returns_404_for_missing_program(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[_evidence()])
    )
    response = await client.post("/programs/unknown-program/needs/skills/run")
    assert response.status_code == 404


async def test_combine_run_feeds_stored_skills_into_the_stage(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
):
    """Combine-only reads the skill rows back out of the repository — it must not
    re-extract, and the stage must receive them under the key it reads.

    EvidenceRepository is deliberately left unstubbed: the route must not touch it
    at all, so a call would hit a real database and fail this test rather than
    passing on a stub nobody noticed had become unnecessary."""
    seen: dict[str, object] = {}

    async def fake_needs(state):
        seen.update(state)
        return {**state, "needs": [_need().model_dump(mode="json")]}

    extracted = False

    async def fake_skills(state):
        nonlocal extracted
        extracted = True
        return state

    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[_skill()])
    )
    with (
        patch("curriculum_agent.stages.need_combination.run", new=fake_needs),
        patch("curriculum_agent.stages.skill_extraction.run", new=fake_skills),
    ):
        response = await client.post("/programs/cs-test/needs/combine/run")
        job = await _finish(response, jobs_store, spawned)

    assert extracted is False
    # Agent 2 loads the stored groups itself, so the route hands it neither.
    assert "skill_groups" not in seen
    assert "extracted_skills" not in seen
    assert "classified_evidence" not in seen
    assert job.result["needs"][0]["need_id"] == "N1"


async def test_combine_run_rejects_a_program_with_no_skills(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[]))
    response = await client.post("/programs/cs-test/needs/combine/run")
    assert response.status_code == 422
    assert "ทักษะ" in response.json()["detail"]


async def test_combine_run_returns_404_for_missing_program(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(
        needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[_skill()])
    )
    response = await client.post("/programs/unknown-program/needs/combine/run")
    assert response.status_code == 404


async def test_combine_run_does_not_require_any_evidence(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    jobs_store: InMemoryJobs,
    spawned: SpawnRecorder,
):
    """Skills are the only precondition.

    The shared state builder used to 422 on an empty evidence table, which was a
    precondition need_combination no longer has: it groups and writes from the
    skills alone. A program whose evidence rows were cleared after extraction must
    still be able to redraw its Needs.
    """

    async def fake_needs(state):
        return {**state, "needs": [_need().model_dump(mode="json")]}

    monkeypatch.setattr(needs_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        needs_route.EvidenceRepository, "list_by_program", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        needs_route.SkillRepository, "list_by_program", AsyncMock(return_value=[_skill()])
    )
    with patch("curriculum_agent.stages.need_combination.run", new=fake_needs):
        response = await client.post("/programs/cs-test/needs/combine/run")
        job = await _finish(response, jobs_store, spawned)

    assert job.result["needs"][0]["need_id"] == "N1"


# --- POST /plos/from-needs: a merge replaces what it covers ------------------
#
# The endpoint used to append. A Need therefore ended up behind both its own
# outcome and the merged one, and two PLOs claiming the same evidence read as
# two independent market demands in the มคอ.2 matrix when they are one. Merging
# now supersedes every outcome citing a selected Need, which is also what a
# designer means by the word — so the count moves in both directions and both
# ends of the 6-10 policy have to be checked.


def _core_plo(index: int, *, optional: bool = False, need_ids: list[str] | None = None) -> PLO:
    """One outcome, citing its own Need by default.

    Each PLO gets a distinct Need because that is the invariant the route now
    keeps. The fixture used to give every outcome `["N1"]`, which no program can
    actually be in and which makes any merge look like it supersedes everything.
    """
    prefix = "PLO-O" if optional else "PLO"
    return PLO(
        plo_id=f"{prefix}{index}",
        program_id="cs-test",
        statement_th="บัณฑิตสามารถวิเคราะห์ข้อมูลขนาดใหญ่เพื่อสนับสนุนการตัดสินใจทางธุรกิจได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        source_need_ids=need_ids or [f"N{index}"],
        source_evidence_ids=["E1"],
        rationale_th="ตอบความต้องการของตลาดแรงงานด้านการวิเคราะห์ข้อมูล",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        is_optional=optional,
    )


def _named_need(need_id: str, *, optional: bool = False) -> Need:
    return _need().model_copy(update={"need_id": need_id, "is_optional": optional})


def _patch_merge(
    monkeypatch: pytest.MonkeyPatch,
    *,
    needs: list[Need],
    plos: list[PLO],
) -> AsyncMock:
    """Wire the three repositories the merge route reads. Returns the replace mock."""
    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=needs))
    monkeypatch.setattr(plos_route.PLORepository, "list_by_program", AsyncMock(return_value=plos))
    replace = AsyncMock(return_value=0)
    monkeypatch.setattr(plos_route.PLORepository, "replace", replace)
    return replace


async def test_a_merge_supersedes_every_plo_citing_a_selected_need(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """The point of the change: PLO1 and PLO2 are replaced, not left beside the
    merged outcome, so N1 and N2 stay behind exactly one PLO each."""
    # Seven outcomes, so folding two into one lands on the floor rather than
    # through it — the floor guard is exercised by its own test.
    replace = _patch_merge(
        monkeypatch,
        needs=[_named_need(f"N{i}") for i in range(1, 8)],
        plos=[_core_plo(i) for i in range(1, 8)],
    )
    merged = _core_plo(1, need_ids=["N1", "N2"])
    with patch(
        "curriculum_agent.stages.plo_synthesis.synthesize_from_needs",
        AsyncMock(return_value=merged),
    ):
        response = await client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]}
        )

    assert response.status_code == 200, response.json()
    program_id, removed_ids, added = replace.await_args.args
    assert program_id == "cs-test"
    assert removed_ids == ["PLO1", "PLO2"]
    assert [p.plo_id for p in added] == ["PLO1"]
    # PLO3 is untouched: it cites a Need this merge does not name.
    assert "PLO3" not in removed_ids


async def test_a_merge_reuses_the_lowest_number_it_frees(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """next_plo_id is given the surviving ids, so the merged outcome takes a slot
    it is about to empty rather than counting past ids that are being deleted."""
    _patch_merge(
        monkeypatch,
        needs=[_named_need(f"N{i}") for i in range(1, 8)],
        plos=[_core_plo(i) for i in range(1, 8)],
    )
    captured: dict[str, str] = {}

    async def fake_synth(metadata, needs, program_id, known, plo_id, **kw):  # noqa: ANN001, ANN003
        captured["plo_id"] = plo_id
        return _core_plo(2, need_ids=["N2", "N3"])

    with patch("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", fake_synth):
        response = await client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N2", "N3"]}
        )

    assert response.status_code == 200, response.json()
    # PLO2 and PLO3 are superseded; PLO1 survives, so 2 is the lowest free slot.
    assert captured["plo_id"] == "PLO2"


async def test_from_needs_refuses_to_push_the_core_count_past_the_ceiling(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Merging Needs nothing cites yet adds an outcome without replacing one, so
    the ceiling is still reachable one merge at a time."""
    from curriculum_agent.stages.need_grouping import MAX_CORE_PLOS

    _patch_merge(
        monkeypatch,
        needs=[_named_need(f"N{i}") for i in range(1, MAX_CORE_PLOS + 3)],
        plos=[_core_plo(i) for i in range(1, MAX_CORE_PLOS + 1)],
    )
    # Patched even though the guard should refuse before reaching it: unpatched,
    # a regression here calls the real provider instead of failing the assertion.
    synth = AsyncMock()
    with patch("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", synth):
        response = await client.post(
            "/programs/cs-test/plos/from-needs",
            json={"need_ids": [f"N{MAX_CORE_PLOS + 1}", f"N{MAX_CORE_PLOS + 2}"]},
        )

    assert response.status_code == 422
    assert str(MAX_CORE_PLOS) in response.json()["detail"]
    synth.assert_not_awaited()


async def test_a_replacing_merge_is_allowed_at_the_ceiling(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """The old guard refused every merge once the core count hit ten and told the
    designer to delete outcomes by hand first. A merge that supersedes what it
    covers lowers the count, so there is nothing left to refuse."""
    from curriculum_agent.stages.need_grouping import MAX_CORE_PLOS

    _patch_merge(
        monkeypatch,
        needs=[_named_need(f"N{i}") for i in range(1, MAX_CORE_PLOS + 1)],
        plos=[_core_plo(i) for i in range(1, MAX_CORE_PLOS + 1)],
    )
    merged = _core_plo(1, need_ids=["N1", "N2"])
    with patch(
        "curriculum_agent.stages.plo_synthesis.synthesize_from_needs",
        AsyncMock(return_value=merged),
    ):
        response = await client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]}
        )

    assert response.status_code == 200, response.json()
    assert response.json()["source_need_ids"] == ["N1", "N2"]


async def test_from_needs_refuses_a_merge_that_falls_through_the_floor(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """The merge floor refuses only when this merge is what causes the shortfall.
    Four core PLOs, two folded into one, leaves three — below the merge floor."""
    from curriculum_agent.stages.need_grouping import MIN_CORE_AFTER_MERGE

    _patch_merge(
        monkeypatch,
        needs=[_named_need(f"N{i}") for i in range(1, MIN_CORE_AFTER_MERGE + 1)],
        plos=[_core_plo(i) for i in range(1, MIN_CORE_AFTER_MERGE + 1)],
    )
    synth = AsyncMock()
    with patch("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", synth):
        response = await client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]}
        )

    assert response.status_code == 422
    assert str(MIN_CORE_AFTER_MERGE) in response.json()["detail"]
    synth.assert_not_awaited()


async def test_a_program_already_below_the_floor_can_still_merge(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """The floor guard blocks a merge that causes the shortfall, not every merge
    afterwards — a program with too few Needs to begin with must not be frozen."""
    from curriculum_agent.stages.need_grouping import MIN_NEEDS

    # Three core outcomes, already below the merge floor. Merging two optional Needs leaves
    # the core count exactly where it was.
    _patch_merge(
        monkeypatch,
        needs=[_named_need("N8", optional=True), _named_need("N9", optional=True)],
        plos=[_core_plo(i) for i in range(1, MIN_NEEDS - 2)],
    )
    merged = _core_plo(1, optional=True, need_ids=["N8", "N9"])
    with patch(
        "curriculum_agent.stages.plo_synthesis.synthesize_from_needs",
        AsyncMock(return_value=merged),
    ):
        response = await client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N8", "N9"]}
        )

    assert response.status_code == 200, response.json()


async def test_from_needs_leaves_an_optional_merge_outside_the_ceiling(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Optional PLOs sit outside the 6-10 count in synthesis, and a merge of
    want-based Needs is optional too — a full core set must not block one."""
    from curriculum_agent.stages.need_grouping import MAX_CORE_PLOS

    _patch_merge(
        monkeypatch,
        needs=[_named_need("N11", optional=True), _named_need("N12", optional=True)],
        plos=[_core_plo(i) for i in range(1, MAX_CORE_PLOS + 1)],
    )
    merged = _core_plo(1, optional=True, need_ids=["N11", "N12"])
    with patch(
        "curriculum_agent.stages.plo_synthesis.synthesize_from_needs",
        AsyncMock(return_value=merged),
    ):
        response = await client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N11", "N12"]}
        )

    assert response.status_code == 200, response.json()
    assert response.json()["is_optional"] is True


async def test_a_need_left_behind_by_a_superseded_plo_returns_to_the_pool(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Merging N1 into a new outcome supersedes the PLO that covered N1 and N2,
    so N2 ends up behind nothing. That is correct — it is no longer cited — but
    it is not what the designer asked for, so the route says so."""
    replace = _patch_merge(
        monkeypatch,
        needs=[_named_need(f"N{i}") for i in range(1, 9)],
        plos=[_core_plo(1, need_ids=["N1", "N2"]), *(_core_plo(i) for i in range(3, 9))],
    )
    merged = _core_plo(1, need_ids=["N1", "N3"])
    with patch(
        "curriculum_agent.stages.plo_synthesis.synthesize_from_needs",
        AsyncMock(return_value=merged),
    ):
        response = await client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N3"]}
        )

    assert response.status_code == 200, response.json()
    _, removed_ids, added = replace.await_args.args
    assert removed_ids == ["PLO1", "PLO3"]
    # N2 is cited by nothing that remains.
    assert "N2" not in {nid for p in added for nid in p.source_need_ids}


async def test_a_failed_synthesis_leaves_the_stored_set_untouched(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Supersede and insert happen together, after the model has answered — a
    provider failure must not leave the curriculum with holes in it."""
    replace = _patch_merge(
        monkeypatch,
        needs=[_named_need(f"N{i}") for i in range(1, 8)],
        plos=[_core_plo(i) for i in range(1, 8)],
    )
    with patch(
        "curriculum_agent.stages.plo_synthesis.synthesize_from_needs",
        AsyncMock(return_value=None),
    ):
        response = await client.post(
            "/programs/cs-test/plos/from-needs", json={"need_ids": ["N1", "N2"]}
        )

    assert response.status_code == 502
    replace.assert_not_awaited()
