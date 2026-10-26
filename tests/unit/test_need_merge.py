from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import (
    BloomLevel,
    ExtractedSkill,
    KSECCategory,
    Need,
    ProgramMetadata,
    StakeholderType,
)
from curriculum_agent.stages import need_dedup as nd
from curriculum_agent.stages import need_merge as nm
from curriculum_agent.stages.need_combination import NeedStatement
from curriculum_agent.stages.need_dedup import FoldGroup
from curriculum_agent.stages.need_grouping import REVIEW_MARKER_TH
from tests.support.needs import RATIONALE_TH

_METADATA = ProgramMetadata.model_validate(
    {
        "program_id": "test",
        "field": "ภาษาจีน",
        "degree_level": "bachelor",
        "duration_years": 4,
        "faculty": "มนุษยศาสตร์",
        "university": "Test University",
    }
)
_MERGED_SENTENCE = "ต้องการบัณฑิตที่แปลและตรวจสอบเอกสารธุรกิจไทย-จีนโดยใช้ AI ช่วยตรวจคุณภาพ"


def _skill(
    sid: str, name: str, importance: float, *, ksec: KSECCategory = KSECCategory.S, eid: str = ""
) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="test",
        skill_name_th=name,
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=name,
        source_evidence_id=eid or f"E-{sid}",
        source_stakeholder_type=StakeholderType.EMPLOYER,
        classification="need",
        extraction_method="llm",
        confidence=0.9,
        importance_score=importance,
    )


def _need(
    nid: str,
    demand: float,
    *,
    ksec: KSECCategory = KSECCategory.S,
    skills: list[str] | None = None,
    evidence: list[str] | None = None,
    optional: bool = False,
    statement: str | None = None,
    in_scope: bool = True,
) -> Need:
    members = skills or [f"S-{nid}"]
    return Need(
        need_id=nid,
        program_id="test",
        statement_th=statement or f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        ksec_categories=[ksec],
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=members,
        source_evidence_ids=evidence or [f"E-{nid}"],
        freq=len(members),
        demand_score=demand,
        is_optional=optional,
        in_field_skill_count=len(members) if in_scope else 0,
        graduate_capability_skill_count=len(members) if in_scope else 0,
    )


def _fold(*needs: Need, reason: str = "งานเดียวกัน") -> FoldGroup:
    return FoldGroup(needs=tuple(sorted(needs, key=lambda n: -n.demand_score)), reason_th=reason)


def _fillers(count: int = 4) -> list[Need]:
    """Core Needs nothing folds, so a pair fold still leaves the merge floor intact."""
    return [_need(f"F{i}", 0.05 + i / 100) for i in range(count)]


def _corpus(skills: list[ExtractedSkill]) -> dict[str, str]:
    return {s.source_evidence_id: s.source_stakeholder_type.value for s in skills}


class _Sentence:
    """Stands in for the need_combination slot: records messages, answers a fixed sentence."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    async def __call__(
        self, model: type[NeedStatement], messages: list[dict[str, str]], **kw: object
    ) -> NeedStatement:
        self.calls.append(messages)
        return NeedStatement(statement_th=_MERGED_SENTENCE, rationale_th=RATIONALE_TH)


def _patch(
    monkeypatch: pytest.MonkeyPatch, folds: list[FoldGroup], sentence: object | None = None
) -> tuple[AsyncMock, object]:
    dedup = AsyncMock(return_value=folds)
    chosen = sentence or _Sentence()
    monkeypatch.setattr(nm, "find_duplicate_groups", dedup)
    monkeypatch.setattr(nm, "complete_need_combination", chosen)
    return dedup, chosen


async def _merge(needs: list[Need], skills: list[ExtractedSkill]) -> list[Need]:
    return await nm.merge_duplicates("test", needs, skills, _METADATA, _corpus(skills))


# --------------------------- the merged Need ---------------------------


async def test_merged_need_trail_is_union_of_originals(monkeypatch: pytest.MonkeyPatch) -> None:
    a = _need("A", 0.9, skills=["s1", "s2"], evidence=["E1", "E2"])
    b = _need("B", 0.5, skills=["s2", "s3"], evidence=["E2", "E3"])
    skills = [_skill(f"s{i}", f"ทักษะ{i}", 0.5, eid=f"E{i}") for i in (1, 2, 3)]
    _patch(monkeypatch, [_fold(a, b)])

    stored = await _merge([a, b, *_fillers()], skills)

    (merged,) = [n for n in stored if n.merged_from]
    assert sorted(merged.member_skill_ids) == ["s1", "s2", "s3"]
    assert sorted(merged.source_evidence_ids) == ["E1", "E2", "E3"]
    assert merged.freq == 3
    assert merged.merged_from == ["A", "B"]
    assert merged.merge_reason_th == "งานเดียวกัน"
    assert merged.statement_th == _MERGED_SENTENCE
    assert merged.need_id not in {"A", "B"}


async def test_merged_need_tags_are_union_in_ksec_order(monkeypatch: pytest.MonkeyPatch) -> None:
    a = _need("A", 0.9, ksec=KSECCategory.S, skills=["s1"])
    b = _need("B", 0.5, ksec=KSECCategory.K, skills=["s2"])
    skills = [_skill("s1", "ทักษะหนึ่ง", 0.5), _skill("s2", "ความรู้สอง", 0.5, ksec=KSECCategory.K)]
    _patch(monkeypatch, [_fold(a, b)])

    stored = await _merge([a, b, *_fillers()], skills)

    (merged,) = [n for n in stored if n.merged_from]
    assert merged.ksec_categories == [KSECCategory.K, KSECCategory.S]


async def test_top_skills_capped_at_seven_by_importance(monkeypatch: pytest.MonkeyPatch) -> None:
    skills = [_skill(f"s{i}", f"ทักษะ{i:02d}", i / 20, eid=f"E{i}") for i in range(1, 11)]
    a = _need("A", 0.9, skills=[f"s{i}" for i in range(1, 6)])
    b = _need("B", 0.5, skills=[f"s{i}" for i in range(6, 11)])
    _, sentence = _patch(monkeypatch, [_fold(a, b)])

    stored = await _merge([a, b, *_fillers()], skills)

    (merged,) = [n for n in stored if n.merged_from]
    assert merged.top_skill_ids == [f"s{i}" for i in range(10, 3, -1)]
    assert nm.TOP_SKILL_CAP == 7
    assert len(merged.member_skill_ids) == 10, "the trail keeps every member, not just the top"
    user = sentence.calls[0][-1]["content"]  # type: ignore[attr-defined]
    assert "ทักษะ10" in user and "ทักษะ04" in user and "ทักษะ03" not in user


def test_rank_top_skills_breaks_ties_by_name() -> None:
    skills = [_skill("s1", "ข", 0.5), _skill("s2", "ก", 0.5), _skill("s3", "ค", 0.9)]

    assert [s.skill_id for s in nm.rank_top_skills(skills)] == ["s3", "s2", "s1"]


def test_duplicate_skill_name_keeps_higher_score() -> None:
    skills = [_skill("lo", "วิเคราะห์ข้อมูล", 0.3), _skill("hi", " วิเคราะห์ข้อมูล ", 0.8)]

    ranked = nm.rank_top_skills(skills)

    assert [s.skill_id for s in ranked] == ["hi"]


async def test_originals_marked_merged_into_not_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = _need("A", 0.9, skills=["s1"]), _need("B", 0.5, skills=["s2"])
    fillers = _fillers()
    skills = [_skill("s1", "ทักษะหนึ่ง", 0.5), _skill("s2", "ทักษะสอง", 0.5)]
    _patch(monkeypatch, [_fold(a, b)])

    stored = await _merge([a, b, *fillers], skills)

    merged = stored[-1]
    assert [n.need_id for n in stored[:-1]] == ["A", "B", *[f.need_id for f in fillers]]
    by_id = {n.need_id: n for n in stored}
    assert by_id["A"].merged_into == merged.need_id
    assert by_id["B"].merged_into == merged.need_id
    assert all(by_id[f.need_id].merged_into is None for f in fillers)
    assert by_id["A"].statement_th == a.statement_th, "an original is kept as it was"


async def test_out_of_scope_and_unwritten_needs_never_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ok1, ok2 = _need("A", 0.9), _need("B", 0.8)
    out = _need("OUT", 0.7, in_scope=False)
    unwritten = _need("UNW", 0.6, statement=f"{REVIEW_MARKER_TH} ทักษะ ก, ทักษะ ข")
    dedup, _ = _patch(monkeypatch, [])

    stored = await _merge([ok1, out, unwritten, ok2], [])

    offered = dedup.await_args.args[0]
    assert [n.need_id for n in offered] == ["A", "B"]
    assert [n.need_id for n in stored] == ["A", "OUT", "UNW", "B"]


async def test_failed_merged_sentence_leaves_group_unmerged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = _need("A", 0.9, skills=["s1"]), _need("B", 0.5, skills=["s2"])
    skills = [_skill("s1", "ทักษะหนึ่ง", 0.5), _skill("s2", "ทักษะสอง", 0.5)]
    _patch(monkeypatch, [_fold(a, b)], AsyncMock(side_effect=RuntimeError("down")))

    stored = await _merge([a, b, *_fillers()], skills)

    assert all(n.merged_into is None for n in stored)
    assert not [n for n in stored if n.merged_from]
    assert len(stored) == 6


async def test_dedup_switched_off_merges_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nd.settings, "need_dedup_provider", "")
    call = AsyncMock(side_effect=AssertionError("no dedup call when switched off"))
    monkeypatch.setattr(nd, "complete_need_dedup", call)
    sentence = _Sentence()
    monkeypatch.setattr(nm, "complete_need_combination", sentence)
    needs = [_need("A", 0.9), _need("B", 0.5), *_fillers()]

    stored = await _merge(needs, [])

    assert stored == needs
    assert sentence.calls == []


async def test_a_merged_need_is_scored_from_the_pooled_skills(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recomputed, not the max of the originals: two voices beat the one that named each."""
    s1 = _skill("s1", "ทักษะหนึ่ง", 0.5, eid="E1")
    s2 = _skill("s2", "ทักษะสอง", 0.5, eid="E2")
    a = _need("A", 0.2, skills=["s1"], evidence=["E1"])
    b = _need("B", 0.2, skills=["s2"], evidence=["E2"])
    _patch(monkeypatch, [_fold(a, b)])

    stored = await nm.merge_duplicates(
        "test", [a, b, *_fillers()], [s1, s2], _METADATA, {"E1": "employer", "E2": "employer"}
    )

    (merged,) = [n for n in stored if n.merged_from]
    assert merged.demand_score == pytest.approx(0.55)
    assert merged.is_optional is False
    assert merged.stakeholder_coverage == {StakeholderType.EMPLOYER: 2}
    assert merged.source_stakeholder_types == [StakeholderType.EMPLOYER]
    assert merged.in_field_skill_count == 2
    assert merged.graduate_capability_skill_count == 2


# --------------------------- the merge floor ---------------------------


def _kept(needs: list[Need], folds: list[FoldGroup]) -> list[list[str]]:
    return [[n.need_id for n in f.needs] for f in nm.enforce_merge_floor(needs, folds)]


def test_a_fold_leaving_exactly_the_floor_is_kept() -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 6)]  # 5 core

    assert _kept(needs, [_fold(needs[0], needs[1])]) == [["N2", "N1"]]


def test_a_fold_leaving_less_than_the_floor_is_unfolded() -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 5)]  # 4 core

    assert _kept(needs, [_fold(needs[0], needs[1])]) == []


def test_merge_floor_unfolds_lowest_demand_first() -> None:
    """Five core Needs, two pair folds -> 3 slots. Unfolding one restores 4; it is
    the fold whose top member has the lower demand."""
    needs = [_need(f"N{i}", i / 10) for i in range(1, 6)]
    low = _fold(needs[0], needs[1])  # top demand 0.2
    high = _fold(needs[3], needs[4])  # top demand 0.5

    assert _kept(needs, [low, high]) == [["N5", "N4"]]


def test_a_set_already_below_the_floor_gets_no_core_folds() -> None:
    needs = [_need(f"N{i}", i / 10) for i in range(1, 4)]  # 3 core

    assert _kept(needs, [_fold(needs[0], needs[1])]) == []


def test_optional_folds_are_never_unfolded_for_the_floor() -> None:
    core = [_need(f"N{i}", i / 10) for i in range(1, 4)]  # 3 core, below the floor
    o1, o2 = _need("O1", 0.05, optional=True), _need("O2", 0.04, optional=True)

    assert _kept([*core, o1, o2], [_fold(o1, o2)]) == [["O1", "O2"]]


def test_pooled_frequencies_count_rows_per_normalised_name_in_top_order() -> None:
    pooled = [
        _skill("a1", "วิเคราะห์ข้อมูล", 0.9, eid="E1"),
        _skill("a2", " วิเคราะห์ข้อมูล ", 0.9, eid="E2"),
        _skill("a3", "วิเคราะห์ข้อมูล", 0.9, eid="E3"),
        _skill("b1", "นำเสนอผลงาน", 0.5, eid="E4"),
    ]

    assert nm.pooled_frequencies(pooled, nm.rank_top_skills(pooled)) == [3, 1]


async def test_the_merged_prompt_is_given_the_pooled_frequencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skills = [
        _skill("s1", "วิเคราะห์ข้อมูล", 0.9, eid="E1"),
        _skill("s2", "วิเคราะห์ข้อมูล", 0.9, eid="E2"),
        _skill("s3", "นำเสนอผลงาน", 0.5, eid="E3"),
    ]
    a = _need("A", 0.9, skills=["s1", "s3"])
    b = _need("B", 0.5, skills=["s2"])
    _, sentence = _patch(monkeypatch, [_fold(a, b)])

    await _merge([a, b, *_fillers()], skills)

    user = sentence.calls[0][-1]["content"]  # type: ignore[attr-defined]
    assert "0 | วิเคราะห์ข้อมูล | 2" in user and "1 | นำเสนอผลงาน | 1" in user


# ------------------------------ the summary line ------------------------------


async def test_one_summary_line_reports_the_step_in_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loguru import logger  # noqa: PLC0415

    a = _need("A", 0.9, ksec=KSECCategory.S, skills=["s1"])
    b = _need("B", 0.5, ksec=KSECCategory.K, skills=["s2"])
    skills = [_skill("s1", "ทักษะหนึ่ง", 0.5), _skill("s2", "ทักษะสอง", 0.5)]
    accepted = nd.AcceptedGroups([_fold(a, b)])
    accepted.proposed = 3
    _patch(monkeypatch, accepted)  # type: ignore[arg-type]
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        await _merge([a, b, *_fillers()], skills)
    finally:
        logger.remove(sink)

    (summary,) = [m for m in lines if m.startswith("need_merge: groups proposed")]
    assert summary == (
        "need_merge: groups proposed=3 accepted=1 unfolded_for_floor=0 "
        "sentence_failed=0 merged=1 multi_tag_merged=1 core_needs=6->5"
    )


async def test_summary_line_counts_a_floor_unfold_and_a_failed_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loguru import logger  # noqa: PLC0415

    a, b = _need("A", 0.9, skills=["s1"]), _need("B", 0.5, skills=["s2"])
    skills = [_skill("s1", "ทักษะหนึ่ง", 0.5), _skill("s2", "ทักษะสอง", 0.5)]
    _patch(monkeypatch, [_fold(a, b)], sentence=AsyncMock(side_effect=RuntimeError("down")))
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        await _merge([a, b, *_fillers()], skills)
    finally:
        logger.remove(sink)

    (summary,) = [m for m in lines if m.startswith("need_merge: groups proposed")]
    assert "accepted=1 unfolded_for_floor=0 sentence_failed=1 merged=0" in summary
    assert "core_needs=6->6" in summary


async def test_summary_line_counts_unfolded_for_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    from loguru import logger  # noqa: PLC0415

    a, b = _need("A", 0.9, skills=["s1"]), _need("B", 0.5, skills=["s2"])
    skills = [_skill("s1", "ทักษะหนึ่ง", 0.5), _skill("s2", "ทักษะสอง", 0.5)]
    _patch(monkeypatch, [_fold(a, b)])
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="INFO")
    try:
        # Only 2 core Needs: folding them would leave 1, below the floor of 4.
        await _merge([a, b], skills)
    finally:
        logger.remove(sink)

    (summary,) = [m for m in lines if m.startswith("need_merge: groups proposed")]
    assert "accepted=1 unfolded_for_floor=1 sentence_failed=0 merged=0" in summary


# ------------------------- names that normalise away -------------------------


def test_rank_top_skills_is_empty_when_every_name_normalises_away() -> None:
    assert nm.rank_top_skills([_skill("s1", "   ", 0.5)]) == []


async def test_a_group_whose_names_all_normalise_away_is_left_unmerged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = _need("A", 0.9, skills=["s1"]), _need("B", 0.5, skills=["s2"])
    skills = [_skill("s1", "   ", 0.5), _skill("s2", " ", 0.5)]
    _, sentence = _patch(monkeypatch, [_fold(a, b)])

    stored = await _merge([a, b, *_fillers()], skills)

    assert not any(n.merged_from for n in stored)
    assert all(n.merged_into is None for n in stored)
    assert sentence.calls == []  # type: ignore[attr-defined]
