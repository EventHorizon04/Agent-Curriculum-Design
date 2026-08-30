# tests/unit/test_api_programs.py
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from curriculum_agent.api.main import app
from curriculum_agent.api.routes.programs import _slugify
from curriculum_agent.models import SessionInfo

client = TestClient(app)

_NOW = datetime(2026, 6, 1, 12, 0, 0)

VALID_PROGRAM = {
    "field": "Computer Science",
    "degree_level": "bachelor",
    "duration_years": 4,
    "faculty": "Engineering",
    "university": "Test University",
}


def test_slugify_basic() -> None:
    assert _slugify("Computer Science") == "computer-science"


def test_slugify_strips_symbols_and_case() -> None:
    assert _slugify("  B.Sc. (Data Science)!! ") == "b-sc-data-science"


def test_slugify_empty_fallback() -> None:
    assert _slugify("ภาษาไทยล้วน") == "program"


def test_create_program_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))
    resp = client.post("/programs/", json=VALID_PROGRAM)
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"] == "API key ไม่ถูกต้องหรือไม่ได้ระบุ"


def test_create_program_generates_slug_id(monkeypatch) -> None:
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        mock_repo.insert = AsyncMock()
        mock_repo.exists = AsyncMock(return_value=False)
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    # Intake stopped asking for a program name, so the id comes from the field.
    assert resp.json()["program_id"] == "computer-science"


def test_create_program_id_falls_back_when_the_field_is_thai(monkeypatch) -> None:
    """_slugify keeps ASCII only, so a Thai field slugs to "program". The
    collision suffix is what keeps those distinguishable — assert it engages
    rather than pretending Thai fields produce readable ids."""
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        mock_repo.insert = AsyncMock()
        mock_repo.exists = AsyncMock(side_effect=[True, False])  # "program" taken
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json={**VALID_PROGRAM, "field": "ความสัมพันธ์ระหว่างประเทศ"},
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["program_id"] == "program-2"


def test_create_program_collision_appends_suffix(monkeypatch) -> None:
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        mock_repo.insert = AsyncMock()
        # "computer-science" taken, "computer-science-2" free
        mock_repo.exists = AsyncMock(side_effect=[True, False])
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["program_id"] == "computer-science-2"


def test_create_program_insert_conflict_retries_with_suffix(monkeypatch) -> None:
    """Concurrent-insert race: exists() said free, but INSERT hits a duplicate
    PK. The route must regenerate (now seeing the winner row) and succeed."""
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        # attempt 1: exists("computer-science") -> False, insert -> conflict
        # attempt 2: exists("computer-science") -> True (winner visible),
        #            exists("computer-science-2") -> False, insert -> ok
        mock_repo.exists = AsyncMock(side_effect=[False, True, False])
        mock_repo.insert = AsyncMock(
            side_effect=[IntegrityError("stmt", {}, Exception("duplicate key")), None]
        )
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["program_id"] == "computer-science-2"
    assert mock_repo.insert.await_count == 2


def test_create_program_returns_409_when_attempts_exhausted(monkeypatch) -> None:
    import curriculum_agent.config as cfg
    from curriculum_agent.api.main import app as _app

    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls,
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        mock_repo = AsyncMock()
        mock_repo.exists = AsyncMock(return_value=False)
        mock_repo.insert = AsyncMock(
            side_effect=IntegrityError("stmt", {}, Exception("duplicate key"))
        )
        mock_repo_cls.return_value = mock_repo

        resp = client.post(
            "/programs/",
            json=VALID_PROGRAM,
            headers={"X-API-Key": "secret-key"},
        )
    assert resp.status_code == 409, f"got {resp.status_code}: {resp.json()}"
    assert mock_repo.insert.await_count == 5
    mock_graph.ainvoke.assert_not_awaited()


def test_list_programs_empty() -> None:
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.list_all = AsyncMock(return_value=[])
        mock_repo_cls.return_value = mock_repo
        resp = client.get("/programs/")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json() == []


def test_list_programs_returns_summaries_without_api_key() -> None:
    from datetime import datetime

    from curriculum_agent.models import ProgramSummary

    summaries = [
        ProgramSummary(
            program_id="computer-science",
            name_th="วิทยาการคอมพิวเตอร์",
            name_en="Computer Science",
            degree_level="bachelor",
            created_at=datetime(2026, 7, 2, 9, 0, 0),
            current_stage="plo_synthesis",
            session_status="suspended",
        ),
        ProgramSummary(
            program_id="data-science",
            name_th="วิทยาการข้อมูล",
            name_en="Data Science",
            degree_level="master",
            created_at=datetime(2026, 7, 1, 9, 0, 0),
            current_stage="intake",
        ),
    ]
    with patch("curriculum_agent.api.routes.programs.ProgramRepository") as mock_repo_cls:
        mock_repo = AsyncMock()
        mock_repo.list_all = AsyncMock(return_value=summaries)
        mock_repo_cls.return_value = mock_repo
        resp = client.get("/programs/")
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    body = resp.json()
    assert [p["program_id"] for p in body] == ["computer-science", "data-science"]
    assert body[0]["current_stage"] == "plo_synthesis"
    assert body[1]["current_stage"] == "intake"


@contextmanager
def _delete_program_env(
    *,
    deleted: bool = True,
    threads: list[str] | None = None,
    delete_thread: AsyncMock | None = None,
    calls: list[str] | None = None,
):
    """Both repositories and the graph, wired for the delete route.

    SessionRepository is patched here rather than in each test because the route
    reads it on every path: an unpatched one reaches a database that is not
    running, and the failure reads as a route bug.
    """
    from curriculum_agent.api.main import app as _app

    async def _delete_cascade(_program_id: str) -> bool:
        if calls is not None:
            calls.append("delete_cascade")
        return deleted

    async def _list_by_program(program_id: str) -> list[SessionInfo]:
        if calls is not None:
            calls.append("list_sessions")
        return [
            SessionInfo(
                session_id=f"s{i}",
                program_id=program_id,
                thread_id=t,
                status="rejected",
                created_at=_NOW,
                updated_at=_NOW,
            )
            for i, t in enumerate(threads or [])
        ]

    mock_graph = MagicMock()
    mock_graph.checkpointer.adelete_thread = delete_thread or AsyncMock()

    prog_repo = AsyncMock()
    prog_repo.delete_cascade = AsyncMock(side_effect=_delete_cascade)
    sess_repo = AsyncMock()
    sess_repo.list_by_program = AsyncMock(side_effect=_list_by_program)

    with (
        patch("curriculum_agent.api.routes.programs.ProgramRepository", return_value=prog_repo),
        patch("curriculum_agent.api.routes.programs.SessionRepository", return_value=sess_repo),
        patch.object(_app.state, "graph", mock_graph, create=True),
    ):
        yield mock_graph


def test_delete_program_success() -> None:
    with _delete_program_env():
        resp = client.delete("/programs/computer-science")
    assert resp.status_code == 204, f"got {resp.status_code}"


def test_delete_program_not_found() -> None:
    with _delete_program_env(deleted=False) as graph:
        resp = client.delete("/programs/missing-program")
    assert resp.status_code == 404, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"] == "ไม่พบหลักสูตรนี้"
    graph.checkpointer.adelete_thread.assert_not_awaited()


def test_delete_program_discards_the_program_thread_and_every_session_thread() -> None:
    """Checkpoint rows sit in their own schema with no FK to the program, so the
    cascade cannot reach them — and each one holds a full copy of that program's
    evidence, skills and Needs. create_program runs the graph under the program
    id itself, which is why that thread is dropped alongside the session ones."""
    with _delete_program_env(threads=["computer-science:s0", "computer-science:s1"]) as graph:
        resp = client.delete("/programs/computer-science")

    assert resp.status_code == 204
    discarded = [c.args[0] for c in graph.checkpointer.adelete_thread.await_args_list]
    assert discarded == ["computer-science", "computer-science:s0", "computer-science:s1"]


def test_delete_program_reads_session_threads_before_the_cascade() -> None:
    """The cascade deletes the session rows the thread ids are recorded on. Read
    them afterwards and the ids are gone, leaving checkpoints nothing can find."""
    calls: list[str] = []
    with _delete_program_env(threads=["computer-science:s0"], calls=calls):
        resp = client.delete("/programs/computer-science")

    assert resp.status_code == 204
    assert calls == ["list_sessions", "delete_cascade"]


def test_delete_program_reports_success_when_the_checkpoint_delete_fails() -> None:
    """The program is already gone by then. Answering 500 would tell the designer
    nothing was deleted, and a retry would 404 — the leftover rows are logged."""
    failing = AsyncMock(side_effect=RuntimeError("checkpointer down"))
    with _delete_program_env(threads=["computer-science:s0"], delete_thread=failing):
        resp = client.delete("/programs/computer-science")

    assert resp.status_code == 204
    assert failing.await_count == 2


def test_delete_program_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", SecretStr("secret-key"))
    resp = client.delete("/programs/computer-science")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"] == "API key ไม่ถูกต้องหรือไม่ได้ระบุ"


def test_suggest_isced_route_is_gone() -> None:
    resp = client.post(
        "/programs/suggest-isced",
        json={
            "name_th": "วิทยาการคอมพิวเตอร์",
            "name_en": "Computer Science",
            "field": "CS",
        },
    )
    # The dynamic GET/DELETE "/{program_id}" routes still match this path
    # structurally, so Starlette answers "method not allowed" (405) rather than
    # "not found" (404) once the POST route itself is gone.
    assert resp.status_code == 405


def test_extract_metadata_route_is_gone() -> None:
    resp = client.post("/programs/extract-metadata", files={"file": ("a.pdf", b"x")})
    assert resp.status_code == 405


def test_programs_module_has_no_leftover_isced_or_metadata_symbols() -> None:
    """The 405 checks above only pin "POST here is unhandled" — that stays true
    even if the handler comes back under a different verb or path. Assert
    against the module namespace too, the same way test_intake_stage_exports_only_run
    does for the stage module, so a re-registered handler or leftover request
    model would fail this test regardless of which route it's mounted on."""
    from curriculum_agent.api.routes import programs

    for name in ("suggest_isced_route", "SuggestIscedRequest", "extract_metadata"):
        assert not hasattr(programs, name), f"{name} should have been deleted"


def test_intake_stage_exports_only_run() -> None:
    """The stage kept helpers for two features that no longer exist, plus a
    conversion whose source fields are gone."""
    from curriculum_agent.stages import intake

    for name in (
        "suggest_isced",
        "extract_metadata_from_text",
        "build_institutional_evidence",
        "INSTITUTIONAL_FIELDS",
        "grounding_ratio",
        "low_grounding_fields",
    ):
        assert not hasattr(intake, name), f"{name} should have been deleted"
