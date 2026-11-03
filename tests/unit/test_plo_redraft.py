from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.data.repositories import NeedRepository, PLORepository
from curriculum_agent.models import PLO, Need
from curriculum_agent.stages import plo_redraft
from curriculum_agent.stages.plo_redraft import RedraftFailed, RedraftRefused, redraft_from_needs
from tests.unit.test_api_plos import _need, _plo, _program


def _install(
    monkeypatch: pytest.MonkeyPatch,
    needs: list[Need],
    existing: list[PLO],
    draft: PLO | None,
) -> tuple[AsyncMock, AsyncMock]:
    monkeypatch.setattr(NeedRepository, "list_by_program", AsyncMock(return_value=needs))
    monkeypatch.setattr(PLORepository, "list_by_program", AsyncMock(return_value=existing))
    replace = AsyncMock(return_value=len(existing))
    monkeypatch.setattr(PLORepository, "replace", replace)
    synth = AsyncMock(return_value=draft)
    monkeypatch.setattr("curriculum_agent.stages.plo_synthesis.synthesize_from_needs", synth)
    return replace, synth


async def test_one_need_replaces_exactly_the_plo_citing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    needs = [_need(f"N{i}") for i in range(1, 7)]
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)]
    draft = _plo("PLO2", ["N2"])
    replace, _ = _install(monkeypatch, needs, existing, draft)

    plo, replaced = await redraft_from_needs(
        _program(), "cs-test", ["N2"], note_th=None, cause="designer"
    )

    assert plo is draft
    assert replaced == ["PLO2"]
    replace.assert_awaited_once()
    assert replace.await_args.args == ("cs-test", ["PLO2"], [draft])


async def test_cause_reaches_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    needs = [_need(f"N{i}") for i in range(1, 7)]
    existing = [_plo(f"PLO{i}", [f"N{i}"]) for i in range(1, 7)]
    replace, _ = _install(monkeypatch, needs, existing, _plo("PLO1", ["N1"]))

    await redraft_from_needs(_program(), "cs-test", ["N1"], note_th=None, cause="review")

    assert replace.await_args.kwargs == {"cause": "review"}


async def test_refusal_raises_422_and_replaces_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    replace, synth = _install(monkeypatch, [_need("N1")], [], _plo("PLO1", ["N1"]))

    with pytest.raises(RedraftRefused) as info:
        await redraft_from_needs(_program(), "cs-test", ["NOPE"], note_th=None, cause="designer")

    assert info.value.status == 422
    assert "NOPE" in info.value.detail_th
    replace.assert_not_awaited()
    synth.assert_not_awaited()


async def test_empty_draft_raises_failed_and_replace_is_not_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replace, _ = _install(monkeypatch, [_need("N1")], [_plo("PLO1", ["N1"])], None)

    with pytest.raises(RedraftFailed):
        await redraft_from_needs(_program(), "cs-test", ["N1"], note_th=None, cause="designer")

    replace.assert_not_awaited()


def test_stage_module_imports_nothing_from_api() -> None:
    source = Path(plo_redraft.__file__).read_text(encoding="utf-8")
    assert "curriculum_agent.api" not in source
