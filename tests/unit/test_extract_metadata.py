# tests/unit/test_extract_metadata.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from curriculum_agent.api.main import app
from curriculum_agent.models import ExtractedMetadata
from curriculum_agent.prompts.extract_metadata import build_extract_metadata_prompt
from curriculum_agent.stages.intake import DOC_TEXT_LIMIT, extract_metadata_from_text

# --- ExtractedMetadata model ---


def test_extracted_metadata_all_fields_default_none() -> None:
    result = ExtractedMetadata()
    assert result.vision_th is None
    assert result.mission_th is None
    assert result.institutional_identity_th is None
    assert result.student_identity_th is None


# --- prompt builder ---


def test_prompt_builder_forbids_fabrication_in_system() -> None:
    messages = build_extract_metadata_prompt("เนื้อหาเอกสาร")
    assert messages[0]["role"] == "system"
    assert "null" in messages[0]["content"]
    assert "ห้ามแต่ง" in messages[0]["content"]


def test_prompt_builder_puts_doc_text_in_user_message() -> None:
    messages = build_extract_metadata_prompt("วิสัยทัศน์ของมหาวิทยาลัยทดสอบ")
    assert messages[1]["role"] == "user"
    assert "วิสัยทัศน์ของมหาวิทยาลัยทดสอบ" in messages[1]["content"]


# --- extract_metadata_from_text helper ---


async def test_extract_helper_returns_llm_result() -> None:
    expected = ExtractedMetadata(vision_th="วิสัยทัศน์", mission_th="พันธกิจ")
    with patch(
        "curriculum_agent.stages.intake.complete_light",
        new=AsyncMock(return_value=expected),
    ) as mock_llm:
        result = await extract_metadata_from_text("ข้อความเอกสาร")
    assert result == expected
    mock_llm.assert_awaited_once()


async def test_extract_helper_truncates_long_text() -> None:
    long_text = "ก" * DOC_TEXT_LIMIT + "MARKER_BEYOND_LIMIT"
    with patch(
        "curriculum_agent.stages.intake.complete_light",
        new=AsyncMock(return_value=ExtractedMetadata()),
    ) as mock_llm:
        await extract_metadata_from_text(long_text)
    messages = mock_llm.await_args.args[1]
    user_content = messages[1]["content"]
    assert "MARKER_BEYOND_LIMIT" not in user_content


# --- route POST /programs/extract-metadata ---

client = TestClient(app)

_LONG_TEXT = "วิสัยทัศน์ พันธกิจ เอกลักษณ์ อัตลักษณ์ ของมหาวิทยาลัยทดสอบ " * 10


def _post_file(
    filename: str = "doc.pdf",
    content: bytes = b"%PDF-1.4 fake",
    api_key: str | None = None,
) -> object:
    headers = {"X-API-Key": api_key} if api_key else {}
    return client.post(
        "/programs/extract-metadata",
        files={"file": (filename, content, "application/octet-stream")},
        headers=headers,
    )


def test_extract_route_success() -> None:
    expected = ExtractedMetadata(vision_th="วิสัยทัศน์", mission_th=None)
    with (
        patch(
            "curriculum_agent.parsers.tika_parser.parse_file",
            return_value=_LONG_TEXT,
        ),
        patch(
            "curriculum_agent.api.routes.programs.extract_metadata_from_text",
            new=AsyncMock(return_value=expected),
        ),
    ):
        resp = _post_file()
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    body = resp.json()
    assert body["vision_th"] == "วิสัยทัศน์"
    assert body["mission_th"] is None


def test_extract_route_rejects_unsupported_extension() -> None:
    resp = _post_file(filename="malware.exe")
    assert resp.status_code == 422


def test_extract_route_rejects_oversize_file() -> None:
    resp = _post_file(content=b"x" * (10 * 1024 * 1024 + 1))
    assert resp.status_code == 413


def test_extract_route_rejects_oversize_file_via_preread_gate(monkeypatch) -> None:
    """Lower the limit so a small (2 KB) upload trips the pre-read `file.size`
    gate, proving the gate fires without needing a 10 MB+ payload."""
    monkeypatch.setattr("curriculum_agent.api.routes.programs._MAX_FILE_BYTES", 1024)
    resp = _post_file(content=b"x" * 2048)
    assert resp.status_code == 413


def test_extract_route_rejects_empty_parse_result() -> None:
    with patch(
        "curriculum_agent.parsers.tika_parser.parse_file",
        return_value="   ",
    ):
        resp = _post_file()
    assert resp.status_code == 422


def test_extract_route_maps_parse_error_to_422() -> None:
    with patch(
        "curriculum_agent.parsers.tika_parser.parse_file",
        side_effect=RuntimeError("boom"),
    ):
        resp = _post_file()
    assert resp.status_code == 422


def test_extract_route_maps_llm_error_to_502() -> None:
    with (
        patch(
            "curriculum_agent.parsers.tika_parser.parse_file",
            return_value=_LONG_TEXT,
        ),
        patch(
            "curriculum_agent.api.routes.programs.extract_metadata_from_text",
            new=AsyncMock(side_effect=RuntimeError("llm down")),
        ),
    ):
        resp = _post_file()
    assert resp.status_code == 502


def test_extract_route_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")
    resp = _post_file()
    assert resp.status_code == 401
