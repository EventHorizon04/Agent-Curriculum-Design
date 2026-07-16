# tests/unit/test_isced.py
from __future__ import annotations

from curriculum_agent.data.isced import (
    BROAD_FIELDS,
    DETAILED_FIELDS,
    NARROW_FIELDS,
    all_detailed_fields,
    get_detailed_field,
)

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
