from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Docker ignore patterns are root-anchored, so nested dirs need the "**/" form.
REQUIRED_IGNORES = {
    ".env",
    ".env.*",
    ".venv",
    ".scratch",
    "references",
    "**/node_modules",
    "**/dist",
    ".git",
    "tests",
}


def test_dockerignore_keeps_secrets_and_data_out() -> None:
    lines = {
        line.strip().rstrip("/")
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert lines >= REQUIRED_IGNORES


def test_entrypoint_has_lf_line_endings() -> None:
    assert b"\r" not in (ROOT / "docker" / "entrypoint.sh").read_bytes()


def test_entrypoint_migrates_with_package_dsn_then_execs_api() -> None:
    text = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'alembic -x url="$POSTGRES_DSN" upgrade head' in text
    assert "exec python -m curriculum_agent.api" in text
    assert text.index("alembic") < text.index("exec python")


def test_dockerfile_does_not_reload_or_use_cuda() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--reload" not in text
    assert "cuda" not in text.lower()
    assert "torch" not in text
    assert "uv sync --frozen" in text
    assert "USER " in text
