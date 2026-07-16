# tests/unit/test_isced.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from curriculum_agent.api.main import app
from curriculum_agent.data.isced import (
    BROAD_FIELDS,
    DETAILED_FIELDS,
    NARROW_FIELDS,
    all_detailed_fields,
    get_detailed_field,
)
from curriculum_agent.models import IscedSuggestion, ProgramCreateRequest, SuggestedName
from curriculum_agent.prompts.suggest_isced import build_suggest_isced_prompt
from curriculum_agent.stages.intake import suggest_isced

# --- taxonomy integrity ---


def test_broad_fields_codes_unique_and_2_digits() -> None:
    codes = [f.code for f in BROAD_FIELDS]
    assert len(codes) == len(set(codes))
    assert all(len(c) == 2 and c.isdigit() for c in codes)


def test_narrow_fields_codes_unique_and_3_digits() -> None:
    codes = [f.code for f in NARROW_FIELDS]
    assert len(codes) == len(set(codes))
    assert all(len(c) == 3 and c.isdigit() for c in codes)


def test_detailed_fields_codes_unique_and_4_digits() -> None:
    codes = [f.code for f in DETAILED_FIELDS]
    assert len(codes) == len(set(codes))
    assert all(len(c) == 4 and c.isdigit() for c in codes)


def test_narrow_prefix_exists_in_broad() -> None:
    broad_codes = {f.code for f in BROAD_FIELDS}
    for narrow in NARROW_FIELDS:
        assert narrow.code[:2] in broad_codes, f"narrow {narrow.code} has no broad parent"


def test_detailed_prefix_exists_in_narrow() -> None:
    narrow_codes = {f.code for f in NARROW_FIELDS}
    for detailed in DETAILED_FIELDS:
        assert detailed.code[:3] in narrow_codes, f"detailed {detailed.code} has no narrow parent"


def test_every_field_has_thai_name() -> None:
    for field in BROAD_FIELDS + NARROW_FIELDS + DETAILED_FIELDS:
        assert field.name_th.strip(), f"{field.code} missing name_th"


# --- helpers ---


def test_get_detailed_field_hit() -> None:
    result = get_detailed_field("0613")
    assert result is not None
    assert result.name_en == "Software and applications development and analysis"


def test_get_detailed_field_miss() -> None:
    assert get_detailed_field("9999") is None


def test_all_detailed_fields_returns_full_list() -> None:
    assert all_detailed_fields() == DETAILED_FIELDS
    assert len(all_detailed_fields()) > 50


# --- isced_code validator on ProgramCreateRequest ---


def _valid_program_kwargs() -> dict:
    return {
        "name_th": "วิทยาการคอมพิวเตอร์",
        "name_en": "Computer Science",
        "field": "Computer Science",
        "degree_level": "bachelor",
        "duration_years": 4,
        "faculty": "วิศวกรรมศาสตร์",
        "university": "มหาวิทยาลัยทดสอบ",
        "vision_th": "วิสัยทัศน์",
        "mission_th": "พันธกิจ",
        "philosophy_th": "ปรัชญา",
        "program_goals_th": ["เป้าหมายที่ 1"],
        "program_objectives_th": ["วัตถุประสงค์ที่ 1"],
    }


def test_isced_code_none_is_valid() -> None:
    req = ProgramCreateRequest(**_valid_program_kwargs())
    assert req.isced_code is None


def test_isced_code_valid_code_accepted() -> None:
    req = ProgramCreateRequest(isced_code="0613", **_valid_program_kwargs())
    assert req.isced_code == "0613"


def test_isced_code_invalid_code_rejected() -> None:
    kwargs = _valid_program_kwargs()
    kwargs["isced_code"] = "9999"
    with pytest.raises(ValidationError):
        ProgramCreateRequest(**kwargs)


# --- SuggestedName / IscedSuggestion models ---


def test_suggested_name_requires_both_fields() -> None:
    name = SuggestedName(name_th="หลักสูตรวิทยาศาสตรบัณฑิต", name_en="Bachelor of Science Program")
    assert name.name_th and name.name_en


def test_isced_suggestion_requires_at_least_one_suggested_name() -> None:
    with pytest.raises(ValidationError):
        IscedSuggestion(
            isced_code="0613",
            field_name_en="Software and applications development and analysis",
            field_name_th="การพัฒนาและวิเคราะห์ซอฟต์แวร์และแอปพลิเคชัน",
            rationale_th="เหตุผล",
            suggested_names=[],
        )


def test_isced_suggestion_rejects_more_than_3_names() -> None:
    names = [SuggestedName(name_th=f"ชื่อ {i}", name_en=f"Name {i}") for i in range(4)]
    with pytest.raises(ValidationError):
        IscedSuggestion(
            isced_code="0613",
            field_name_en="Software and applications development and analysis",
            field_name_th="การพัฒนาและวิเคราะห์ซอฟต์แวร์และแอปพลิเคชัน",
            rationale_th="เหตุผล",
            suggested_names=names,
        )


# --- prompt builder ---


def test_prompt_contains_closed_list_instruction() -> None:
    messages = build_suggest_isced_prompt(
        "วิทยาการคอมพิวเตอร์", "Computer Science", "Computer Science"
    )
    system = messages[0]["content"]
    assert "เท่านั้น" in system
    assert "0613" in system  # sample detailed code must be present in the embedded list


def test_prompt_user_message_contains_program_info() -> None:
    messages = build_suggest_isced_prompt(
        "วิทยาการคอมพิวเตอร์", "Computer Science", "Computer Science"
    )
    user = messages[1]["content"]
    assert "วิทยาการคอมพิวเตอร์" in user
    assert "Computer Science" in user


def test_prompt_retry_mentions_invalid_code() -> None:
    messages = build_suggest_isced_prompt(
        "วิทยาการคอมพิวเตอร์", "Computer Science", "Computer Science", retry_invalid_code="9999"
    )
    system = messages[0]["content"]
    assert "9999" in system


# --- suggest_isced service helper ---


def _make_suggestion(code: str) -> IscedSuggestion:
    return IscedSuggestion(
        isced_code=code,
        field_name_en="WRONG NAME FROM LLM",  # helper must overwrite with taxonomy value
        field_name_th="ชื่อผิดจาก LLM",
        rationale_th="เหตุผล",
        suggested_names=[
            SuggestedName(
                name_th="หลักสูตรวิทยาศาสตรบัณฑิต", name_en="Bachelor of Science Program"
            )
        ],
    )


async def test_suggest_isced_valid_code_overwrites_field_names_from_taxonomy() -> None:
    with patch(
        "curriculum_agent.stages.intake.complete_light",
        new=AsyncMock(return_value=_make_suggestion("0613")),
    ) as mock_llm:
        result = await suggest_isced("วิทยาการคอมพิวเตอร์", "Computer Science", "Computer Science")
    assert result.isced_code == "0613"
    assert result.field_name_en == "Software and applications development and analysis"
    assert result.field_name_th == "การพัฒนาและวิเคราะห์ซอฟต์แวร์และแอปพลิเคชัน"
    mock_llm.assert_awaited_once()


async def test_suggest_isced_retries_once_on_invalid_code_then_succeeds() -> None:
    with patch(
        "curriculum_agent.stages.intake.complete_light",
        new=AsyncMock(side_effect=[_make_suggestion("9999"), _make_suggestion("0613")]),
    ) as mock_llm:
        result = await suggest_isced("วิทยาการคอมพิวเตอร์", "Computer Science", "Computer Science")
    assert result.isced_code == "0613"
    assert mock_llm.await_count == 2


async def test_suggest_isced_raises_after_second_invalid_code() -> None:
    with (
        patch(
            "curriculum_agent.stages.intake.complete_light",
            new=AsyncMock(side_effect=[_make_suggestion("9999"), _make_suggestion("8888")]),
        ) as mock_llm,
        pytest.raises(ValueError, match="8888"),
    ):
        await suggest_isced("วิทยาการคอมพิวเตอร์", "Computer Science", "Computer Science")
    assert mock_llm.await_count == 2


# --- route POST /programs/suggest-isced ---

client = TestClient(app)

_VALID_BODY = {
    "name_th": "วิทยาการคอมพิวเตอร์",
    "name_en": "Computer Science",
    "field": "Computer Science",
}


def test_suggest_isced_route_success() -> None:
    expected = _make_suggestion("0613")
    with patch(
        "curriculum_agent.api.routes.programs.suggest_isced",
        new=AsyncMock(return_value=expected),
    ):
        resp = client.post("/programs/suggest-isced", json=_VALID_BODY)
    assert resp.status_code == 200, f"got {resp.status_code}: {resp.json()}"
    assert resp.json()["isced_code"] == "0613"


def test_suggest_isced_route_missing_field_returns_422() -> None:
    resp = client.post("/programs/suggest-isced", json={"name_th": "x", "name_en": "y"})
    assert resp.status_code == 422


def test_suggest_isced_route_helper_error_returns_502() -> None:
    with patch(
        "curriculum_agent.api.routes.programs.suggest_isced",
        new=AsyncMock(side_effect=ValueError("bad code")),
    ):
        resp = client.post("/programs/suggest-isced", json=_VALID_BODY)
    assert resp.status_code == 502


def test_suggest_isced_route_requires_api_key_when_configured(monkeypatch) -> None:
    import curriculum_agent.config as cfg

    monkeypatch.setattr(cfg.settings, "api_key", "secret-key")
    resp = client.post("/programs/suggest-isced", json=_VALID_BODY)
    assert resp.status_code == 401
