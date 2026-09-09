from __future__ import annotations

import pytest

from curriculum_agent.models import BLOOM_ORDER, BloomLevel
from curriculum_agent.smart_vocabulary import FORBIDDEN_WORDS_TH
from curriculum_agent.stages.bloom_verbs import (
    _NON_VERB_CONTEXTS_TH,
    BLOOM_VERBS_TH,
    are_adjacent,
    levels_for_verb,
    scan_statement_verbs,
    verbs_for_level,
)


def test_a_verb_at_one_level_reports_that_level() -> None:
    assert levels_for_verb("ออกแบบ") == [BloomLevel.CREATE]


def test_a_verb_at_several_levels_reports_all_of_them_in_order() -> None:
    """The rubric is explicit that cognitive demand, not the verb, fixes the
    level — so a one-level-per-verb table would assert something false."""
    assert levels_for_verb("เปรียบเทียบ") == [BloomLevel.UNDERSTAND, BloomLevel.ANALYZE]


def test_an_unrecognized_verb_reports_no_level() -> None:
    """A legitimate answer, and the useful one: no recognized Bloom verb."""
    assert levels_for_verb("ทำ") == []
    assert levels_for_verb("") == []


def test_every_level_carries_verbs_and_they_are_sorted() -> None:
    for level in BLOOM_ORDER:
        verbs = verbs_for_level(level)
        assert len(verbs) >= 5, f"{level} has only {len(verbs)} verbs"
        assert verbs == sorted(verbs)


def test_a_verb_is_never_also_masked_as_a_non_verb() -> None:
    """The two lists pull in opposite directions: a word in both would be
    offered as a Bloom verb and then discarded whenever it appeared. "ทบทวน"
    nearly landed in both — it was masked to stop "ทวน" firing, until "ทวน"
    left the table instead."""
    offered = {verb for verbs in BLOOM_VERBS_TH.values() for verb in verbs}
    assert offered & set(_NON_VERB_CONTEXTS_TH) == set()


def test_no_forbidden_word_is_offered_as_a_bloom_verb() -> None:
    """The table must not hand the synthesis model a word the M hard check
    rejects, which รู้/จำ/เข้าใจ would be at the two lowest levels."""
    offered = {verb for verbs in BLOOM_VERBS_TH.values() for verb in verbs}
    assert offered & FORBIDDEN_WORDS_TH == set()


# ---------------------------- scanning ----------------------------


def test_a_compound_verb_is_reported_as_itself_only() -> None:
    """ "จำแนกความแตกต่าง" contains "จำแนก". Reporting both would fail the
    one-verb rule on a single correct verb."""
    assert scan_statement_verbs("จำแนกความแตกต่างของโครงสร้างข้อมูลได้") == ["จำแนกความแตกต่าง"]


def test_two_verbs_are_both_reported_in_written_order() -> None:
    found = scan_statement_verbs("วิเคราะห์ปัญหาและออกแบบระบบได้")
    assert found == ["วิเคราะห์", "ออกแบบ"]


def test_a_statement_with_no_recognized_verb_reports_nothing() -> None:
    assert scan_statement_verbs("มีคุณลักษณะที่พึงประสงค์") == []


@pytest.mark.parametrize(
    ("word", "statement_th"),
    [
        ("โครงสร้าง", "จำแนกความแตกต่างของโครงสร้างข้อมูลได้"),
        ("การก่อสร้าง", "ควบคุมงานการก่อสร้างตามแบบได้"),
        ("ผู้สร้าง", "อธิบายบทบาทของผู้สร้างภาพยนตร์ได้"),
        ("ผู้ใช้", "อธิบายความต้องการของผู้ใช้ระบบได้"),
        ("ผลิตภัณฑ์", "ประเมินคุณภาพผลิตภัณฑ์ตามมาตรฐานได้"),
    ],
)
def test_a_verb_hiding_inside_an_ordinary_word_is_not_reported(
    word: str, statement_th: str
) -> None:
    """ "โครงสร้าง" reads as the Create verb "สร้าง", and it appears in
    engineering and IT outcomes constantly — the one-verb rule would fire on
    almost every one of them."""
    found = scan_statement_verbs(statement_th)
    assert len(found) == 1, f"{word} produced a spurious verb: {found}"


def test_a_compound_verb_survives_a_non_verb_word_in_its_middle() -> None:
    """ "จัดโครงสร้างใหม่" is a Create verb that contains "โครงสร้าง". A match is
    only discarded when it sits *entirely inside* a listed word."""
    assert scan_statement_verbs("จัดโครงสร้างใหม่ขององค์กรได้") == ["จัดโครงสร้างใหม่"]


def test_the_same_verb_twice_is_reported_twice() -> None:
    """The count is what the one-verb rule reads, so a repeat must not collapse."""
    assert scan_statement_verbs("ออกแบบระบบและออกแบบฐานข้อมูลได้") == ["ออกแบบ", "ออกแบบ"]


# ---------------------------- adjacency ----------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (BloomLevel.APPLY, BloomLevel.ANALYZE),
        (BloomLevel.ANALYZE, BloomLevel.APPLY),
        (BloomLevel.CREATE, BloomLevel.CREATE),
    ],
)
def test_adjacent_levels_are_adjacent_in_both_directions(a: BloomLevel, b: BloomLevel) -> None:
    assert are_adjacent(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (BloomLevel.REMEMBER, BloomLevel.APPLY),
        (BloomLevel.CREATE, BloomLevel.REMEMBER),
    ],
)
def test_levels_two_or_more_steps_apart_are_not(a: BloomLevel, b: BloomLevel) -> None:
    assert not are_adjacent(a, b)


def test_adjacency_reads_the_shared_bloom_order() -> None:
    """Not a second ordering of its own — the project's adjacent-levels rule
    must not acquire a rival definition."""
    for earlier, later in zip(BLOOM_ORDER, BLOOM_ORDER[1:], strict=False):
        assert are_adjacent(earlier, later)


def test_the_table_is_not_wired_into_the_hard_checks() -> None:
    """Advisory only, deliberately: a PLO using a sound verb this table forgot
    would otherwise hard-fail Specific and escalate."""
    from curriculum_agent.stages import smart_rules

    assert "bloom" not in smart_rules.__dict__
    # A statement whose verb is absent from the table still clears the gate.
    assert smart_rules.hard_failures("ตรวจวัดคุณภาพน้ำได้", "ตรวจวัด", ["c1"], {"c1"}) == []
