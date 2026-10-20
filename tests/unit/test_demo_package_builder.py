from __future__ import annotations

import importlib.util
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("demo_package", ROOT / "scripts" / "demo_package.py")
assert _spec is not None and _spec.loader is not None
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)


def compose_template() -> dict[str, Any]:
    text = (ROOT / "packaging" / "demo" / "docker-compose.yml").read_text(encoding="utf-8")
    loaded: dict[str, Any] = yaml.safe_load(text)
    return loaded


def test_read_demo_keys_reads_only_the_two_keys(tmp_path: Path) -> None:
    f = tmp_path / ".env.demo"
    f.write_text(
        '# c\nOPENROUTER_API_KEY="or-1"\nOPENTYPHOON_API_KEY=ty-1\nPLO_SYNTHESIS_MODEL=x\n',
        encoding="utf-8",
    )
    assert dp.read_demo_keys(f) == dp.DemoKeys("or-1", "ty-1")


def test_read_demo_keys_refuses_missing_file(tmp_path: Path) -> None:
    with pytest.raises(dp.PackagingError):
        dp.read_demo_keys(tmp_path / "nope")


@pytest.mark.parametrize(
    "body", ["OPENROUTER_API_KEY=or\n", "OPENROUTER_API_KEY=or\nOPENTYPHOON_API_KEY=\n"]
)
def test_read_demo_keys_refuses_blank_or_absent_key(tmp_path: Path, body: str) -> None:
    f = tmp_path / ".env.demo"
    f.write_text(body, encoding="utf-8")
    with pytest.raises(dp.PackagingError):
        dp.read_demo_keys(f)


def test_render_env_is_exactly_the_allowlist() -> None:
    text = dp.render_package_env(
        version="20261020-1530", keys=dp.DemoKeys("or", "ty"), postgres_password="ab12"
    )
    keys = [line.split("=", 1)[0] for line in text.splitlines() if line]
    assert tuple(keys) == dp.PACKAGE_ENV_KEYS
    assert not any(k.endswith(("_PROVIDER", "_MODEL")) or k == "API_HOST" for k in keys)
    assert "COMPOSE_PROJECT_NAME=curriculum-demo-20261020-1530" in text
    assert "APP_IMAGE=curriculum-demo-app:20261020-1530" in text
    assert "APP_ENV=development" in text
    assert (
        "POSTGRES_DSN=postgresql+asyncpg://curriculum:ab12@postgres:5432/curriculum_agent" in text
    )
    assert '"' not in text and "'" not in text


def test_package_version_format() -> None:
    assert dp.package_version(datetime(2026, 10, 20, 15, 30)) == "20261020-1530"


def test_postgres_image_matches_template_compose() -> None:
    assert compose_template()["services"]["postgres"]["image"] == dp.POSTGRES_IMAGE


def test_expected_alembic_heads_is_nonempty() -> None:
    assert dp.expected_alembic_heads(ROOT)


def test_build_refuses_bad_keys_before_any_docker_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(dp.subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(dp.PackagingError):
        dp.build_package(ROOT, tmp_path / "missing", tmp_path / "out", datetime(2026, 10, 20))
    assert calls == []


def test_env_demo_is_gitignored() -> None:
    assert subprocess.run(["git", "check-ignore", "-q", ".env.demo"], cwd=ROOT).returncode == 0
