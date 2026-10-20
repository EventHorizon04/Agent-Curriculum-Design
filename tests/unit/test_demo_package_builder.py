from __future__ import annotations

import importlib.util
import io
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


def _stub_happy_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    keys = tmp_path / ".env.demo"
    keys.write_text("OPENROUTER_API_KEY=or\nOPENTYPHOON_API_KEY=ty\n", encoding="utf-8")
    monkeypatch.setattr(dp, "expected_alembic_heads", lambda root: {"head1"})

    def fake_run(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
        if cmd[1] == "exec":
            out = "head1" if "alembic_version" in cmd[-1] else "3"
            return subprocess.CompletedProcess(cmd, 0, stdout=out + "\n", stderr="")
        if cmd[1] == "save":
            Path(cmd[3]).write_bytes(b"partial")
            raise dp.PackagingError("Image save failed")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(dp, "_run", fake_run)
    monkeypatch.setattr(dp, "_dump_seed", lambda target: target.write_bytes(b"seed"))
    return keys


def test_failed_save_leaves_no_package_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    keys = _stub_happy_path(monkeypatch, tmp_path)
    out = tmp_path / "out"
    with pytest.raises(dp.PackagingError, match="Image save"):
        dp.build_package(ROOT, keys, out, datetime(2026, 10, 20, 15, 30))
    assert list(out.iterdir()) == []


def test_failed_zip_leaves_neither_dir_nor_partial_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = _stub_happy_path(monkeypatch, tmp_path)
    original_run = dp._run

    def save_ok(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
        if cmd[1] == "save":
            Path(cmd[3]).write_bytes(b"tar")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return original_run(cmd, what)

    def broken_archive(base: str, *a: Any, **k: Any) -> str:
        Path(base + ".zip").write_bytes(b"half")
        raise KeyboardInterrupt

    monkeypatch.setattr(dp, "_run", save_ok)
    monkeypatch.setattr(dp.shutil, "make_archive", broken_archive)
    out = tmp_path / "out"
    with pytest.raises(KeyboardInterrupt):
        dp.build_package(ROOT, keys, out, datetime(2026, 10, 20, 15, 30))
    assert list(out.iterdir()) == []


def test_env_demo_is_gitignored() -> None:
    assert subprocess.run(["git", "check-ignore", "-q", ".env.demo"], cwd=ROOT).returncode == 0


def _docker_build_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    seen: list[list[str]] = []
    inner = dp._run

    def spy(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return inner(cmd, what)

    monkeypatch.setattr(dp, "_run", spy)
    return seen


def _stub_db_answers(monkeypatch: pytest.MonkeyPatch, *, revision: str, count: str) -> None:
    def fake_run(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
        out = revision if "alembic_version" in cmd[-1] else count
        return subprocess.CompletedProcess(cmd, 0, stdout=out + "\n", stderr="")

    monkeypatch.setattr(dp, "_run", fake_run)


@pytest.mark.parametrize(("revision", "count"), [("other", "3"), ("head1", "0")])
def test_build_refuses_stale_or_empty_db_before_docker_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revision: str, count: str
) -> None:
    keys = _stub_happy_path(monkeypatch, tmp_path)
    _stub_db_answers(monkeypatch, revision=revision, count=count)
    calls = _docker_build_calls(monkeypatch)
    with pytest.raises(dp.PackagingError):
        dp.build_package(ROOT, keys, tmp_path / "out", datetime(2026, 10, 20, 15, 30))
    assert [c for c in calls if c[1] == "build"] == []
    assert not (tmp_path / "out").exists()


class _FakePopen:
    def __init__(self, lines: list[bytes], returncode: int, stderr: bytes = b"") -> None:
        self.stdout = io.BytesIO(b"".join(lines))
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode

    def __enter__(self) -> _FakePopen:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def wait(self) -> int:
        return self.returncode


def _fake_popen(monkeypatch: pytest.MonkeyPatch, fake: _FakePopen) -> None:
    monkeypatch.setattr(dp.subprocess, "Popen", lambda *a, **k: fake)


def test_dump_seed_refuses_dump_without_programs_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_popen(monkeypatch, _FakePopen([b"COPY public.needs (a) FROM stdin;\n"], 0))
    with pytest.raises(dp.PackagingError, match="programs"):
        dp._dump_seed(tmp_path / "seed.sql.gz")


def test_dump_seed_refuses_nonzero_pg_dump_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_popen(
        monkeypatch,
        _FakePopen([b"COPY public.programs (a) FROM stdin;\n"], 1, b"boom"),
    )
    with pytest.raises(dp.PackagingError, match="pg_dump failed"):
        dp._dump_seed(tmp_path / "seed.sql.gz")


def test_successful_build_removes_staging_dir_and_keeps_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = _stub_happy_path(monkeypatch, tmp_path)
    original_run = dp._run

    def save_ok(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
        if cmd[1] == "save":
            Path(cmd[3]).write_bytes(b"tar")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return original_run(cmd, what)

    monkeypatch.setattr(dp, "_run", save_ok)
    out = tmp_path / "out"
    zip_path = dp.build_package(ROOT, keys, out, datetime(2026, 10, 20, 15, 30))
    assert [p.name for p in out.iterdir()] == [zip_path.name]
