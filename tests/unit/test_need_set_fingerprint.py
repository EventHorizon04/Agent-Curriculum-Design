from __future__ import annotations

from curriculum_agent.models import BloomLevel, KSECCategory, Need
from curriculum_agent.stages.plo_review_facts import need_set_fingerprint


def _need(need_id: str, statement: str = "วิเคราะห์ข้อมูลได้", score: float = 0.5) -> Need:
    return Need(
        need_id=need_id,
        program_id="p",
        statement_th=statement,
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=["S1"],
        source_evidence_ids=["E1"],
        freq=1,
        demand_score=score,
    )


def test_order_of_the_input_does_not_matter() -> None:
    a, b = _need("N1"), _need("N2")
    assert need_set_fingerprint([a, b]) == need_set_fingerprint([b, a])


def test_a_changed_statement_changes_it() -> None:
    assert need_set_fingerprint([_need("N1")]) != need_set_fingerprint([_need("N1", "อื่น")])


def test_a_changed_demand_score_changes_it() -> None:
    assert need_set_fingerprint([_need("N1")]) != need_set_fingerprint([_need("N1", score=0.6)])


def test_a_removed_need_changes_it() -> None:
    assert need_set_fingerprint([_need("N1"), _need("N2")]) != need_set_fingerprint([_need("N1")])
