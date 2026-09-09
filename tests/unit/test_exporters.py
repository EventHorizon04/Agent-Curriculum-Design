from __future__ import annotations

import io

import pytest
from openpyxl import load_workbook

from curriculum_agent.exporters.excel_matrix import MATRIX_HEADERS, export_matrix_xlsx
from curriculum_agent.models import PLO, BloomLevel, KSECCategory, Need, SMARTCheck


def _need(need_id: str, ksec: KSECCategory) -> Need:
    return Need(
        need_id=need_id,
        program_id="cs-test",
        statement_th=f"ตลาดต้องการ {need_id}",
        ksec_category=ksec,
        bloom_level=BloomLevel.ANALYZE,
        member_skill_ids=[f"S-{need_id}"],
        source_evidence_ids=[f"E-{need_id}"],
        freq=1,
        demand_score=0.7,
    )


def _plo(
    plo_id: str,
    need_ids: list[str],
    *,
    optional: bool = False,
    escalated: bool = False,
    soft_flags: list[str] | None = None,
) -> PLO:
    return PLO(
        plo_id=plo_id,
        program_id="cs-test",
        statement_th=f"วิเคราะห์งาน {plo_id} เพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=SMARTCheck(
            specific=True, measurable=True, achievable=True, relevant=True, timely=True
        ),
        source_need_ids=need_ids,
        source_evidence_ids=[f"E-{n}" for n in need_ids],
        rationale_th="ตรงกับความต้องการของตลาด",
        is_optional=optional,
        smart_escalated=escalated,
        soft_flags=soft_flags or [],
    )


def _rows(payload: bytes) -> list[list[object]]:
    sheet = load_workbook(io.BytesIO(payload)).active
    assert sheet is not None
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def test_workbook_opens_and_carries_the_declared_headers() -> None:
    payload = export_matrix_xlsx([_plo("PLO1", ["N1"])], {"N1": _need("N1", KSECCategory.S)})

    rows = _rows(payload)
    assert rows[0] == list(MATRIX_HEADERS)


def test_one_row_per_plo_in_the_given_order() -> None:
    plos = [_plo("PLO1", ["N1"]), _plo("PLO2", ["N1"]), _plo("OPT1", ["N1"], optional=True)]
    rows = _rows(export_matrix_xlsx(plos, {"N1": _need("N1", KSECCategory.S)}))

    assert [row[0] for row in rows[1:]] == ["PLO1", "PLO2", "OPT1"]


def test_ksec_column_resolves_through_the_source_needs() -> None:
    """A PLO carries no KSEC tag of its own — the competency domain is the tag of
    the Needs behind it, which is why the exporter needs needs_by_id."""
    needs = {"N1": _need("N1", KSECCategory.K), "N2": _need("N2", KSECCategory.EC)}
    rows = _rows(export_matrix_xlsx([_plo("PLO1", ["N1", "N2"])], needs))

    ksec_cell = rows[1][MATRIX_HEADERS.index("หมวดสมรรถนะ")]
    assert ksec_cell == "K, EC"


def test_duplicate_ksec_tags_collapse_to_one() -> None:
    needs = {"N1": _need("N1", KSECCategory.S), "N2": _need("N2", KSECCategory.S)}
    rows = _rows(export_matrix_xlsx([_plo("PLO1", ["N1", "N2"])], needs))

    assert rows[1][MATRIX_HEADERS.index("หมวดสมรรถนะ")] == "S"


def test_an_unresolvable_need_id_leaves_the_cell_empty_rather_than_raising() -> None:
    """The report stage warns about unresolved ids; the export must still produce
    a file so the designer can see which outcome lost its trail."""
    rows = _rows(export_matrix_xlsx([_plo("PLO1", ["GONE"])], {}))

    # xlsx has no empty-string cell — an unset cell reads back as None.
    assert rows[1][MATRIX_HEADERS.index("หมวดสมรรถนะ")] in (None, "")
    assert rows[1][0] == "PLO1", "the row itself must still be exported"


def test_needs_by_id_is_optional() -> None:
    rows = _rows(export_matrix_xlsx([_plo("PLO1", ["N1"])]))

    assert rows[1][0] == "PLO1"
    assert rows[1][MATRIX_HEADERS.index("หมวดสมรรถนะ")] in (None, "")


def test_optional_and_core_outcomes_are_distinguishable() -> None:
    plos = [_plo("PLO1", ["N1"]), _plo("OPT1", ["N1"], optional=True)]
    rows = _rows(export_matrix_xlsx(plos, {"N1": _need("N1", KSECCategory.S)}))

    kind = MATRIX_HEADERS.index("ประเภท")
    assert rows[1][kind] == "หลัก"
    assert rows[2][kind] == "เสริม"


def test_escalated_outcome_is_flagged_for_repair() -> None:
    """A PLO that failed the SMART gate must stay visible in the export, not be
    silently dropped — repairing it is the designer's job."""
    plos = [_plo("PLO1", ["N1"]), _plo("PLO2", ["N1"], escalated=True)]
    rows = _rows(export_matrix_xlsx(plos, {"N1": _need("N1", KSECCategory.S)}))

    status = MATRIX_HEADERS.index("สถานะ")
    assert rows[1][status] == "ผ่าน"
    assert rows[2][status] == "ต้องแก้ไข"


def test_soft_flags_are_joined_into_one_cell() -> None:
    plo = _plo("PLO1", ["N1"], soft_flags=["วัตถุประสงค์กว้างเกินไป", "ไม่ตรงวิสัยทัศน์"])
    rows = _rows(export_matrix_xlsx([plo], {"N1": _need("N1", KSECCategory.S)}))

    cell = rows[1][MATRIX_HEADERS.index("ข้อสังเกต")]
    assert cell == "วัตถุประสงค์กว้างเกินไป; ไม่ตรงวิสัยทัศน์"


def test_bloom_level_is_written_as_its_value() -> None:
    rows = _rows(export_matrix_xlsx([_plo("PLO1", ["N1"])], {"N1": _need("N1", KSECCategory.S)}))

    assert rows[1][MATRIX_HEADERS.index("ระดับ Bloom")] == "analyze"


def test_empty_plo_list_is_rejected() -> None:
    """An empty workbook is worse than an error: it looks like a successful export
    of a program that has no outcomes."""
    with pytest.raises(ValueError, match="ไม่มี PLO"):
        export_matrix_xlsx([])


def _column(payload: bytes, header: str) -> list[object]:
    """One column by name. MATRIX_HEADERS exists so a reordering cannot silently
    shift what a caller reads, and that applies to these tests too."""
    rows = _rows(payload)
    index = list(rows[0]).index(header)
    return [row[index] for row in rows[1:]]


def test_status_says_not_fully_checked_rather_than_passed() -> None:
    """ "ผ่าน" / "ต้องแก้ไข" was a false dichotomy. A hand-edited statement
    nothing has re-judged, and a verdict the pure checks reached alone because
    the validator could not run, are neither — and this file is what leaves the
    tool, so it must not overstate what was checked."""
    stale = _plo("PLO1", ["N1"]).model_copy(update={"smart_validated_by": "stale"})
    code_only = _plo("PLO2", ["N1"]).model_copy(update={"smart_validated_by": "code_only"})
    judged = _plo("PLO3", ["N1"]).model_copy(update={"smart_validated_by": "agent"})

    statuses = _column(export_matrix_xlsx([stale, code_only, judged]), "สถานะ")

    assert statuses == ["ยังไม่ได้ตรวจครบ", "ยังไม่ได้ตรวจครบ", "ผ่าน"]


def test_findings_are_rendered_in_thai_not_as_raw_codes() -> None:
    """The codes used to land in a Thai workbook a designer sends to MHESI."""
    from curriculum_agent.models import SmartFinding
    from curriculum_agent.smart_vocabulary import SmartFindingCode

    plo = _plo("PLO1", ["N1"])
    flagged = plo.model_copy(
        update={
            "soft_flags": ["A_level"],
            "smart_check": plo.smart_check.model_copy(
                update={
                    "achievable": False,
                    "findings": [
                        SmartFinding(
                            criterion=SmartFindingCode.A_LEVEL,
                            severity="soft",
                            note_th="ระดับสูงเกินปริญญาตรี",
                        )
                    ],
                }
            ),
        }
    )

    cell = _column(export_matrix_xlsx([flagged]), "ข้อสังเกต")[0]

    assert isinstance(cell, str)
    assert "A_level" not in cell
    assert "ระดับ Bloom" in cell
    assert "ระดับสูงเกินปริญญาตรี" in cell


def test_a_legacy_row_still_renders_its_flat_flags() -> None:
    """Rows written before findings existed carry only the code list."""
    plo = _plo("PLO1", ["N1"], soft_flags=["A_level", "R_alignment"])

    cell = _column(export_matrix_xlsx([plo]), "ข้อสังเกต")[0]

    assert isinstance(cell, str)
    assert "ระดับ Bloom" in cell
    # A code this build no longer knows falls through rather than vanishing.
    assert "R_alignment" in cell


def test_the_diagnosis_reaches_the_workbook() -> None:
    """The whole point of the validator is that its diagnosis is actionable, and
    the workbook is what a designer works from."""
    diagnosis = "กรรมของกริยากว้างเกินไป ควรระบุมาตรฐานที่อ้างอิง"
    plo = _plo("PLO1", ["N1"]).model_copy(update={"smart_diagnosis_th": diagnosis})

    assert _column(export_matrix_xlsx([plo]), "ข้อวินิจฉัย")[0] == diagnosis
