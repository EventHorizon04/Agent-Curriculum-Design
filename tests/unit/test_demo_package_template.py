from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

TEMPLATE = Path(__file__).resolve().parents[2] / "packaging" / "demo"


def compose() -> dict[str, Any]:
    text = (TEMPLATE / "docker-compose.yml").read_text(encoding="utf-8")
    loaded: dict[str, Any] = yaml.safe_load(text)
    return loaded


def test_postgres_publishes_no_port_and_seeds_from_folder() -> None:
    pg = compose()["services"]["postgres"]
    assert "ports" not in pg
    assert pg["image"] == "postgres:16.15-alpine"
    assert "./seed:/docker-entrypoint-initdb.d:ro" in pg["volumes"]
    # TCP, not the unix socket: during initdb the image runs a temporary server
    # with listen_addresses='' — a socket check reports "ready" while the seed
    # is still loading, and the app's alembic would race it.
    assert "-h 127.0.0.1" in " ".join(pg["healthcheck"]["test"])


def test_app_binds_loopback_only_and_waits_for_healthy_db() -> None:
    app = compose()["services"]["app"]
    assert app["ports"] == ["127.0.0.1:${APP_PORT}:8000"]
    assert app["image"] == "${APP_IMAGE}"
    assert app["env_file"] == [".env"] or app["env_file"] == ".env"
    assert app["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_no_minio_or_pgadmin() -> None:
    assert set(compose()["services"]) == {"postgres", "app"}


@pytest.mark.parametrize("name", ["start", "stop", "reset"])
def test_ps1_has_bom_and_utf8_console(name: str) -> None:
    raw = (TEMPLATE / f"{name}.ps1").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "[Console]::OutputEncoding = [Text.Encoding]::UTF8" in raw.decode("utf-8-sig")
    assert "Set-Location $PSScriptRoot" in raw.decode("utf-8-sig")


@pytest.mark.parametrize("name", ["start", "stop", "reset"])
def test_cmd_wrapper_bypasses_policy_with_quoted_path(name: str) -> None:
    text = (TEMPLATE / f"{name}.cmd").read_text(encoding="ascii")
    assert f'-ExecutionPolicy Bypass -File "%~dp0{name}.ps1"' in text


def test_start_loads_images_only_when_missing_and_waits_long_enough() -> None:
    text = (TEMPLATE / "start.ps1").read_text(encoding="utf-8-sig")
    assert "docker image inspect" in text and "docker load -i" in text
    assert "$HealthTimeoutSeconds = 300" in text


@pytest.mark.parametrize("name", ["start", "stop", "reset"])
def test_cmd_wrapper_guards_against_running_inside_the_zip(name: str) -> None:
    raw = (TEMPLATE / f"{name}.cmd").read_bytes()
    text = raw.decode("ascii")
    assert f'if not exist "%~dp0{name}.ps1"' in text
    assert "Please extract the zip first" in text
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


@pytest.mark.parametrize("name", ["start", "stop", "reset"])
def test_ps1_lets_the_package_env_beat_the_shell(name: str) -> None:
    text = (TEMPLATE / f"{name}.ps1").read_text(encoding="utf-8-sig")
    assert '"APP_PORT", "APP_IMAGE", "COMPOSE_PROJECT_NAME", "POSTGRES_PASSWORD"' in text
    assert 'Set-Item -Path "Env:$name"' in text


def test_start_validates_port_and_points_failures_at_reset() -> None:
    text = (TEMPLATE / "start.ps1").read_text(encoding="utf-8-sig")
    assert r"-notmatch '^\d{2,5}$'" in text
    assert text.count("reset.cmd") == 2
