"""The migration's shape, tested without a database.

The five columns are dropped, not renamed or backfilled: the content's new home is
the evidence table, and a program that had them converted keeps those evidence rows
untouched. downgrade() re-adds them nullable, because the original NOT NULL values
are not recoverable once dropped.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

DROPPED = (
    "vision_th",
    "mission_th",
    "philosophy_th",
    "institutional_identity_th",
    "student_identity_th",
)


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    path = next(Path("migrations/versions").glob("*_drop_institutional_metadata.py"))
    spec = importlib.util.spec_from_file_location("drop_institutional", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_names_every_dropped_column(migration: ModuleType) -> None:
    assert set(migration.DROPPED_COLUMNS) == set(DROPPED)


def test_downgrade_restores_them_nullable(migration: ModuleType) -> None:
    source = Path(migration.__file__ or "").read_text(encoding="utf-8")
    downgrade = source.split("def downgrade()")[1]
    for column in DROPPED:
        assert column in downgrade, f"{column} is not restored by downgrade()"
    assert "nullable=True" in downgrade
