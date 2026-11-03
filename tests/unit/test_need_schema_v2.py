"""Need schema v2: several KSEC tags, merge links, active-only read, split."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from curriculum_agent.data.program_copy import _REFERENCE_COLUMNS
from curriculum_agent.data.repositories import NeedRepository
from curriculum_agent.models import BloomLevel, KSECCategory, Need
from curriculum_agent.stages.need_grouping import ksec_label


def _data(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "need_id": "N1",
        "program_id": "p",
        "statement_th": "ต้องการบัณฑิตที่ทำงานได้จริง",
        "bloom_level": BloomLevel.APPLY,
        "member_skill_ids": ["S1"],
        "source_evidence_ids": ["E1"],
        "freq": 1,
        "demand_score": 0.5,
    }
    base.update(over)
    return base


def test_old_key_maps_to_single_tag_list() -> None:
    need = Need.model_validate(_data(ksec_category="S"))
    assert need.ksec_categories == [KSECCategory.S]


def test_old_key_does_not_mutate_the_callers_dict() -> None:
    raw = _data(ksec_category="S")
    Need.model_validate(raw)
    assert "ksec_category" in raw and "ksec_categories" not in raw


def test_tags_deduplicated_and_ordered() -> None:
    need = Need.model_validate(_data(ksec_categories=["S", "K", "S"]))
    assert need.ksec_categories == [KSECCategory.K, KSECCategory.S]


def test_empty_tags_rejected() -> None:
    with pytest.raises(ValidationError):
        Need.model_validate(_data(ksec_categories=[]))


def test_unmerged_need_defaults() -> None:
    need = Need.model_validate(_data(ksec_categories=["K"]))
    assert need.merged_into is None
    assert need.merged_from == []
    assert need.top_skill_ids == []
    assert need.merge_reason_th == ""
    assert not need.is_merged


def test_merged_need_reports_is_merged() -> None:
    need = Need.model_validate(_data(ksec_categories=["K"], merged_from=["A", "B"]))
    assert need.is_merged


def test_ksec_label_joins_tags() -> None:
    need = Need.model_validate(_data(ksec_categories=["S", "K"]))
    assert ksec_label(need) == "K+S"


def test_copy_remaps_merged_into() -> None:
    assert "merged_into" in _REFERENCE_COLUMNS


def _session_ctx(session: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def test_active_read_filters_on_merged_into() -> None:
    captured: list[object] = []
    session = AsyncMock()

    async def execute(statement: object) -> MagicMock:
        captured.append(statement)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    session.execute = execute
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_session_ctx(session),
    ):
        assert await NeedRepository().list_active_by_program("p") == []
    assert "merged_into is null" in str(captured[0]).lower()


async def test_split_runs_in_one_session_and_restores_originals() -> None:
    from curriculum_agent.data.orm import NeedTable

    def row(nid: str, **over: Any) -> NeedTable:
        need = Need.model_validate(_data(need_id=nid, ksec_categories=["K"], **over))
        return NeedTable(**need.model_dump(mode="json"))

    merged = row("M", merged_from=["A", "B"])
    a = row("A", merged_into="M")
    b = row("B", merged_into="M")
    session = AsyncMock()
    session.get = AsyncMock(return_value=merged)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [a, b]
    session.execute = AsyncMock(return_value=result)
    ctx = _session_ctx(session)
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=ctx) as factory:
        restored = await NeedRepository().split("p", "M")

    assert factory.call_count == 1  # one session, one transaction
    assert [n.need_id for n in restored] == ["A", "B"]
    assert all(n.merged_into is None for n in restored)
    assert a.merged_into is None and b.merged_into is None
    session.delete.assert_awaited_once_with(merged)
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("found", ["missing", "other_program"])
async def test_split_of_a_need_not_in_this_program_raises_key_error_and_writes_nothing(
    found: str,
) -> None:
    from curriculum_agent.data.orm import NeedTable

    row = None
    if found == "other_program":
        need = Need.model_validate(_data(need_id="M", program_id="other", ksec_categories=["K"]))
        row = NeedTable(**need.model_dump(mode="json"))
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    ctx = _session_ctx(session)
    with (
        patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=ctx),
        pytest.raises(KeyError),
    ):
        await NeedRepository().split("p", "M")

    session.execute.assert_not_awaited()
    session.delete.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_excluded_at_and_merged_by_default_to_none() -> None:
    need = Need.model_validate(_data(ksec_categories=["K"]))
    assert need.excluded_at is None and need.merged_by is None
