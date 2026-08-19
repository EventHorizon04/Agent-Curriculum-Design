from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from curriculum_agent.api.routes import needs as needs_route
from curriculum_agent.api.routes import plos as plos_route
from curriculum_agent.models import (
    NOTE_MAX_CHARS,
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    ProgramMetadata,
    StakeholderEvidence,
)
from curriculum_agent.stages import skill_extraction


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
    assert body[0]["ksec_category"] == "S"


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
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
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

    assert response.status_code == 200, response.text
    assert seen["designer_note"] == NOTE


async def test_needs_run_still_works_with_no_body_at_all(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
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

    assert response.status_code == 200, response.text
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
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
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

    assert response.status_code == 200, response.text
    user_message = captured["messages"][1]["content"]
    assert _program().field in user_message


async def test_plos_run_carries_the_note_into_the_stage_state(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    seen: dict[str, object] = {}

    async def fake_run(state):
        seen.update(state)
        return {**state, "plos": []}

    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    with patch("curriculum_agent.stages.plo_synthesis.run", new=fake_run):
        response = await client.post("/programs/cs-test/plos/run", json={"note_th": NOTE})

    assert response.status_code == 200, response.text
    assert seen["designer_note"] == NOTE


async def test_plos_run_still_works_with_no_body_at_all(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    seen: dict[str, object] = {}

    async def fake_run(state):
        seen.update(state)
        return {**state, "plos": []}

    monkeypatch.setattr(plos_route.ProgramRepository, "get", AsyncMock(return_value=_program()))
    monkeypatch.setattr(
        plos_route.NeedRepository, "list_by_program", AsyncMock(return_value=[_need()])
    )
    with patch("curriculum_agent.stages.plo_synthesis.run", new=fake_run):
        response = await client.post("/programs/cs-test/plos/run")

    assert response.status_code == 200, response.text
    assert "designer_note" not in seen


async def test_from_needs_passes_the_note_to_synthesis(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    captured: dict[str, object] = {}
    second = _need().model_copy(update={"need_id": "N2"})

    async def fake_synth(metadata, needs, program_id, known, plo_id, *, note_th=None):
        captured["note_th"] = note_th
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
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
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

    assert response.status_code == 200, response.text
    assert called is False
    assert response.json()["skills"][0]["skill_name_th"] == "วิเคราะห์ข้อมูลขนาดใหญ่"


async def test_skills_run_carries_the_note_into_the_stage_state(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
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

    assert response.status_code == 200, response.text
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
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
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

    assert response.status_code == 200, response.text
    assert extracted is False
    assert [s["skill_id"] for s in seen["extracted_skills"]] == ["S1"]
    assert "classified_evidence" not in seen
    assert response.json()["needs"][0]["need_id"] == "N1"


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
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
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

    assert response.status_code == 200, response.text
    assert response.json()["needs"][0]["need_id"] == "N1"
