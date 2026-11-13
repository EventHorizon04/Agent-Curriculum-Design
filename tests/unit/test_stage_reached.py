"""How far a program has got, read off what it owns.

Progress used to be read off the program's latest session, and only the graph
path wrote one. The per-stage REST routes behind every stage page wrote nothing,
so a designer who worked page by page had no recorded progress at all: the rail
marked every stage as not yet reached however much of the pipeline they had run.
"""

from __future__ import annotations

from curriculum_agent.graph import DESIGNER_STAGES, stage_reached


def test_bare_program_is_at_intake():
    """The program row is intake's own output, so there is no 'nothing yet'."""
    assert (
        stage_reached(has_evidence=False, has_skills=False, has_needs=False, has_plos=False)
        == "intake"
    )


def test_evidence_alone_is_stakeholder_needs():
    assert (
        stage_reached(has_evidence=True, has_skills=False, has_needs=False, has_plos=False)
        == "stakeholder_needs"
    )


def test_skills_alone_are_skill_extraction():
    assert (
        stage_reached(has_evidence=True, has_skills=True, has_needs=False, has_plos=False)
        == "skill_extraction"
    )


def test_needs_are_need_analysis():
    """Agent 2 has its own page and rail stage, behind the one review gate."""
    assert (
        stage_reached(has_evidence=True, has_skills=True, has_needs=True, has_plos=False)
        == "need_analysis"
    )


def test_plos_without_a_review_or_report_are_plo_synthesis():
    """The stage is derived from what is stored: PLOs alone are synthesis."""
    assert (
        stage_reached(has_evidence=True, has_skills=True, has_needs=True, has_plos=True)
        == "plo_synthesis"
    )


def test_every_outcome_is_a_designer_stage():
    """Anything outside this list reaches the UI as a stage it cannot place, and
    the program reads as though it had never started."""
    flags = [
        {
            "has_evidence": e,
            "has_skills": s,
            "has_needs": n,
            "has_plos": p,
            "has_current_review": r,
            "has_current_report": c,
        }
        for e in (False, True)
        for s in (False, True)
        for n in (False, True)
        for p in (False, True)
        for r in (False, True)
        for c in (False, True)
    ]
    for combination in flags:
        assert stage_reached(**combination) in DESIGNER_STAGES, combination


def test_later_output_wins_over_earlier():
    """Skills that were re-extracted after the PLOs were written must not drag
    progress backwards — the furthest output is what counts."""
    assert (
        stage_reached(has_evidence=False, has_skills=False, has_needs=False, has_plos=True)
        == "plo_synthesis"
    )


def test_a_current_review_is_the_last_stage():
    assert (
        stage_reached(
            has_evidence=True,
            has_skills=True,
            has_needs=True,
            has_plos=True,
            has_current_review=True,
        )
        == "plo_review"
    )


def test_without_a_current_review_plos_are_still_plo_synthesis():
    assert (
        stage_reached(has_evidence=True, has_skills=True, has_needs=True, has_plos=True)
        == "plo_synthesis"
    )


def test_a_current_report_is_the_last_stage_and_wins_over_a_review():
    assert (
        stage_reached(
            has_evidence=True,
            has_skills=True,
            has_needs=True,
            has_plos=True,
            has_current_review=True,
            has_current_report=True,
        )
        == "plo_report"
    )
    assert (
        stage_reached(
            has_evidence=True,
            has_skills=True,
            has_needs=True,
            has_plos=True,
            has_current_report=True,
        )
        == "plo_report"
    )


def test_precedence_is_report_then_review_then_plos():
    base = {"has_evidence": True, "has_skills": True, "has_needs": True, "has_plos": True}
    assert stage_reached(**base, has_current_review=True) == "plo_review"
    assert stage_reached(**base) == "plo_synthesis"
