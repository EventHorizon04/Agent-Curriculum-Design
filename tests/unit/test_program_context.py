from __future__ import annotations

from typing import get_args, get_type_hints

import pytest

from curriculum_agent.models import ProgramCreateRequest
from curriculum_agent.prompts.program_context import (
    _DEGREE_LABEL_TH,
    build_program_context_th,
)

# Written independently of _DEGREE_LABEL_TH: asserting against the module's own
# dict would let a mistyped entry pass, since both sides would read the same
# wrong string.
_EXPECTED_DEGREE_TH = {
    "bachelor": "ปริญญาตรี",
    "master": "ปริญญาโท",
    "doctoral": "ปริญญาเอก",
}

_DEGREE_LEVELS = get_args(get_type_hints(ProgramCreateRequest)["degree_level"])


def test_expected_degree_labels_cover_every_level() -> None:
    """Guards the test data itself against the Literal it mirrors."""
    assert set(_EXPECTED_DEGREE_TH) == set(_DEGREE_LEVELS)


def test_degree_label_th_covers_every_level() -> None:
    """The module asserts this at import time; here it is a readable test too."""
    assert set(_DEGREE_LABEL_TH) == set(_DEGREE_LEVELS)


@pytest.mark.parametrize("level", _DEGREE_LEVELS)
def test_context_names_the_field_and_the_degree_in_thai(level: str) -> None:
    context = build_program_context_th({"field": "วิศวกรรมซอฟต์แวร์", "degree_level": level})
    assert context is not None
    assert "วิศวกรรมซอฟต์แวร์" in context
    assert _EXPECTED_DEGREE_TH[level] in context
    # The raw code is what a Thai prompt must not carry through.
    assert level not in context


def test_no_field_means_no_context() -> None:
    """A program without a field gets the pre-context behaviour, not a stub line."""
    assert build_program_context_th({"degree_level": "bachelor"}) is None
    assert build_program_context_th({"field": "   ", "degree_level": "bachelor"}) is None
    assert build_program_context_th({}) is None


def test_unknown_degree_level_still_names_the_field() -> None:
    """A row written before a level was renamed must not lose its field."""
    context = build_program_context_th({"field": "พยาบาลศาสตร์", "degree_level": "postdoc"})
    assert context is not None
    assert "พยาบาลศาสตร์" in context
    assert "postdoc" not in context
