import pytest

from curriculum_agent.stages.smart_rules import (
    CRITERION_FIX_HINTS_TH,
    HardCriterion,
    hard_failures,
    strip_outcome_prefix,
)

KNOWN = {"c1", "c2"}


def test_clean_plo_has_no_hard_failures():
    fails = hard_failures("วิเคราะห์ข้อมูลด้วยเทคนิคทางสถิติได้", "วิเคราะห์", ["c1"], KNOWN)
    assert fails == []


def test_forbidden_word_fails_measurable():
    fails = hard_failures("เข้าใจหลักการเขียนโปรแกรม", "เข้าใจ", ["c1"], KNOWN)
    assert HardCriterion.M_FORBIDDEN in fails


def test_verb_absent_from_statement_fails_specific():
    fails = hard_failures("ข้อมูลด้วยเทคนิคทางสถิติ", "ออกแบบ", ["c1"], KNOWN)
    assert HardCriterion.S_VERB in fails


def test_empty_clusters_fails_evidence():
    assert HardCriterion.R_EVIDENCE in hard_failures("วิเคราะห์ข้อมูลได้", "วิเคราะห์", [], KNOWN)


def test_unknown_cluster_id_fails_evidence():
    assert HardCriterion.R_EVIDENCE in hard_failures("วิเคราะห์ข้อมูลได้", "วิเคราะห์", ["c9"], KNOWN)


def test_every_criterion_has_a_thai_hint():
    assert set(CRITERION_FIX_HINTS_TH) == set(HardCriterion)


# --- S_multi_verb: the rule is enforced on the declared verb, not the sentence.
#
# Measured on the nine stored PLOs before this check existed: six declared a
# multi-verb phrase in action_verb_th ("ออกแบบและดำเนินการ", "ตีความและอธิบาย"),
# and `action_verb_th in statement_th` passed every one of them because synthesis
# writes the whole phrase into the sentence. Scanning the sentence instead reports
# verbs from subordinate clauses ("โดยใช้...", "เพื่อสร้าง...", the noun
# "แนวปฏิบัติ") and would have failed four sound outcomes.


def _statement_using(verb_phrase: str) -> str:
    """A statement that contains the phrase, so only S_multi_verb is in play."""
    return f"{verb_phrase}เอกสารสัญญาทางธุรกิจไทย-จีนในบริบทของงานแปลวิชาชีพ"


def test_one_declared_verb_passes():
    fails = hard_failures(_statement_using("ออกแบบ"), "ออกแบบ", ["c1"], KNOWN)
    assert HardCriterion.S_MULTI_VERB not in fails


def test_two_declared_verbs_at_the_same_level_pass():
    fails = hard_failures(_statement_using("ออกแบบและพัฒนา"), "ออกแบบและพัฒนา", ["c1"], KNOWN)
    assert HardCriterion.S_MULTI_VERB not in fails


def test_two_declared_verbs_two_levels_apart_fail():
    """create + apply. The rule allows two verbs only at adjacent levels."""
    fails = hard_failures(_statement_using("ออกแบบและดำเนินการ"), "ออกแบบและดำเนินการ", ["c1"], KNOWN)
    assert HardCriterion.S_MULTI_VERB in fails


def test_three_declared_verbs_fail_however_close_the_levels():
    fails = hard_failures(
        _statement_using("ออกแบบและดำเนินการตรวจสอบ"),
        "ออกแบบและดำเนินการตรวจสอบ",
        ["c1"],
        KNOWN,
    )
    assert HardCriterion.S_MULTI_VERB in fails


def test_a_verb_the_table_does_not_know_passes():
    """The table's silence is not evidence the verb is wrong.

    `bloom_verbs` is a judgement call that has never had a Thai curriculum
    specialist's review, so an unrecognised phrase must not escalate an outcome —
    that is the failure its header warned about, and it is why zero recognised
    verbs passes rather than failing as "no Bloom verb declared". OPT4 declares
    "ประพฤติตน", which the table does not hold.
    """
    fails = hard_failures(_statement_using("ประพฤติตน"), "ประพฤติตน", ["c1"], KNOWN)
    assert HardCriterion.S_MULTI_VERB not in fails


def test_a_compound_verb_is_not_split_into_the_verb_inside_it():
    """ "ประยุกต์ใช้" is one verb, not "ประยุกต์" plus the Apply verb "ใช้"."""
    fails = hard_failures(_statement_using("ประยุกต์ใช้"), "ประยุกต์ใช้", ["c1"], KNOWN)
    assert HardCriterion.S_MULTI_VERB not in fails


def test_verbs_in_the_statement_do_not_fail_the_check():
    """Only the declared phrase is judged.

    The statement below carries ออกแบบ, ดำเนินการ and สร้าง — the shape of stored
    OPT1 — but declares one of them. Scanning the sentence is what over-reports a
    means clause or a purpose clause as a second outcome verb.
    """
    statement = "ออกแบบกลยุทธ์การตลาดดิจิทัล โดยดำเนินการตามบริบทธุรกิจ เพื่อสร้างคอนเทนต์ที่เหมาะสม"
    fails = hard_failures(statement, "ออกแบบ", ["c1"], KNOWN)
    assert HardCriterion.S_MULTI_VERB not in fails


def test_a_verb_sitting_at_several_levels_passes_on_its_closest_one():
    """ "เปรียบเทียบ" is both Understand and Analyze; "กำกับติดตาม" is Evaluate.

    Analyze and Evaluate are adjacent, Understand and Evaluate are not. The rule
    asks whether *some* pair of levels is adjacent rather than every pair,
    because `levels_for_verb` returns a list precisely where the rubric says the
    verb's level is settled by the object it takes — which this check cannot see.
    Requiring every pair would reject the phrase on a reading the author never
    meant.
    """
    phrase = "เปรียบเทียบและกำกับติดตาม"
    fails = hard_failures(_statement_using(phrase), phrase, ["c1"], KNOWN)
    assert HardCriterion.S_MULTI_VERB not in fails


# --------------------------- the declared verb leads the sentence ---------------------------
#
# Stored PLO2 declared "ประยุกต์ใช้" while its outcome was "แปลและตรวจสอบ...":
# the declared verb sat in a means clause ("โดยประยุกต์ใช้เทคโนโลยี AI"), and a
# presence test passed it. Thai outcome statements open with their verb, so the
# check is on the opening, after the subject prefix the sentence should not
# carry anyway.


def test_a_declared_verb_only_in_a_means_clause_fails_specific():
    statement = "แปลและตรวจสอบเอกสารกฎหมายไทย-จีน โดยประยุกต์ใช้เทคโนโลยี AI ในการตรวจทาน"
    fails = hard_failures(statement, "ประยุกต์ใช้", ["c1"], KNOWN)
    assert HardCriterion.S_VERB in fails


def test_a_declared_verb_behind_a_graduate_prefix_passes():
    """The prefix is stripped before the opening is checked, so a designer's
    edit that still says "บัณฑิตสามารถ..." is not failed for the subject."""
    statement = "บัณฑิตสามารถประพฤติตนอย่างมีจริยธรรมในการสื่อสารข้ามวัฒนธรรม"
    fails = hard_failures(statement, "ประพฤติตน", ["c1"], KNOWN)
    assert HardCriterion.S_VERB not in fails


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("บัณฑิตสามารถวิเคราะห์ข้อมูลได้", "วิเคราะห์ข้อมูลได้"),
        ("บัณฑิตจะสามารถวิเคราะห์ข้อมูลได้", "วิเคราะห์ข้อมูลได้"),
        ("บัณฑิตมีความสามารถในการวิเคราะห์ข้อมูล", "วิเคราะห์ข้อมูล"),
        ("ผู้เรียนสามารถวิเคราะห์ข้อมูลได้", "วิเคราะห์ข้อมูลได้"),
        ("ผู้สำเร็จการศึกษาสามารถ วิเคราะห์ข้อมูลได้", "วิเคราะห์ข้อมูลได้"),
        ("สามารถวิเคราะห์ข้อมูลได้", "วิเคราะห์ข้อมูลได้"),
        ("  บัณฑิตสามารถวิเคราะห์ข้อมูลได้", "วิเคราะห์ข้อมูลได้"),
        ("วิเคราะห์ข้อมูลได้", "วิเคราะห์ข้อมูลได้"),
        ("  วิเคราะห์ข้อมูลได้", "วิเคราะห์ข้อมูลได้"),
    ],
)
def test_the_graduate_prefix_is_stripped(statement: str, expected: str) -> None:
    assert strip_outcome_prefix(statement) == expected


def test_a_prefix_word_inside_the_sentence_is_left_alone() -> None:
    """Only the opening is the subject; "บัณฑิต" later in the sentence is content."""
    statement = "วิเคราะห์ความสามารถของบัณฑิตสามารถด้านภาษา"
    assert strip_outcome_prefix(statement) == statement
