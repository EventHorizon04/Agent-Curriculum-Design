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


def test_ylo_smart_pass_constant_removed() -> None:
    """_SMART_PASS constant must not exist in ylo_derivation module."""
    from curriculum_agent.stages import ylo_derivation
    assert not hasattr(ylo_derivation, "_SMART_PASS"), (
        "_SMART_PASS constant must be removed; each YLO must call complete_light() for SMART validation"
    )
