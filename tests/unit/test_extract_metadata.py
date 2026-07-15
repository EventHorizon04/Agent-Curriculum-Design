# tests/unit/test_extract_metadata.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
