from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from curriculum_agent.data.orm import PLOReviewTable
from curriculum_agent.data.repositories import PLOReviewRepository
from curriculum_agent.models import (
    BloomFinding,
    BloomLevel,
    KsecFinding,
    PLOSetReview,
    RedundancyFinding,
)

_REVIEW = PLOSetReview(
    program_id="p",
    plo_fingerprint="f" * 64,
    model="z-ai/glm-5.3-flash",
    created_at=datetime(2026, 10, 5, 12, 0, 0),
    redundancies=[RedundancyFinding(plo_ids=["PLO1", "PLO4"], reason_th="ซ้ำ", suggestion_th="รวม")],
    ksec=[
        KsecFinding(
            plo_id="PLO6", current=["S"], suggested=["S", "E"], agrees=False, reason_th="จริยธรรม"
        )
    ],
    bloom=[
        BloomFinding(
            plo_id="PLO5",
            declared=BloomLevel.CREATE,
            suggested_level=BloomLevel.APPLY,
            reason_th="ปริญญาตรี",
        )
    ],
    bloom_distribution_th="apply เป็นหลัก",
    summary_th="มีสองข้อซ้ำกัน",
)


def _ctx(session: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def test_table_is_keyed_by_program() -> None:
    assert {c.name for c in PLOReviewTable.__table__.primary_key.columns} == {"program_id"}


async def test_upsert_then_get_round_trips_the_review() -> None:
    stored: dict[str, PLOReviewTable] = {}
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda cls, key: stored.get(key))
    session.add = MagicMock(side_effect=lambda row: stored.__setitem__(row.program_id, row))
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        await PLOReviewRepository().upsert(_REVIEW)
        got = await PLOReviewRepository().get("p")
    assert got == _REVIEW


async def test_get_answers_none_for_a_program_never_reviewed() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        assert await PLOReviewRepository().get("nobody") is None


async def test_upsert_replaces_the_existing_row() -> None:
    existing = PLOReviewTable(
        program_id="p", plo_fingerprint="old", model="m", created_at=datetime(2026, 1, 1), review={}
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=existing)
    session.add = MagicMock()
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        await PLOReviewRepository().upsert(_REVIEW)
    session.add.assert_not_called()
    assert existing.plo_fingerprint == "f" * 64
    assert existing.review["summary_th"] == "มีสองข้อซ้ำกัน"


def test_program_delete_cascade_drops_the_review() -> None:
    source = Path("src/curriculum_agent/data/repositories.py").read_text(encoding="utf-8")
    cascade = source.split("async def delete_cascade", 1)[1].split("async def ", 1)[0]
    assert "PLOReviewTable" in cascade
    assert cascade.index("PLOReviewTable") < cascade.index("ProgramTable")


@pytest.fixture
def migration() -> ModuleType:
    path = next(Path("migrations/versions").glob("*_plo_reviews.py"))
    spec = importlib.util.spec_from_file_location("plo_reviews_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_follows_the_composite_key_migration(migration: ModuleType) -> None:
    assert migration.down_revision == "e4b6d19a3f72"


def test_upgrade_creates_and_downgrade_drops_the_table(migration: ModuleType) -> None:
    op = MagicMock()
    with patch.object(migration, "op", op):
        migration.upgrade()
        migration.downgrade()
    assert op.create_table.call_args.args[0] == "plo_reviews"
    op.drop_table.assert_called_once_with("plo_reviews")
