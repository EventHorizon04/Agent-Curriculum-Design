from __future__ import annotations

from datetime import datetime

from curriculum_agent.models import PLO, BloomLevel, KSECCategory, Need, SMARTCheck
from curriculum_agent.stages.plo_review import (
    ReviewAnswer,
    _BloomVerdict,
    _KsecVerdict,
    _Redundancy,
    accept_review,
    current_ksec,
    is_empty,
    is_stale,
    need_demands,
    plo_fingerprint,
)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)
_NOW = datetime(2026, 10, 5, 12, 0, 0)


def _need(nid: str, ksec: KSECCategory) -> Need:
    return Need(
        need_id=nid,
        program_id="p",
        statement_th=f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=[f"S-{nid}"],
        source_evidence_ids=[f"E-{nid}"],
        freq=1,
        demand_score=0.5,
    )


def _plo(pid: str, need_ids: list[str], *, statement: str | None = None) -> PLO:
    return PLO(
        plo_id=pid,
        program_id="p",
        statement_th=statement or f"วิเคราะห์ระบบงาน {pid} เพื่อเสนอแนวทางแก้ปัญหา",
        bloom_level=BloomLevel.APPLY,
        action_verb_th="วิเคราะห์",
        smart_check=_SMART,
        source_need_ids=need_ids,
        source_evidence_ids=["E1"],
        rationale_th="เหตุผล",
    )


NEEDS = {"n1": _need("n1", KSECCategory.S), "n2": _need("n2", KSECCategory.EC)}
DEMANDS = need_demands(NEEDS.values())
PLOS = [_plo("PLO1", ["n1"]), _plo("PLO2", ["n2"]), _plo("PLO3", ["n1", "n2"])]


def _accept(answer: ReviewAnswer):
    return accept_review(
        answer, PLOS, NEEDS, program_id="p", fingerprint="f", model="m", created_at=_NOW
    )


# ------------------------------ current_ksec ------------------------------


def test_current_ksec_expands_ec_and_follows_ksec_order() -> None:
    assert current_ksec(PLOS[1], NEEDS) == ["E", "C"]
    assert current_ksec(PLOS[2], NEEDS) == ["S", "E", "C"]


def test_current_ksec_ignores_an_unknown_need() -> None:
    assert current_ksec(_plo("PLO9", ["gone", "n1"]), NEEDS) == ["S"]


# ------------------------------ fingerprint ------------------------------


def test_fingerprint_ignores_order_and_moves_on_each_field() -> None:
    base = plo_fingerprint(PLOS, DEMANDS)
    assert plo_fingerprint(list(reversed(PLOS)), DEMANDS) == base
    changed = [PLOS[0].model_copy(update={"statement_th": "ออกแบบระบบ"}), *PLOS[1:]]
    assert plo_fingerprint(changed, DEMANDS) != base
    for field, value in [
        ("bloom_level", BloomLevel.CREATE),
        ("action_verb_th", "ออกแบบ"),
        ("is_optional", True),
        ("source_need_ids", ["n2"]),
    ]:
        assert (
            plo_fingerprint([PLOS[0].model_copy(update={field: value}), *PLOS[1:]], DEMANDS) != base
        )


def test_is_stale_compares_fingerprints() -> None:
    review, _ = accept_review(
        ReviewAnswer(summary_th="ดี"),
        PLOS,
        NEEDS,
        program_id="p",
        fingerprint=plo_fingerprint(PLOS, DEMANDS),
        model="m",
        created_at=_NOW,
    )
    assert not is_stale(review, PLOS, DEMANDS)
    assert is_stale(review, PLOS[:2], DEMANDS)


# ------------------------------ redundancy ------------------------------


def test_redundancy_keeps_known_ids_and_drops_short_or_oversized_groups() -> None:
    review, drops = _accept(
        ReviewAnswer(
            redundancies=[
                _Redundancy(plo_ids=["PLO1", "PLO2"], reason_th="ซ้ำ", suggestion_th="รวม"),
                _Redundancy(plo_ids=["PLO1", "PLO99"], reason_th="ซ้ำ"),
                _Redundancy(plo_ids=["PLO1", "PLO2", "PLO3", "PLO1"], reason_th="ซ้ำ"),
                _Redundancy(plo_ids=["PLO2", "PLO1"], reason_th="ซ้ำอีก"),
                _Redundancy(plo_ids=["PLO2", "PLO3"], reason_th="  "),
            ]
        )
    )
    assert [r.plo_ids for r in review.redundancies] == [["PLO1", "PLO2"], ["PLO1", "PLO2", "PLO3"]]
    assert drops["redundancy"] == 3


def test_a_group_naming_more_than_three_distinct_plos_is_dropped() -> None:
    plos = [*PLOS, _plo("PLO4", ["n1"])]
    review, _ = accept_review(
        ReviewAnswer(
            redundancies=[_Redundancy(plo_ids=["PLO1", "PLO2", "PLO3", "PLO4"], reason_th="ซ้ำ")]
        ),
        plos,
        NEEDS,
        program_id="p",
        fingerprint="f",
        model="m",
        created_at=_NOW,
    )
    assert review.redundancies == []


# ------------------------------ KSEC ------------------------------


def test_ksec_current_and_agrees_are_computed_in_code() -> None:
    review, drops = _accept(
        ReviewAnswer(
            ksec=[
                _KsecVerdict(plo_id="PLO1", suggested=["s", "E"], reason_th="มีจริยธรรมด้วย"),
                _KsecVerdict(plo_id="PLO2", suggested=["EC"], reason_th="ตรง"),
                _KsecVerdict(plo_id="PLO2", suggested=["K"], reason_th="ซ้ำ plo_id"),
                _KsecVerdict(plo_id="PLO99", suggested=["K"], reason_th="ไม่มีจริง"),
                _KsecVerdict(plo_id="PLO3", suggested=["X", "Y"], reason_th="ไม่มีหมวดจริง"),
            ]
        )
    )
    by_id = {k.plo_id: k for k in review.ksec}
    assert set(by_id) == {"PLO1", "PLO2"}
    assert by_id["PLO1"].current == ["S"] and by_id["PLO1"].suggested == ["S", "E"]
    assert by_id["PLO1"].agrees is False
    assert by_id["PLO2"].suggested == ["E", "C"] and by_id["PLO2"].agrees is True
    assert drops["ksec"] == 3


def test_ksec_accepts_the_e_bar_c_spelling() -> None:
    review, _ = _accept(
        ReviewAnswer(ksec=[_KsecVerdict(plo_id="PLO2", suggested=["E|C"], reason_th="ตรง")])
    )
    assert review.ksec[0].suggested == ["E", "C"]


# ------------------------------ Bloom ------------------------------


def test_bloom_declared_is_filled_in_code_and_a_bad_level_becomes_none() -> None:
    review, drops = _accept(
        ReviewAnswer(
            bloom=[
                _BloomVerdict(
                    plo_id="PLO1", suggested_level="Analyze", reason_th="กรรมคือการวิเคราะห์"
                ),
                _BloomVerdict(plo_id="PLO2", suggested_level="psychic", reason_th="ระดับสูงเกิน"),
                _BloomVerdict(plo_id="PLO3", suggested_level="apply", reason_th=""),
                _BloomVerdict(plo_id="PLO99", suggested_level="apply", reason_th="ไม่มีจริง"),
            ]
        )
    )
    by_id = {b.plo_id: b for b in review.bloom}
    assert set(by_id) == {"PLO1", "PLO2"}
    assert by_id["PLO1"].declared is BloomLevel.APPLY
    assert by_id["PLO1"].suggested_level is BloomLevel.ANALYZE
    assert by_id["PLO2"].suggested_level is None
    assert drops["bloom"] == 2


# ------------------------------ texts and emptiness ------------------------------


def test_texts_are_stripped_and_an_answer_with_nothing_is_empty() -> None:
    review, _ = _accept(ReviewAnswer(summary_th="  ดีแล้ว  ", bloom_distribution_th=" apply เป็นหลัก "))
    assert review.summary_th == "ดีแล้ว"
    assert review.bloom_distribution_th == "apply เป็นหลัก"
    assert not is_empty(review)
    blank, _ = _accept(ReviewAnswer(summary_th="   "))
    assert is_empty(blank)
