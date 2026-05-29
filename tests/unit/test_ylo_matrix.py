from __future__ import annotations

import pytest

from curriculum_agent.models import (
    Domain,
    PLO,
    BloomLevel,
    KrathwohlLevel,
    SMARTCheck,
    YLO,
    YLOMatrix,
)

SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def make_plo(plo_id: str = "PLO1", domain: Domain = Domain.COGNITIVE) -> PLO:
    bloom = BloomLevel.CREATE if domain != Domain.AFFECTIVE else None
    krath = KrathwohlLevel.VALUING if domain == Domain.AFFECTIVE else None
    return PLO(
        plo_id=plo_id,
        program_id="cs-test",
        statement_th=f"ออกแบบระบบ {plo_id} ได้",
        domain=domain,
        bloom_level=bloom,
        krathwohl_level=krath,
        is_subject_specific=True,
        action_verb_th="ออกแบบ",
        smart_check=SMART_PASS,
        source_cluster_ids=["C1"],
        source_evidence_ids=["E1"],
        rationale_th="ทดสอบ",
    )


def make_ylo(ylo_id: str, parent: str, year: int, bloom: BloomLevel) -> YLO:
    return YLO(
        ylo_id=ylo_id,
        program_id="cs-test",
        parent_plo_id=parent,
        year=year,
        statement_th=f"วิเคราะห์ได้ในปีที่ {year}",
        bloom_level=bloom,
        action_verb_th="วิเคราะห์",
        smart_check=SMART_PASS,
        rationale_th="ทดสอบ",
    )


def test_valid_matrix_no_issues() -> None:
    plo = make_plo()
    ylos = [
        make_ylo("YLO1.1", "PLO1", 1, BloomLevel.APPLY),
        make_ylo("YLO1.2", "PLO1", 2, BloomLevel.ANALYZE),
        make_ylo("YLO1.3", "PLO1", 3, BloomLevel.EVALUATE),
        make_ylo("YLO1.4", "PLO1", 4, BloomLevel.CREATE),
    ]
    matrix = YLOMatrix(program_id="cs-test", plos=[plo], ylos=ylos)
    assert matrix.validate_coverage() == []


def test_bloom_decrease_caught() -> None:
    plo = make_plo()
    ylos = [
        make_ylo("YLO1.1", "PLO1", 1, BloomLevel.ANALYZE),
        make_ylo("YLO1.2", "PLO1", 2, BloomLevel.APPLY),  # decrease
    ]
    matrix = YLOMatrix(program_id="cs-test", plos=[plo], ylos=ylos)
    issues = matrix.validate_coverage()
    assert any("Bloom decreases" in i for i in issues)


def test_plo_with_no_ylo_caught() -> None:
    plo = make_plo()
    matrix = YLOMatrix(program_id="cs-test", plos=[plo], ylos=[])
    issues = matrix.validate_coverage()
    assert any("no YLO" in i for i in issues)


def test_ylo_referencing_unknown_plo_caught() -> None:
    plo = make_plo()
    orphan_ylo = make_ylo("YLO9.1", "PLO_UNKNOWN", 1, BloomLevel.APPLY)
    matrix = YLOMatrix(program_id="cs-test", plos=[plo], ylos=[orphan_ylo])
    issues = matrix.validate_coverage()
    assert any("unknown PLO" in i for i in issues)


def test_psychomotor_bloom_decrease_caught() -> None:
    """Psychomotor PLOs must also have monotonic Bloom levels."""
    plo = make_plo("PLO-P1", domain=Domain.PSYCHOMOTOR)
    ylos = [
        make_ylo("YLO-P1.1", "PLO-P1", 1, BloomLevel.CREATE),
        make_ylo("YLO-P1.2", "PLO-P1", 2, BloomLevel.APPLY),  # decrease
    ]
    matrix = YLOMatrix(program_id="cs-test", plos=[plo], ylos=ylos)
    issues = matrix.validate_coverage()
    assert any("Bloom decreases" in i for i in issues), f"Expected Bloom decrease issue, got: {issues}"


def test_bloom_decrease_error_message_shows_correct_years_with_none_bloom() -> None:
    """Error message must reference years of the non-None bloom_level YLOs, not list indices."""
    plo = make_plo()
    # year 1: bloom=None (skipped in filter), year 2: ANALYZE, year 3: APPLY (decrease)
    ylo_none = YLO(
        ylo_id="YLO1.0",
        program_id="cs-test",
        parent_plo_id="PLO1",
        year=1,
        statement_th="วิเคราะห์ได้",
        bloom_level=None,
        action_verb_th="วิเคราะห์",
        smart_check=SMART_PASS,
        rationale_th="test",
    )
    ylo_analyze = make_ylo("YLO1.1", "PLO1", 2, BloomLevel.ANALYZE)
    ylo_apply = make_ylo("YLO1.2", "PLO1", 3, BloomLevel.APPLY)  # decrease

    matrix = YLOMatrix(program_id="cs-test", plos=[plo], ylos=[ylo_none, ylo_analyze, ylo_apply])
    issues = matrix.validate_coverage()
    assert any("year 2" in i and "year 3" in i for i in issues), (
        f"Expected issue mentioning year 2 and year 3, got: {issues}"
    )
