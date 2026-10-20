"""Build the customer demo zip: app image, seed database dump, images, .env.

Runs on the developer's machine, against the local dev stack (container
``ca-postgres``). Nothing here is read from the dev ``.env``: the package
``.env`` is rendered from an allowlist plus the two demo keys.
"""

from __future__ import annotations

import argparse
import gzip
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

POSTGRES_IMAGE = "postgres:16-alpine"
APP_PORT = 8765
DEMO_KEY_NAMES = ("OPENROUTER_API_KEY", "OPENTYPHOON_API_KEY")
PACKAGE_ENV_KEYS = (
    "COMPOSE_PROJECT_NAME",
    "APP_IMAGE",
    "APP_PORT",
    "APP_ENV",
    "SERVE_FRONTEND",
    "FRONTEND_DIST",
    "POSTGRES_PASSWORD",
    "POSTGRES_DSN",
    "OPENROUTER_API_KEY",
    "OPENTYPHOON_API_KEY",
)

_DB_CONTAINER = "ca-postgres"
_DB_USER = "curriculum"
_DB_NAME = "curriculum_agent"


class PackagingError(RuntimeError):
    """A refusal to build; the message is safe to print (never holds a key)."""


class DemoKeys(NamedTuple):
    openrouter: str
    opentyphoon: str


def read_demo_keys(path: Path) -> DemoKeys:
    if not path.is_file():
        raise PackagingError(f"Demo keys file not found: {path}")
    found: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in DEMO_KEY_NAMES:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        found[name] = value
    missing = [n for n in DEMO_KEY_NAMES if not found.get(n)]
    if missing:
        raise PackagingError(f"Demo keys file {path} is missing or blank: {', '.join(missing)}")
    return DemoKeys(found["OPENROUTER_API_KEY"], found["OPENTYPHOON_API_KEY"])


def package_version(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M")


def render_package_env(
    *, version: str, keys: DemoKeys, postgres_password: str, app_port: int = APP_PORT
) -> str:
    # Values are written unquoted: start.ps1 parses KEY=VALUE and keeps quotes.
    values = {
        "COMPOSE_PROJECT_NAME": f"curriculum-demo-{version}",
        "APP_IMAGE": f"curriculum-demo-app:{version}",
        "APP_PORT": str(app_port),
        "APP_ENV": "development",
        "SERVE_FRONTEND": "true",
        "FRONTEND_DIST": "/app/frontend/dist",
        "POSTGRES_PASSWORD": postgres_password,
        "POSTGRES_DSN": (
            f"postgresql+asyncpg://{_DB_USER}:{postgres_password}@postgres:5432/{_DB_NAME}"
        ),
        "OPENROUTER_API_KEY": keys.openrouter,
        "OPENTYPHOON_API_KEY": keys.opentyphoon,
    }
    return "".join(f"{k}={values[k]}\n" for k in PACKAGE_ENV_KEYS)


def expected_alembic_heads(repo_root: Path) -> set[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(repo_root / "alembic.ini"))
    return set(ScriptDirectory.from_config(config).get_heads())


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError as exc:
        raise PackagingError(f"{what}: command not found ({cmd[0]})") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()[-500:]
        raise PackagingError(f"{what} failed (exit {exc.returncode}): {detail}") from exc


def _psql(query: str, what: str) -> str:
    out = _run(
        ["docker", "exec", _DB_CONTAINER, "psql", "-U", _DB_USER, "-d", _DB_NAME, "-tAc", query],
        what,
    )
    return out.stdout.strip()


def _dump_seed(target: Path) -> None:
    """Stream pg_dump into a gzip file; refuse a dump with no programs rows."""
    cmd = [
        "docker", "exec", _DB_CONTAINER, "pg_dump",
        "-U", _DB_USER, "-d", _DB_NAME, "--no-owner", "--no-privileges",
    ]  # fmt: skip
    has_programs = False
    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
            assert proc.stdout is not None
            with gzip.open(target, "wb") as gz:
                for line in proc.stdout:
                    if line.startswith(b"COPY public.programs "):
                        has_programs = True
                    gz.write(line)
            stderr = (proc.stderr.read().decode("utf-8", "replace") if proc.stderr else "").strip()
            if proc.wait() != 0:
                raise PackagingError(f"pg_dump failed (exit {proc.returncode}): {stderr[-500:]}")
    except FileNotFoundError as exc:
        raise PackagingError("pg_dump: docker not found") from exc
    if not has_programs:
        raise PackagingError("The dump has no 'COPY public.programs' section; refusing to ship it.")


def build_package(repo_root: Path, keys_file: Path, out_dir: Path, now: datetime) -> Path:
    keys = read_demo_keys(keys_file)

    heads = expected_alembic_heads(repo_root)
    current = _psql("select version_num from alembic_version", "Reading the dev DB revision")
    if current not in heads:
        raise PackagingError(
            f"Dev DB revision {current or '(none)'} is not at alembic head {sorted(heads)}; "
            "run the migrations first."
        )
    count_text = _psql("select count(*) from programs", "Counting programs in the dev DB")
    programs = int(count_text) if count_text.isdigit() else 0
    if programs < 1:
        raise PackagingError("The dev DB has no programs; there would be nothing to demo.")

    version = package_version(now)
    name = f"curriculum-demo-{version}"
    package_dir = out_dir / name
    if package_dir.exists():
        raise PackagingError(f"Package folder already exists: {package_dir}")
    tag = f"curriculum-demo-app:{version}"

    _run(["docker", "build", "--platform", "linux/amd64", "-t", tag, str(repo_root)], "Image build")
    _run(["docker", "pull", "--platform", "linux/amd64", POSTGRES_IMAGE], "Postgres image pull")

    zip_target = out_dir / f"{name}.zip"
    zip_started = False
    package_dir.mkdir(parents=True)
    try:
        for item in (repo_root / "packaging" / "demo").iterdir():
            if item.is_file():
                shutil.copy2(item, package_dir / item.name)

        seed_dir = package_dir / "seed"
        seed_dir.mkdir()
        _dump_seed(seed_dir / "01-seed.sql.gz")

        env_text = render_package_env(
            version=version, keys=keys, postgres_password=secrets.token_hex(16)
        )
        (package_dir / ".env").write_bytes(env_text.encode("utf-8"))

        _run(
            ["docker", "save", "-o", str(package_dir / "images.tar"), tag, POSTGRES_IMAGE],
            "Image save",
        )

        zip_started = True
        zip_path = Path(shutil.make_archive(str(out_dir / name), "zip", out_dir, name))
    except BaseException:
        # The directory may hold the real keys and a partial multi-hundred-MB
        # images.tar; a half-written zip would look complete. Leave neither.
        shutil.rmtree(package_dir, ignore_errors=True)
        if zip_started:
            zip_target.unlink(missing_ok=True)
        raise
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"Package: {zip_path}")
    print(f"Size: {size_mb:.0f} MB")
    print(f"Programs in seed: {programs}")
    print(f"App image: {tag}")
    return zip_path


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build the customer demo package zip.")
    parser.add_argument("--keys-file", default=".env.demo")
    parser.add_argument("--out", default="dist/demo-package")
    args = parser.parse_args(argv)
    keys_file = repo_root / args.keys_file
    out_dir = repo_root / args.out
    try:
        build_package(repo_root, keys_file, out_dir, datetime.now())
    except PackagingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
