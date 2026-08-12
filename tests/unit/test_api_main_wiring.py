from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from curriculum_agent.api.main import app
from curriculum_agent.config import settings


def test_cors_origins_come_from_settings_not_a_literal() -> None:
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_origins"] is settings.cors_origins


def test_no_static_mount_when_serving_is_off() -> None:
    # serve_frontend defaults to False, so importing the app must not mount
    # anything — otherwise every existing TestClient(app) test changes meaning.
    assert settings.serve_frontend is False
    assert not [r for r in app.routes if getattr(r, "name", None) == "frontend"]
