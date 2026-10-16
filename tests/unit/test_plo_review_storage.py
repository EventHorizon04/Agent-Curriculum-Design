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
    BloomHistogram,
    BloomLevel,
    KsecCoverage,
    KsecFinding,
    PLOSetReview,
    RedundancyFinding,
    ReviewToolCall,
    UnusedNeedFinding,
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
    unused_needs=[
        UnusedNeedFinding(
            need_id="n9",
            statement_th="ต้องการบัณฑิตที่ใช้ภาษาที่สามได้",
            demand_score=0.7,
            ksec_category="S",
            exclusion="lost_on_demand",
            verdict="should_be_covered",
            reason_th="ความต้องการสูง",
        )
    ],
    reviewed_by="code_only",
    code_only_reason="timeout",
    tool_calls=[ReviewToolCall(tool="read_need", arg="n9")],
)


# Every field non-default, so a field that is not stored reads back as its default
# and breaks equality. Keep it complete: the test below fails when a field is added
# to PLOSetReview and not here.
_FULL_REVIEW = _REVIEW.model_copy(
    update={
        "redundancies": [
            RedundancyFinding(
                plo_ids=["PLO1", "PLO4"], reason_th="ซ้ำ", suggestion_th="รวม", agreed_runs=2
            )
        ],
        "ksec": [
            KsecFinding(
                plo_id="PLO6",
                current=["S"],
                suggested=["S", "E"],
                agrees=False,
                reason_th="จริยธรรม",
                agreed_runs=2,
            )
        ],
        "bloom": [
            BloomFinding(
                plo_id="PLO5",
                declared=BloomLevel.CREATE,
                suggested_level=BloomLevel.APPLY,
                reason_th="ปริญญาตรี",
                agreed_runs=2,
            )
        ],
        "coverage_th": "ครบ K S",
        "ksec_coverage": KsecCoverage(counts={"K": 2}, missing=["E"], flags=["missing_E"]),
        "bloom_histogram": BloomHistogram(
            counts={"apply": 3}, degree_level="bachelor", flags=["too_high"]
        ),
        "reviewed_by": "code_only",
        "code_only_reason": "failed",
        "dropped_findings": {"redundancy": 1},
        "runs_requested": 3,
        "runs_succeeded": 2,
        "agreement_threshold": 2,
        "unused_needs": [
            _REVIEW.unused_needs[0].model_copy(update={"agreed_runs": 2, "unwritten": True})
        ],
    }
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


async def test_every_review_field_survives_storage() -> None:
    defaults = PLOSetReview(
        program_id="x", plo_fingerprint="x", model="x", created_at=datetime(2026, 1, 1)
    )
    for name in PLOSetReview.model_fields:
        if name in {"program_id", "plo_fingerprint", "model", "created_at"}:
            continue
        assert getattr(_FULL_REVIEW, name) != getattr(defaults, name), (
            f"fixture leaves {name} at its default — set it so the round trip can see it"
        )
    stored: dict[str, PLOReviewTable] = {}
    session = AsyncMock()
    session.get = AsyncMock(side_effect=lambda cls, key: stored.get(key))
    session.add = MagicMock(side_effect=lambda row: stored.__setitem__(row.program_id, row))
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        await PLOReviewRepository().upsert(_FULL_REVIEW)
        got = await PLOReviewRepository().get("p")
    assert got == _FULL_REVIEW


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


async def test_upsert_writes_the_agent_fields_into_the_jsonb_body() -> None:
    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=_ctx(session)):
        await PLOReviewRepository().upsert(_REVIEW)
    body = session.add.call_args.args[0].review
    assert body["reviewed_by"] == "code_only"
    assert body["code_only_reason"] == "timeout"
    assert body["unused_needs"][0]["need_id"] == "n9"
    assert body["tool_calls"] == [{"tool": "read_need", "arg": "n9"}]
    assert "ksec_coverage" in body and "bloom_histogram" in body and "coverage_th" in body


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
