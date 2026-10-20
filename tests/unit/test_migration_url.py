from __future__ import annotations

import pytest

from curriculum_agent.data.migration_url import resolve_migration_url


def test_x_url_wins_over_ini() -> None:
    assert (
        resolve_migration_url({"url": "postgresql+asyncpg://u:p@db:5432/x"}, "ini")
        == "postgresql+asyncpg://u:p@db:5432/x"
    )


def test_falls_back_to_ini_without_x_url() -> None:
    assert resolve_migration_url({}, "ini-url") == "ini-url"


def test_blank_x_url_falls_back_to_ini() -> None:
    assert resolve_migration_url({"url": "  "}, "ini-url") == "ini-url"


def test_raises_when_neither_is_set() -> None:
    with pytest.raises(RuntimeError):
        resolve_migration_url({}, None)
