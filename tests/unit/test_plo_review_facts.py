from __future__ import annotations

from curriculum_agent.models import (
    PLO,
    BloomLevel,
    KSECCategory,
    Need,
    PLOSetReview,
    SMARTCheck,
    StakeholderType,
)
from curriculum_agent.prompts.plo_review import build_plo_review_prompt
from curriculum_agent.stages.plo_review_facts import (
    bloom_histogram,
    build_dossier,
    current_ksec,
    exclusion_reason,
    is_stale,
    ksec_coverage,
    need_demands,
    plo_fingerprint,
    select_unused_needs,
)

_SMART = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _need(
    nid: str,
    ksec: KSECCategory = KSECCategory.S,
    *,
    demand: float = 0.5,
    types: list[StakeholderType] | None = None,
    statement: str | None = None,
    in_field: int | None = None,
) -> Need:
    data: dict = dict(
        need_id=nid,
        program_id="p",
        statement_th=statement or f"ต้องการบัณฑิตที่ทำงาน {nid} ในสถานประกอบการจริงได้",
        rationale_th=f"เหตุผลของ {nid}",
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        member_skill_ids=[f"S-{nid}-1", f"S-{nid}-2"],
        source_evidence_ids=[f"E-{nid}"],
        source_stakeholder_types=types or [StakeholderType.EMPLOYER],
        stakeholder_coverage={t: 1 for t in (types or [StakeholderType.EMPLOYER])},
        freq=2,
        demand_score=demand,
    )
    if in_field is not None:
        data["in_field_skill_count"] = in_field
    return Need(**data)


def _plo(
    pid: str,
    need_ids: list[str],
    *,
    level: BloomLevel = BloomLevel.APPLY,
    optional: bool = False,
) -> PLO:
    return PLO(
        plo_id=pid,
        program_id="p",
        statement_th=f"วิเคราะห์ระบบงาน {pid} เพื่อเสนอแนวทางแก้ปัญหา",
        bloom_level=level,
        action_verb_th="วิเคราะห์",
        smart_check=_SMART,
        source_need_ids=need_ids,
        source_evidence_ids=["E1"],
        rationale_th="เหตุผล",
        is_optional=optional,
    )


# ------------------------------ KSEC ------------------------------


def test_current_ksec_expands_ec_and_ignores_a_missing_need() -> None:
    needs = {"n1": _need("n1", KSECCategory.EC), "n2": _need("n2", KSECCategory.K)}
    assert current_ksec(_plo("PLO1", ["n2", "n1", "gone"]), needs) == ["K", "E", "C"]


def test_coverage_counts_every_plo_per_domain_and_names_the_missing() -> None:
    needs = {"n1": _need("n1", KSECCategory.S), "n2": _need("n2", KSECCategory.EC)}
    plos = [_plo("PLO1", ["n1"]), _plo("PLO2", ["n2"]), _plo("OPT1", ["n1"], optional=True)]
    cov = ksec_coverage(plos, needs)
    assert cov.counts == {"K": 0, "S": 2, "E": 1, "C": 1}
    assert cov.missing == ["K"]
    assert cov.flags == []


def test_coverage_flags_an_all_k_set_and_a_set_without_e_or_c() -> None:
    needs = {"k": _need("k", KSECCategory.K)}
    cov = ksec_coverage([_plo("PLO1", ["k"]), _plo("PLO2", ["k"])], needs)
    assert cov.flags == ["all_k", "no_e_or_c"]


def test_a_plo_citing_a_vanished_need_counts_nothing() -> None:
    cov = ksec_coverage([_plo("PLO1", ["gone"])], {})
    assert cov.counts == {"K": 0, "S": 0, "E": 0, "C": 0}


def test_optional_plos_count_and_an_empty_set_raises_no_flag() -> None:
    needs = {"k": _need("k", KSECCategory.K)}
    cov = ksec_coverage([_plo("OPT1", ["k"], optional=True)], needs)
    assert cov.counts == {"K": 1, "S": 0, "E": 0, "C": 0}
    assert cov.flags == ["all_k", "no_e_or_c"]
    hist = bloom_histogram(
        [_plo("OPT1", ["k"], optional=True, level=BloomLevel.REMEMBER)], "bachelor"
    )
    assert hist.counts["remember"] == 1 and hist.flags == ["below_apply_majority"]
    assert ksec_coverage([], needs).flags == [] and bloom_histogram([], "bachelor").flags == []


# ------------------------------ Bloom ------------------------------


def test_histogram_counts_every_plo_in_level_order() -> None:
    plos = [
        _plo("PLO1", ["n"], level=BloomLevel.CREATE),
        _plo("PLO2", ["n"], level=BloomLevel.APPLY),
        _plo("PLO3", ["n"], level=BloomLevel.CREATE),
        _plo("OPT1", ["n"], level=BloomLevel.REMEMBER, optional=True),
    ]
    hist = bloom_histogram(plos, "bachelor")
    assert list(hist.counts) == [level.value for level in BloomLevel]
    assert hist.counts["create"] == 2 and hist.counts["apply"] == 1 and hist.counts["remember"] == 1
    assert hist.degree_level == "bachelor"
    assert hist.flags == []


def test_histogram_flags_a_majority_below_apply() -> None:
    plos = [
        _plo("PLO1", ["n"], level=BloomLevel.UNDERSTAND),
        _plo("PLO2", ["n"], level=BloomLevel.REMEMBER),
        _plo("PLO3", ["n"], level=BloomLevel.APPLY),
    ]
    assert bloom_histogram(plos, "bachelor").flags == ["below_apply_majority"]


def test_exactly_half_below_apply_is_not_a_majority() -> None:
    plos = [_plo("PLO1", ["n"], level=BloomLevel.UNDERSTAND), _plo("PLO2", ["n"])]
    assert bloom_histogram(plos, "bachelor").flags == []


# ------------------------------ unused Needs ------------------------------


def test_unused_needs_are_the_top_five_by_demand_plus_council_backed() -> None:
    needs = [_need(f"n{i}", demand=i / 10) for i in range(1, 9)]  # n8 highest
    council = _need("c1", demand=0.05, types=[StakeholderType.PROFESSIONAL_COUNCIL])
    cited = _need("used", demand=0.99)
    plos = [_plo("PLO1", ["used"])]
    picked = select_unused_needs(plos, [*needs, council, cited])
    assert [u.need_id for u in picked] == ["n8", "n7", "n6", "n5", "n4", "c1"]
    assert picked[-1].stakeholder_types == ["professional_council"]
    assert all(u.verdict is None and u.reason_th == "" for u in picked)


def test_unused_selection_is_deduplicated_when_a_council_need_is_also_top() -> None:
    council = _need("c1", demand=0.9, types=[StakeholderType.PROFESSIONAL_COUNCIL])
    picked = select_unused_needs([], [council, _need("n1", demand=0.1)])
    assert [u.need_id for u in picked] == ["c1", "n1"]


def test_exclusion_reason_checks_scope_then_unwritten() -> None:
    assert exclusion_reason(_need("a")) == "lost_on_demand"
    assert exclusion_reason(_need("b", in_field=0)) == "out_of_scope"
    unwritten = _need("c", statement="[ต้องทบทวน] ทักษะก, ทักษะข, ทักษะค ที่ต้องเขียนใหม่")
    assert exclusion_reason(unwritten) == "unwritten"


# ------------------------------ dossier ------------------------------


def test_the_dossier_carries_no_evidence_skill_names_or_old_verdicts() -> None:
    """The information-bias rule (spec section 2): the dossier is the set, its
    Need sentences, and code facts — nothing a reviewer could anchor on."""
    needs = [_need("n1"), _need("n2", KSECCategory.EC), _need("u1", demand=0.9)]
    plos = [_plo("PLO1", ["n1"]), _plo("PLO2", ["n2", "gone"])]
    d = build_dossier(
        plos, needs, program_context="หลักสูตรปริญญาตรี สาขาการแปล", degree_level="bachelor"
    )
    text = repr(d)
    for forbidden in ("E-n1", "S-n1-1", "rationale", "เหตุผลของ", "smart_check", "diagnosis"):
        assert forbidden not in text, forbidden
    assert [i.plo_id for i in d.items] == ["PLO1", "PLO2"]
    assert d.items[1].need_statements_th == (needs[1].statement_th,)
    assert d.core_count == 2
    assert [u.need_id for u in d.unused_needs] == ["u1"]


def test_the_rendered_prompt_carries_no_skill_names_ids_or_rationale() -> None:
    """The bias test reads what the model reads: both turns of the rendered prompt,
    including an unwritten Need whose fallback statement is a skill list."""
    skill_a, skill_b = "การแปลเอกสารกฎหมาย", "การล่ามประชุม"
    unwritten = _need("w1", demand=0.9, statement=f"[ต้องทบทวน] {skill_a}, {skill_b}")
    needs = [_need("n1"), _need("n2", KSECCategory.EC), unwritten]
    plos = [_plo("PLO1", ["n1"]), _plo("PLO2", ["n2"])]
    d = build_dossier(
        plos, needs, program_context="หลักสูตรปริญญาตรี สาขาการแปล", degree_level="bachelor"
    )
    assert [u.exclusion for u in d.unused_needs] == ["unwritten"]
    text = "\n".join(m["content"] for m in build_plo_review_prompt(d))
    assert "[w1]" in text  # the Need is offered to the reviewer, by id
    forbidden = [skill_a, skill_b, "smart_check", "diagnosis", "rationale"]
    for n in needs:
        forbidden += [*n.source_evidence_ids, *n.member_skill_ids, n.rationale_th]
    for term in forbidden:
        assert term not in text, term


# ------------------------------ fingerprint ------------------------------


def test_fingerprint_moves_when_a_need_demand_changes() -> None:
    plos = [_plo("PLO1", ["n1"])]
    a = plo_fingerprint(plos, need_demands([_need("n1", demand=0.5)]))
    b = plo_fingerprint(plos, need_demands([_need("n1", demand=0.6)]))
    c = plo_fingerprint(plos, need_demands([_need("n1", demand=0.5), _need("n2")]))
    assert len({a, b, c}) == 3
    assert a == plo_fingerprint(plos, {"n1": 0.5})


def test_an_old_review_row_reads_and_is_stale_under_the_new_fingerprint() -> None:
    old = PLOSetReview.model_validate(
        {
            "program_id": "p",
            "plo_fingerprint": "0" * 64,
            "model": "z-ai/glm-5.3-flash",
            "created_at": "2026-10-05T16:32:00",
            "redundancies": [],
            "ksec": [],
            "bloom": [],
            "bloom_distribution_th": "",
            "summary_th": "เดิม",
        }
    )
    assert old.reviewed_by == "agent"
    assert old.code_only_reason is None and old.unused_needs == [] and old.tool_calls == []
    assert is_stale(old, [_plo("PLO1", ["n1"])], {"n1": 0.5})
