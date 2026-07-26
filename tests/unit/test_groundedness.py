from __future__ import annotations

from curriculum_agent.stages.skill_extraction import is_grounded, normalize_for_match

EVIDENCE = "ผู้สมัครต้อง   วิเคราะห์ข้อมูลขนาดใหญ่\nและนำเสนอผลได้"


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
