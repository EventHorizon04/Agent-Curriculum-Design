from __future__ import annotations

from curriculum_agent.models import SMARTCheck


def test_smart_passed_when_all_true() -> None:
    check = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
    assert check.passed is True


def test_smart_fails_when_any_false() -> None:
    for field in ("specific", "measurable", "achievable", "relevant", "timely"):
        kwargs = {f: True for f in ("specific", "measurable", "achievable", "relevant", "timely")}
        kwargs[field] = False
        check = SMARTCheck(**kwargs)
        assert check.passed is False, f"Expected False when {field}=False"
