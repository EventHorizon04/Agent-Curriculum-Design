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


def test_skills_and_needs_both_report_skill_extraction():
    """Two engine stages behind one review gate, reviewed on one page — so they
    are one stage as far as the designer's rail is concerned."""
    just_skills = stage_reached(has_evidence=True, has_skills=True, has_needs=False, has_plos=False)
    and_needs = stage_reached(has_evidence=True, has_skills=True, has_needs=True, has_plos=False)
    assert just_skills == and_needs == "skill_extraction"


def test_plos_are_the_furthest_derivable_stage():
    """plo_report re-persists the PLOs synthesis already wrote and leaves nothing
    of its own, so a program that has been through it is indistinguishable here."""
    assert (
        stage_reached(has_evidence=True, has_skills=True, has_needs=True, has_plos=True)
        == "plo_synthesis"
    )


def test_every_outcome_is_a_designer_stage():
    """Anything outside this list reaches the UI as a stage it cannot place, and
    the program reads as though it had never started."""
    flags = [
        {"has_evidence": e, "has_skills": s, "has_needs": n, "has_plos": p}
        for e in (False, True)
        for s in (False, True)
        for n in (False, True)
        for p in (False, True)
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
