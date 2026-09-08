from __future__ import annotations

from fastapi.middleware.cors import CORSMiddleware

from curriculum_agent.api.main import app
from curriculum_agent.config import Settings, settings


def test_cors_origins_come_from_settings_not_a_literal() -> None:
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1
    assert cors[0].kwargs["allow_origins"] is settings.cors_origins


def test_static_is_mounted_exactly_when_serving_is_on() -> None:
    """The mount follows the flag, in both directions.

    The default is off, so an ordinary `TestClient(app)` test keeps its meaning.
    Asserted against `settings` as the process actually resolved it rather than
    against the default, because `scripts/start-demo.ps1` exports
    SERVE_FRONTEND=true into the session it runs in — a suite run from that same
    terminal is a real configuration, not a broken one, and the relationship
    under test holds either way.
    """
    assert Settings(_env_file=None).serve_frontend is False

    mounts = [r for r in app.routes if getattr(r, "name", None) == "frontend"]
    assert len(mounts) == (1 if settings.serve_frontend else 0)
