"""Thai has no word boundaries, so a substring scan for the seven forbidden
words flags legitimate curriculum vocabulary. Each false positive below is a
named case rather than one parametrised blob, so a regression says which word
came back.
"""

import pytest

from curriculum_agent.models import PLO
from curriculum_agent.smart_vocabulary import forbidden_words_in
from curriculum_agent.stages.smart_rules import HardCriterion, hard_failures

KNOWN = {"c1"}


# ------------------- compounds that must NOT fail M -------------------


@pytest.mark.parametrize(
    ("case", "statement_th"),
    [
        ("รักษา", "รักษาผู้ป่วยตามมาตรฐานวิชาชีพได้"),
        ("การรักษา", "วางแผนการรักษาผู้ป่วยร่วมกับทีมสหวิชาชีพได้"),
        ("อนุรักษ์", "ออกแบบแนวทางอนุรักษ์พลังงานในโรงงานได้"),
        ("จำแนก", "จำแนกประเภทของข้อมูลตามเกณฑ์ที่กำหนดได้"),
        ("จำลอง", "สร้างแบบจำลองทางคณิตศาสตร์ของระบบได้"),
        ("จำเป็น", "ระบุทรัพยากรที่จำเป็นต่อโครงการได้"),
        ("จำกัด", "วิเคราะห์ข้อจำกัดของระบบสารสนเทศได้"),
        ("จำนวน", "คำนวณจำนวนวัสดุที่ใช้ในการก่อสร้างได้"),
        ("ประจำ", "ปฏิบัติงานประจำวันตามมาตรฐานความปลอดภัยได้"),
        ("ความรู้", "บูรณาการความรู้ทางวิศวกรรมเพื่อออกแบบระบบได้"),
        ("เรียนรู้", "ออกแบบแผนการเรียนรู้ของตนเองได้"),
        ("รู้จัก", "วิเคราะห์กลุ่มลูกค้าที่รู้จักตราสินค้าได้"),
    ],
)
def test_a_compound_containing_a_forbidden_word_is_not_a_violation(
    case: str, statement_th: str
) -> None:
    assert forbidden_words_in(statement_th) == [], f"{case} flagged as a forbidden word"


@pytest.mark.parametrize(
    ("verb_th", "statement_th"),
    [
        ("จำแนก", "จำแนกประเภทของข้อมูลตามเกณฑ์ที่กำหนดได้"),
        ("รักษา", "รักษาผู้ป่วยตามมาตรฐานวิชาชีพได้"),
    ],
)
def test_a_sound_plo_using_such_a_verb_clears_the_hard_gate(
    verb_th: str, statement_th: str
) -> None:
    """The reason this bug mattered: a PLO like this used to hard-fail M, spend
    every repair round on a hint about a word it never used, and escalate."""
    assert hard_failures(statement_th, verb_th, ["c1"], KNOWN) == []


# --------------------- genuine violations still fail ---------------------


@pytest.mark.parametrize(
    ("word", "statement_th"),
    [
        ("เข้าใจ", "เข้าใจหลักการเขียนโปรแกรมเชิงวัตถุ"),
        ("เข้าใจ", "มีความเข้าใจในหลักการทางสถิติ"),
        ("ตระหนัก", "ตระหนักถึงจริยธรรมวิชาชีพ"),
        ("รู้", "รู้หลักการพื้นฐานของระบบฐานข้อมูล"),
        ("จำ", "จำสูตรคำนวณทางวิศวกรรมได้"),
        ("จำ", "จดจำขั้นตอนการทำงานของอัลกอริทึม"),
        ("รัก", "รักและภูมิใจในวิชาชีพของตน"),
        ("ซาบซึ้ง", "ซาบซึ้งในคุณค่าของศิลปวัฒนธรรมไทย"),
        ("ศรัทธา", "ศรัทธาในจรรยาบรรณวิชาชีพ"),
    ],
)
def test_a_real_violation_is_still_caught(word: str, statement_th: str) -> None:
    assert word in forbidden_words_in(statement_th)
    assert HardCriterion.M_FORBIDDEN in hard_failures(statement_th, "ระบุ", ["c1"], KNOWN)


def test_a_violation_next_to_an_allowed_compound_is_still_caught() -> None:
    """Masking must not swallow a real violation that happens to sit beside one."""
    found = forbidden_words_in("เข้าใจแนวทางการรักษาผู้ป่วย")
    assert found == ["เข้าใจ"]


def test_several_violations_come_back_in_the_order_they_appear() -> None:
    """FORBIDDEN_WORDS_TH is a set, so scan order would otherwise vary per run
    and `found[0]` — the word the error message quotes — would be arbitrary."""
    assert forbidden_words_in("รู้และเข้าใจหลักการทางสถิติ") == ["รู้", "เข้าใจ"]


# ---------------- the two callers must agree ----------------


@pytest.mark.parametrize(
    "statement_th",
    [
        "จำแนกประเภทของข้อมูลตามเกณฑ์ที่กำหนดได้",
        "รักษาผู้ป่วยตามมาตรฐานวิชาชีพได้",
        "บูรณาการความรู้ทางวิศวกรรมเพื่อออกแบบระบบได้",
    ],
)
def test_the_gate_and_the_model_validator_agree(valid_plo: PLO, statement_th: str) -> None:
    """Two independent substring loops could disagree about what a forbidden
    word is, and the moment they do a PLO the gate passed raises inside
    `PLO(...)` in the synthesis stage instead. One scan, one answer.
    """
    verb = "จำแนก" if statement_th.startswith("จำแนก") else statement_th[:5]
    assert hard_failures(statement_th, verb, ["c1"], KNOWN) != [HardCriterion.M_FORBIDDEN]

    # The validator is the other caller: it must accept exactly what the gate did.
    rebuilt = valid_plo.model_copy(update={"statement_th": statement_th})
    assert PLO.model_validate(rebuilt.model_dump()).statement_th == statement_th


def test_the_model_validator_still_rejects_a_real_violation(valid_plo: PLO) -> None:
    data = valid_plo.model_dump() | {"statement_th": "เข้าใจหลักการเขียนโปรแกรม"}
    with pytest.raises(ValueError, match="เข้าใจ"):
        PLO.model_validate(data)


def test_an_escalated_plo_still_keeps_its_forbidden_word(valid_plo: PLO) -> None:
    """The escalation escape hatch is unaffected — an unrepairable statement is
    kept for human review rather than dropped (immutable rule 3's exception)."""
    data = valid_plo.model_dump() | {
        "statement_th": "เข้าใจหลักการเขียนโปรแกรม",
        "smart_escalated": True,
    }
    assert PLO.model_validate(data).statement_th == "เข้าใจหลักการเขียนโปรแกรม"
