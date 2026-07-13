from __future__ import annotations

from curriculum_agent.stages.skill_extraction import _compute_demand_score


def _classify(**kw: str) -> dict[str, str]:
    return dict(kw)


def test_want_evidence_contributes_zero_weight():
    cls = _classify(e1="need", e2="requirement", e3="want")
    score_with_want, _, _ = _compute_demand_score(["e1", "e2", "e3"], {"employer": 3}, 2, cls)
    score_without, _, _ = _compute_demand_score(["e1", "e2"], {"employer": 2}, 2, cls)
    assert score_with_want == score_without  # e3 (want) adds nothing


def test_majority_want_cluster_is_optional():
    cls = _classify(e1="want", e2="want", e3="need")
    _, is_optional, coverage = _compute_demand_score(["e1", "e2", "e3"], {"employer": 3}, 1, cls)
    assert is_optional is True
    assert coverage == {"want": 2, "need": 1}


def test_requirement_and_need_cluster_not_optional():
    cls = _classify(e1="requirement", e2="need")
    coverage_by_stakeholder = {"employer": 1, "alumni": 1}
    score, is_optional, coverage = _compute_demand_score(
        ["e1", "e2"], coverage_by_stakeholder, 2, cls
    )
    assert is_optional is False
    assert score > 0
    assert coverage == {"requirement": 1, "need": 1}


def test_unclassified_treated_as_need():
    cls = _classify(e1="unclassified")
    score, is_optional, _ = _compute_demand_score(["e1"], {"employer": 1}, 1, cls)
    assert is_optional is False
    assert score > 0
