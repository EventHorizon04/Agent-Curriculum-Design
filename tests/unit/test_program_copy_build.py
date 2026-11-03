"""build_copy: clone a program's rows under fresh ids, rewiring every reference.

evidence_id, skill_id and need_id are single-column global primary keys, so a
copy cannot reuse them. One old->new map covers all three, and every value in
every column — JSONB included — that exactly equals an old id is rewritten.
plo_id is kept: a PLO's identity is (program_id, plo_id).
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime

from curriculum_agent.data.orm import (
    EvidenceTable,
    NeedTable,
    PLOReviewTable,
    PLOTable,
    ProgramTable,
    SkillTable,
)
from curriculum_agent.data.program_copy import ProgramRows, build_copy, remap_ids
from curriculum_agent.data.repositories import _row_to_dict
from curriculum_agent.models import PLO
from curriculum_agent.stages.plo_review_facts import plo_fingerprint

NOW = datetime(2026, 10, 6, 12, 0, 0)


def _ids() -> itertools.count[int]:
    return itertools.count(1)


def _new_uuid_factory():  # noqa: ANN202
    counter = _ids()
    return lambda: f"new-{next(counter)}"


def test_remap_ids_rewrites_exact_matches_at_any_depth() -> None:
    id_map = {"a": "A", "b": "B"}
    value = {"x": ["a", {"y": "b", "z": "ab"}], "a": 1, "n": None, "f": 0.5, "t": True}
    assert remap_ids(value, id_map) == {
        "x": ["A", {"y": "B", "z": "ab"}],
        "A": 1,
        "n": None,
        "f": 0.5,
        "t": True,
    }


def test_remap_ids_leaves_free_text_containing_an_id_alone() -> None:
    assert remap_ids("ดู a ประกอบ", {"a": "A"}) == "ดู a ประกอบ"


def _source() -> ProgramRows:
    program = ProgramTable(
        program_id="program-2",
        name_th="",
        name_en="",
        field="การท่องเที่ยว",
        degree_level="bachelor",
        duration_years=4,
        faculty="คณะ",
        university="มหาวิทยาลัย",
        scope_th="",
        program_goals_th=[],
        program_objectives_th=[],
        created_at=datetime(2026, 9, 1),
        copied_from=None,
    )
    evidence = [
        EvidenceTable(
            evidence_id="ev-1",
            program_id="program-2",
            stakeholder_type="employer",
            source_name="โรงแรม",
            raw_text_th="ต้องการพนักงานที่สื่อสารภาษาอังกฤษได้",
            collected_at=datetime(2026, 9, 1),
            classification="general",
            extra_metadata={},
        )
    ]
    skills = [
        SkillTable(
            skill_id="sk-1",
            program_id="program-2",
            skill_name_th="การสื่อสารภาษาอังกฤษ",
            ksec_category="S",
            bloom_level="apply",
            evidence_span_th="สื่อสารภาษาอังกฤษได้",
            source_evidence_id="ev-1",
            source_stakeholder_type="employer",
            classification="want",
            is_field_relevant=True,
            is_graduate_capability=True,
            extraction_method="llm",
            confidence=0.9,
            importance_score=0.5,
        )
    ]
    needs = [
        NeedTable(
            need_id="nd-1",
            program_id="program-2",
            statement_th="ต้องการบัณฑิตที่สื่อสารภาษาอังกฤษกับนักท่องเที่ยวได้",
            rationale_th="ทุกทักษะในกลุ่มเป็นการสื่อสารกับลูกค้า",
            ksec_categories=["S"],
            bloom_level="apply",
            member_skill_ids=["sk-1"],
            source_evidence_ids=["ev-1"],
            stakeholder_coverage={"employer": 1},
            source_stakeholder_types=["employer"],
            freq=1,
            demand_score=0.5,
            is_optional=False,
            classification_coverage={"want": 1},
            in_field_skill_count=1,
            graduate_capability_skill_count=1,
        )
    ]
    plos = [
        PLOTable(
            plo_id="PLO1",
            program_id="program-2",
            statement_th="สื่อสารภาษาอังกฤษกับนักท่องเที่ยวในงานบริการได้",
            bloom_level="apply",
            action_verb_th="สื่อสาร",
            # SmartFinding has no id-valued field (criterion/severity/note_th
            # only), so the exact-match id rides in note_th and the free-text
            # case rides in SMARTCheck.notes_th, which SMARTCheck keeps
            # verbatim. "R_needs" is a soft code (not in HARD_CODES), matching
            # severity="soft" per SmartFinding.check_severity_matches_the_criterion.
            smart_check={
                "specific": True,
                "measurable": True,
                "achievable": True,
                "relevant": True,
                "timely": True,
                "notes_th": "ดู nd-1 ประกอบ",
                "findings": [{"criterion": "R_needs", "severity": "soft", "note_th": "nd-1"}],
            },
            source_need_ids=["nd-1"],
            source_evidence_ids=["ev-1"],
            rationale_th="เหตุผล",
            version=1,
            smart_retry_count=0,
            smart_escalated=False,
            soft_flags=["R_needs"],
            smart_validated_by="agent",
            is_optional=False,
        )
    ]
    return ProgramRows(
        program=program, evidence=evidence, skills=skills, needs=needs, plos=plos, review=None
    )


def _with_review(src: ProgramRows, *, fingerprint: str) -> ProgramRows:
    from dataclasses import replace

    review = PLOReviewTable(
        program_id="program-2",
        plo_fingerprint=fingerprint,
        model="z-ai/glm-5.3-flash",
        created_at=datetime(2026, 10, 5),
        review={"redundancies": [], "ksec": [{"plo_id": "PLO1"}], "bloom": [], "summary_th": "ok"},
    )
    return replace(src, review=review)


def _fingerprint(rows: list[PLOTable], need_rows: list[NeedTable]) -> str:
    return plo_fingerprint(
        [PLO.model_validate(_row_to_dict(r)) for r in rows],
        {r.need_id: r.demand_score for r in need_rows},
    )


def _dump(rows: ProgramRows) -> str:
    every = [rows.program, *rows.evidence, *rows.skills, *rows.needs, *rows.plos]
    if rows.review is not None:
        every.append(rows.review)
    return json.dumps([_row_to_dict(r) for r in every], default=str, ensure_ascii=False)


def test_every_row_moves_to_the_new_program_with_its_counts() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert copy.program.program_id == "program-2-run-1"
    assert copy.program.copied_from == "program-2"
    assert copy.program.created_at == NOW
    for row in [*copy.evidence, *copy.skills, *copy.needs, *copy.plos]:
        assert row.program_id == "program-2-run-1"
    assert (len(copy.evidence), len(copy.skills), len(copy.needs), len(copy.plos)) == (1, 1, 1, 1)


def test_no_old_id_survives_anywhere_in_the_copy() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    text = _dump(copy)
    for old in ("ev-1", "sk-1", "nd-1"):
        assert f'"{old}"' not in text


def test_every_reference_resolves_inside_the_copy() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    evidence_ids = {e.evidence_id for e in copy.evidence}
    skill_ids = {s.skill_id for s in copy.skills}
    need_ids = {n.need_id for n in copy.needs}
    assert {s.source_evidence_id for s in copy.skills} <= evidence_ids
    for n in copy.needs:
        assert set(n.member_skill_ids) <= skill_ids
        assert set(n.source_evidence_ids) <= evidence_ids
    for p in copy.plos:
        assert set(p.source_need_ids) <= need_ids
        assert set(p.source_evidence_ids) <= evidence_ids
        assert p.smart_check["findings"][0]["note_th"] in need_ids
        assert p.smart_check["notes_th"] == "ดู nd-1 ประกอบ", "free text is left alone"


def test_plo_ids_are_kept() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert [p.plo_id for p in copy.plos] == ["PLO1"]


def test_the_source_rows_are_not_mutated() -> None:
    src = _source()
    before = _dump(src)
    build_copy(src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert _dump(src) == before


def test_a_current_review_stays_current_in_the_copy() -> None:
    src = _source()
    src = _with_review(src, fingerprint=_fingerprint(src.plos, src.needs))
    copy = build_copy(src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert copy.review is not None
    assert copy.review.program_id == "program-2-run-1"
    assert copy.review.plo_fingerprint == _fingerprint(copy.plos, copy.needs)


def _active_fingerprint(rows: list[PLOTable], need_rows: list[NeedTable]) -> str:
    """What plo_review hashes: the PLOs and the *active* Needs only."""
    active = [n for n in need_rows if n.merged_into is None and n.excluded_at is None]
    return _fingerprint(rows, active)


def test_a_current_review_stays_current_with_inactive_needs() -> None:
    """The review is fingerprinted over active Needs, so the copy has to be too:
    counting a merged-away or excluded Need made every such review read stale."""
    from dataclasses import replace

    src = _source()
    base = _row_to_dict(src.needs[0])
    merged_away = NeedTable(**{**base, "need_id": "nd-2", "merged_into": "nd-1"})
    excluded = NeedTable(**{**base, "need_id": "nd-3", "excluded_at": datetime(2026, 10, 1)})
    src = replace(src, needs=[*src.needs, merged_away, excluded])
    src = _with_review(src, fingerprint=_active_fingerprint(src.plos, src.needs))

    copy = build_copy(src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())

    assert copy.review is not None
    assert len(copy.needs) == 3
    assert copy.review.plo_fingerprint == _active_fingerprint(copy.plos, copy.needs)


def test_a_stale_review_stays_stale_in_the_copy() -> None:
    src = _with_review(_source(), fingerprint="0" * 64)
    copy = build_copy(src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert copy.review is not None
    assert copy.review.plo_fingerprint != _fingerprint(copy.plos, copy.needs)


def test_no_review_means_no_review() -> None:
    copy = build_copy(_source(), "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())
    assert copy.review is None


def test_plain_columns_are_not_remapped_by_a_coincidental_id_match() -> None:
    """evidence_id is client-supplied with no format check (StakeholderEvidence.
    evidence_id: str), so an id like "employer" can equal another column's
    plain value. Only the named reference columns and JSONB columns are
    remapped; stakeholder_type and source_stakeholder_type are plain String
    columns and must survive untouched even when an id happens to match them.
    """
    program = ProgramTable(
        program_id="program-2",
        name_th="",
        name_en="",
        field="การท่องเที่ยว",
        degree_level="bachelor",
        duration_years=4,
        faculty="คณะ",
        university="มหาวิทยาลัย",
        scope_th="",
        program_goals_th=[],
        program_objectives_th=[],
        created_at=datetime(2026, 9, 1),
        copied_from=None,
    )
    evidence = [
        EvidenceTable(
            evidence_id="employer",
            program_id="program-2",
            stakeholder_type="employer",
            source_name="โรงแรม",
            raw_text_th="ต้องการพนักงานที่สื่อสารภาษาอังกฤษได้",
            collected_at=datetime(2026, 9, 1),
            classification="general",
            extra_metadata={},
        )
    ]
    skills = [
        SkillTable(
            skill_id="sk-1",
            program_id="program-2",
            skill_name_th="การสื่อสารภาษาอังกฤษ",
            ksec_category="S",
            bloom_level="apply",
            evidence_span_th="สื่อสารภาษาอังกฤษได้",
            source_evidence_id="employer",
            source_stakeholder_type="employer",
            classification="want",
            is_field_relevant=True,
            is_graduate_capability=True,
            extraction_method="llm",
            confidence=0.9,
            importance_score=0.5,
        )
    ]
    src = ProgramRows(
        program=program, evidence=evidence, skills=skills, needs=[], plos=[], review=None
    )
    copy = build_copy(src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())

    new_evidence_id = copy.evidence[0].evidence_id
    assert new_evidence_id != "employer"
    # Plain String columns: left verbatim even though they equal the old id.
    assert copy.evidence[0].stakeholder_type == "employer"
    assert copy.skills[0].source_stakeholder_type == "employer"
    # The reference column: rewritten to the new evidence id.
    assert copy.skills[0].source_evidence_id == new_evidence_id


def _need_row(need_id: str, statement: str, **extra: object) -> NeedTable:
    return NeedTable(
        need_id=need_id,
        program_id="program-2",
        statement_th=statement,
        rationale_th="ทุกทักษะในกลุ่มเป็นการสื่อสารกับลูกค้า",
        ksec_categories=["S"],
        bloom_level="apply",
        member_skill_ids=["sk-1"],
        source_evidence_ids=["ev-1"],
        stakeholder_coverage={"employer": 1},
        source_stakeholder_types=["employer"],
        freq=1,
        demand_score=0.5,
        is_optional=False,
        classification_coverage={"want": 1},
        in_field_skill_count=1,
        graduate_capability_skill_count=1,
        **extra,
    )


def test_a_copied_merge_points_at_the_copys_own_merged_need() -> None:
    from dataclasses import replace

    src = replace(
        _source(),
        needs=[
            _need_row("o-1", "ต้องการบัณฑิตที่สื่อสารภาษาอังกฤษได้ ข้อ v1", merged_into="m-1"),
            _need_row("o-2", "ต้องการบัณฑิตที่สื่อสารภาษาอังกฤษได้ ข้อ v2", merged_into="m-1"),
            _need_row("m-1", "ต้องการบัณฑิตที่สื่อสารภาษาอังกฤษได้ ข้อ vM", merged_from=["o-1", "o-2"]),
        ],
        plos=[],
    )

    copy = build_copy(src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory())

    by_statement = {n.statement_th.rsplit(" ", 1)[-1]: n for n in copy.needs}
    first, second, merged = by_statement["v1"], by_statement["v2"], by_statement["vM"]
    assert {first.need_id, second.need_id, merged.need_id}.isdisjoint({"o-1", "o-2", "m-1"})
    assert first.merged_into == merged.need_id
    assert second.merged_into == merged.need_id
    assert merged.merged_into is None
    assert merged.merged_from == [first.need_id, second.need_id]


def test_build_copy_evidence_only() -> None:
    src = _with_review(_source(), fingerprint="0" * 64)
    copy = build_copy(
        src, "program-2-run-1", now=NOW, new_uuid=_new_uuid_factory(), mode="evidence_only"
    )
    assert copy.program.program_id == "program-2-run-1"
    assert copy.program.copied_from == "program-2"
    assert len(copy.evidence) == len(src.evidence) == 1
    assert {e.evidence_id for e in copy.evidence}.isdisjoint({e.evidence_id for e in src.evidence})
    assert all(e.program_id == "program-2-run-1" for e in copy.evidence)
    assert copy.skills == []
    assert copy.needs == []
    assert copy.plos == []
    assert copy.skill_groups == []
    assert copy.review is None
