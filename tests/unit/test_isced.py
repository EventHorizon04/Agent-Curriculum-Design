# tests/unit/test_isced.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from curriculum_agent.data.isced import (
    BROAD_FIELDS,
    DETAILED_FIELDS,
    NARROW_FIELDS,
    all_detailed_fields,
    get_detailed_field,
)
from curriculum_agent.models import ProgramCreateRequest, ProgramMetadata

# The LLM-backed ISCED suggestion (prompt, service helper, and the
# POST /programs/suggest-isced route) was removed with the intake trim —
# isced_code is now hand-typed. Only the taxonomy itself and the validator
# that guards the input boundary remain under test here.


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
    with pytest.raises(ValidationError, match="ISCED"):
        ProgramCreateRequest(**kwargs)


def test_program_metadata_accepts_isced_code_not_in_taxonomy() -> None:
    """Simulates a row whose isced_code was valid at write time but the
    taxonomy has since dropped/renamed that code — must still deserialize."""
    kwargs = _valid_program_kwargs()
    kwargs["isced_code"] = "9999"  # not in taxonomy
    meta = ProgramMetadata(program_id="cs-legacy", **kwargs)
    assert meta.isced_code == "9999"


def test_program_create_request_still_rejects_isced_code_not_in_taxonomy() -> None:
    """Confirm the override on ProgramMetadata did NOT weaken the input boundary."""
    kwargs = _valid_program_kwargs()
    kwargs["isced_code"] = "9999"
    with pytest.raises(ValidationError):
        ProgramCreateRequest(**kwargs)
