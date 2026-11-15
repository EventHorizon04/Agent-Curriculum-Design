from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from curriculum_agent.config import SLOTS, Settings

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "lock_manifest", ROOT / "scripts" / "lock_manifest.py"
)
assert _spec is not None and _spec.loader is not None
lm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lm)

_SECRETS = [
    "sk-test-xyz",
    "typhoon-secret-abc",
    "hunter2-minio",
    "api-secret-qrs",
    "dbpass-9981",
]


def _fake_settings() -> Settings:
    return Settings(
        _env_file=None,
        openrouter_api_key=SecretStr("sk-test-xyz"),
        opentyphoon_api_key=SecretStr("typhoon-secret-abc"),
        minio_secret_key=SecretStr("hunter2-minio"),
        api_key=SecretStr("api-secret-qrs"),
        postgres_dsn="postgresql+asyncpg://admin:dbpass-9981@db.internal:5432/prod",
    )


def _manifest() -> dict[str, Any]:
    return lm.build_manifest(_fake_settings())


def test_no_secret_in_markdown_or_json() -> None:
    manifest = _manifest()
    rendered = [lm.render_markdown(manifest), json.dumps(manifest, default=str)]
    for text in rendered:
        for secret in [*_SECRETS, "db.internal", "admin:"]:
            assert secret not in text


def test_settings_filter_drops_denied_names_and_keeps_token_caps() -> None:
    kept = lm.safe_settings(_fake_settings())
    for name in ("openrouter_api_key", "api_key", "postgres_dsn", "minio_secret_key"):
        assert name not in kept
    assert "extraction_max_tokens" in kept
    assert "extraction_reasoning_max_tokens" in kept
    assert "validation_runs" in kept


def test_value_filter_drops_long_and_url_strings() -> None:
    assert not lm._is_allowed_value("x" * 81)
    assert not lm._is_allowed_value("http://host/x")
    assert lm._is_allowed_value("apply")


def test_prompt_hashes_cover_every_prompt_file() -> None:
    expected = {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "src" / "curriculum_agent" / "prompts").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    hashed = {p["path"] for p in _manifest()["prompts"]}
    assert hashed == expected
    assert any("guidances/" in path for path in hashed)


def test_slot_section_lists_all_slots() -> None:
    manifest = _manifest()
    names = [s["slot"] for s in manifest["slots"]]
    assert names == [slot.name for slot in SLOTS]
    assert len(names) == 8
    markdown = lm.render_markdown(manifest)
    for name in names:
        assert f"| {name} |" in markdown


def test_dirty_tree_is_flagged_at_top() -> None:
    manifest = _manifest()
    manifest["git"] = {**manifest["git"], "dirty": True, "status": " M x.py"}
    assert "DIRTY" in lm.render_markdown(manifest).splitlines()[2]


def test_constants_list_max_group_size() -> None:
    names = {(c["module"], c["name"]) for c in _manifest()["constants"]}
    assert ("curriculum_agent.stages.need_dedup", "MAX_GROUP_SIZE") in names
