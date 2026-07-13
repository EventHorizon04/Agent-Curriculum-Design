from curriculum_agent.stages.smart_rules import CRITERION_FIX_HINTS_TH, HardCriterion, hard_failures

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
