from __future__ import annotations

from curriculum_agent.stages.skill_extraction import (
    _MIN_SPAN_CHARS,
    is_grounded,
    normalize_for_match,
)

EVIDENCE = "ผู้สมัครต้อง   วิเคราะห์ข้อมูลขนาดใหญ่\nและนำเสนอผลได้ เช่น Power BI, Tableau เป็นต้น"


def test_normalize_collapses_whitespace_and_trims():
    assert normalize_for_match("  a \n\t b  ") == "a b"


def test_exact_quote_is_grounded():
    assert is_grounded("และนำเสนอผลได้", EVIDENCE) is True


def test_quote_grounded_despite_differing_whitespace():
    # The model re-spaced the quote; the claim is still traceable.
    assert is_grounded("ผู้สมัครต้อง วิเคราะห์ข้อมูลขนาดใหญ่", EVIDENCE) is True


def test_invented_quote_is_not_grounded():
    assert is_grounded("ต้องมีประสบการณ์ 5 ปี", EVIDENCE) is False


def test_blank_span_is_not_grounded():
    assert is_grounded("   ", EVIDENCE) is False


def test_single_char_that_occurs_is_not_grounded():
    # "ต" genuinely occurs in EVIDENCE (in "ต้อง"), but one character is almost
    # certainly a substring of any real Thai text by chance — it proves nothing.
    assert "ต" in EVIDENCE
    assert is_grounded("ต", EVIDENCE) is False


def test_punctuation_that_occurs_is_not_grounded():
    # A bare comma occurs in EVIDENCE too, for the same reason a single
    # character does — matching it says nothing about a real quote.
    assert "," in EVIDENCE
    assert is_grounded(",", EVIDENCE) is False


def test_span_exactly_at_threshold_is_grounded():
    span = "วิเคราะห์ข้อ"
    assert len(span) == _MIN_SPAN_CHARS
    assert is_grounded(span, EVIDENCE) is True


def test_span_one_below_threshold_is_not_grounded():
    span = "วิเคราะห์ข้อ"[: _MIN_SPAN_CHARS - 1]
    assert len(span) == _MIN_SPAN_CHARS - 1
    assert is_grounded(span, EVIDENCE) is False


def test_genuine_long_quote_still_grounded():
    span = "และนำเสนอผลได้ เช่น Power BI"
    assert len(span) >= _MIN_SPAN_CHARS
    assert is_grounded(span, EVIDENCE) is True


def test_long_fabricated_quote_still_not_grounded():
    span = "ต้องมีประสบการณ์ทำงานอย่างน้อยห้าปีในสายงานนี้"
    assert len(span) >= _MIN_SPAN_CHARS
    assert is_grounded(span, EVIDENCE) is False
