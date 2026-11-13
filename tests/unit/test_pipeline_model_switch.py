"""PIPELINE_PROVIDER / PIPELINE_MODEL: one switch for every LLM slot."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from curriculum_agent.config import _PROVIDER_DEFAULT_MODEL, SLOTS, Settings


def _resolved(s: Settings) -> dict[str, tuple[str, str]]:
    return {
        slot.name: (getattr(s, slot.provider_field), getattr(s, slot.model_field)) for slot in SLOTS
    }


def test_opted_out_pipeline_matches_explicit_none_and_empty_model() -> None:
    baseline = _resolved(Settings(_env_file=None, pipeline_provider=None))
    explicit = _resolved(Settings(_env_file=None, pipeline_provider=None, pipeline_model=""))
    assert explicit == baseline


def test_pipeline_pair_applies_to_every_slot_without_own_setting() -> None:
    s = Settings(_env_file=None, pipeline_provider="openrouter", pipeline_model="x/y")
    assert set(_resolved(s).values()) == {("openrouter", "x/y")}
    assert len(_resolved(s)) == len(SLOTS)


def test_slot_own_provider_wins_and_never_takes_pipeline_model() -> None:
    s = Settings(
        _env_file=None,
        pipeline_provider="openrouter",
        pipeline_model="x/y",
        validation_provider="ollama",
    )
    got = _resolved(s)
    assert got["validation"] == ("ollama", _PROVIDER_DEFAULT_MODEL["ollama"])
    assert all(v == ("openrouter", "x/y") for k, v in got.items() if k != "validation")


def test_slot_own_model_only_runs_on_pipeline_provider() -> None:
    s = Settings(
        _env_file=None,
        pipeline_provider="openrouter",
        pipeline_model="x/y",
        plo_review_model="a/b",
    )
    assert _resolved(s)["plo_review"] == ("openrouter", "a/b")


def test_empty_provider_still_disables_under_pipeline() -> None:
    s = Settings(
        _env_file=None,
        pipeline_provider="openrouter",
        pipeline_model="x/y",
        need_dedup_provider="",
    )
    assert s.need_dedup_provider == ""


def test_pipeline_provider_without_model_uses_slot_defaults() -> None:
    s = Settings(_env_file=None, pipeline_provider="openrouter")
    got = _resolved(s)
    assert all(p == "openrouter" for p, _ in got.values())
    assert got["clustering"][1] == "meta-llama/llama-3.3-70b-instruct"


def test_pipeline_model_with_pipeline_off_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pipeline_provider=None, pipeline_model="x/y")


# ----------------------- through the environment, not kwargs -----------------------


def _clear_slot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ambient slot or pipeline variable may leak in from the developer's shell."""
    for name in ("PIPELINE_PROVIDER", "PIPELINE_MODEL", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    for slot in SLOTS:
        monkeypatch.delenv(slot.provider_field.upper(), raising=False)
        monkeypatch.delenv(slot.model_field.upper(), raising=False)


def test_pipeline_pair_from_the_environment_applies_to_every_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_slot_env(monkeypatch)
    monkeypatch.setenv("PIPELINE_PROVIDER", "openrouter")
    monkeypatch.setenv("PIPELINE_MODEL", "x/y")

    got = _resolved(Settings(_env_file=None))

    assert set(got.values()) == {("openrouter", "x/y")}


def test_a_slot_env_provider_beats_the_pipeline_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_slot_env(monkeypatch)
    monkeypatch.setenv("PIPELINE_PROVIDER", "openrouter")
    monkeypatch.setenv("PIPELINE_MODEL", "x/y")
    monkeypatch.setenv("VALIDATION_PROVIDER", "ollama")

    got = _resolved(Settings(_env_file=None))

    assert got["validation"] == ("ollama", _PROVIDER_DEFAULT_MODEL["ollama"])
    assert all(v == ("openrouter", "x/y") for k, v in got.items() if k != "validation")


# What every slot resolves to when the pipeline pair is opted out (PIPELINE_PROVIDER=""):
# read once from `git show main:src/curriculum_agent/config.py` with no slot variable set.
_MAIN_RESOLUTION: dict[str, tuple[str, str]] = {
    "extraction": ("openrouter", "z-ai/glm-5.3-flash"),
    "clustering": ("openrouter", "meta-llama/llama-3.3-70b-instruct"),
    "need_combination": ("opentyphoon", "typhoon-v2.5-30b-a3b-instruct"),
    "need_dedup": ("openrouter", "z-ai/glm-5.3-flash"),
    "plo_synthesis": ("opentyphoon", "typhoon-v2.5-30b-a3b-instruct"),
    "validation": ("openrouter", "z-ai/glm-5.3-flash"),
    "plo_review": ("openrouter", "z-ai/glm-5.3-flash"),
}


def test_unset_everything_resolves_every_slot_to_the_glm_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_slot_env(monkeypatch)

    assert set(_resolved(Settings(_env_file=None)).values()) == {
        ("openrouter", "z-ai/glm-5.3-flash")
    }


def test_empty_pipeline_provider_env_resolves_every_slot_as_main_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_slot_env(monkeypatch)
    monkeypatch.setenv("PIPELINE_PROVIDER", "")

    assert _resolved(Settings(_env_file=None)) == _MAIN_RESOLUTION


def test_pipeline_provider_none_kwarg_resolves_every_slot_as_main_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_slot_env(monkeypatch)

    assert _resolved(Settings(_env_file=None, pipeline_provider=None)) == _MAIN_RESOLUTION


def test_pipeline_provider_alone_never_carries_the_glm_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_slot_env(monkeypatch)
    monkeypatch.setenv("PIPELINE_PROVIDER", "ollama")

    got = _resolved(Settings(_env_file=None))

    assert all(p == "ollama" for p, _ in got.values())
    assert all(m != "z-ai/glm-5.3-flash" for _, m in got.values())


def test_empty_pipeline_provider_with_a_model_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_slot_env(monkeypatch)
    monkeypatch.setenv("PIPELINE_PROVIDER", "")
    monkeypatch.setenv("PIPELINE_MODEL", "x/y")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_pipeline_model_alone_means_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_slot_env(monkeypatch)
    monkeypatch.setenv("PIPELINE_MODEL", "x/y")

    assert set(_resolved(Settings(_env_file=None)).values()) == {("openrouter", "x/y")}
