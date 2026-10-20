from __future__ import annotations

from collections.abc import Mapping


def resolve_migration_url(x_args: Mapping[str, str], ini_url: str | None) -> str:
    """Pick the database URL alembic migrates.

    ``alembic -x url=...`` wins so a container can point migrations at its own
    database; otherwise the ini value applies, which keeps the developer
    workflow (no ``-x``) unchanged.
    """
    override = (x_args.get("url") or "").strip()
    if override:
        return override
    if ini_url and ini_url.strip():
        return ini_url
    raise RuntimeError("No database URL: pass `-x url=...` or set sqlalchemy.url in alembic.ini")
