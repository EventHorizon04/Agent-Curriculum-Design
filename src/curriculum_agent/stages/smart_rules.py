from __future__ import annotations

import re
from enum import StrEnum

from curriculum_agent.smart_vocabulary import forbidden_words_in
from curriculum_agent.stages.bloom_verbs import (
    are_adjacent,
    levels_for_verb,
    scan_statement_verbs,
)


class HardCriterion(StrEnum):
    S_VERB = "S_verb"
    S_MULTI_VERB = "S_multi_verb"
    M_FORBIDDEN = "M_forbidden"
    R_EVIDENCE = "R_evidence"


CRITERION_FIX_HINTS_TH: dict[HardCriterion, str] = {
    HardCriterion.S_VERB: (
        "Specific ไม่ผ่าน: statement_th ต้องขึ้นต้นด้วย action_verb_th "
        "ซึ่งเป็นกริยาของผลลัพธ์หลัก ไม่ใช่กริยาในวลีรองอย่าง 'โดยใช้...' หรือ 'เพื่อ...' "
        "ถ้างานหลักของประโยคคือกริยาอื่น ให้เปลี่ยน action_verb_th เป็นกริยานั้น หรือเรียบเรียงประโยคใหม่"
    ),
    HardCriterion.S_MULTI_VERB: (
        "Specific ไม่ผ่าน: action_verb_th ต้องเป็นกริยา Bloom เพียงตัวเดียว "
        "ใช้สองตัวได้เฉพาะเมื่ออยู่ระดับ Bloom เดียวกันหรือติดกัน "
        "เช่น 'ออกแบบและพัฒนา' (create ทั้งคู่) ใช้ได้ "
        "แต่ 'ออกแบบและดำเนินการ' (create กับ apply) ห่างกันเกินไป ให้เลือกตัวที่เป็นผลลัพธ์จริง"
    ),
    HardCriterion.M_FORBIDDEN: (
        "Measurable ไม่ผ่าน: ห้ามใช้คำ รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก "
        "ให้แทนด้วยกริยาที่สังเกตได้ เช่น อธิบาย วิเคราะห์ ออกแบบ "
        "(คำที่มีคำห้ามอยู่ข้างในแต่ใช้ได้ เช่น จำแนก จำลอง รักษา ความรู้ เรียนรู้)"
    ),
    HardCriterion.R_EVIDENCE: (
        "Relevant ไม่ผ่าน: source_need_ids ทุกรายการต้องอ้างอิง Need ที่มีอยู่จริง "
        "(ห้ามมี id ที่ไม่รู้จักแม้แต่รายการเดียว) และต้องมีอย่างน้อย 1 รายการ"
    ),
}


# "บัณฑิตสามารถ..." / "ผู้เรียนจะสามารถ..." / "บัณฑิตมีความสามารถในการ..." /
# a bare "สามารถ..." at the opening. An outcome statement in this programme opens
# with its verb; the subject is the graduate by definition of a PLO, so saying
# it adds nothing and pushes the verb off the opening the S check reads.
_OUTCOME_PREFIX_RE = re.compile(
    r"^\s*(?:(?:บัณฑิต|ผู้เรียน|ผู้สำเร็จการศึกษา)\s*(?:จะ)?\s*(?:มีความ)?)?"
    r"สามารถ\s*(?:ใน(?:การ)?)?\s*"
)


def strip_outcome_prefix(statement_th: str) -> str:
    """The statement without a leading subject-and-ability prefix.

    Pure wording: it removes words, never meaning, which is why code does it
    instead of spending one of the validation agent's three repairs on it.
    `plo_synthesis._adopt` applies it to every draft that can ship, and
    `hard_failures` applies it before reading the opening, so text that reached
    the gate some other way (a designer's edit, the agent's own probe) is judged
    on its verb rather than its subject.
    """
    return _OUTCOME_PREFIX_RE.sub("", statement_th, count=1).lstrip()


def declares_too_many_verbs(action_verb_th: str) -> bool:
    """Whether the declared verb phrase breaks "one Bloom verb per outcome".

    Judged on `action_verb_th`, never on the statement, and the measurement is
    the reason. Across the nine stored PLOs, six declared a phrase rather than a
    verb — "ออกแบบและดำเนินการ", "ออกแบบและดำเนินการตรวจสอบ", "ตีความและอธิบาย" —
    and `action_verb_th in statement_th` passed every one, because synthesis
    writes the whole phrase into the sentence it is checked against. Immutable
    rule 4 was prompt text with nothing behind it, and the field that declares
    the outcome verb is where it broke.

    Scanning the *statement* instead is the version that does not work. Thai
    packs means and purpose into the same sentence, so the scan reports
    "โดยใช้เทคโนโลยี", "เพื่อสร้างคอนเทนต์" and the noun "แนวปฏิบัติ" alongside the
    outcome verb: on the same nine rows it flags six, of which four are sound
    outcomes with one behaviour verb and a subordinate clause. The declared
    phrase has no subordinate clauses to mistake.

    Zero recognised verbs passes, and that is not an oversight. `bloom_verbs`
    says of itself that it is a judgement call wanting a Thai curriculum
    specialist's review, so the table not holding a phrase ("ประพฤติตน", on
    stored OPT4) is not evidence the phrase is wrong — and escalating an outcome
    over a gap in a vocabulary this repository wrote alone is exactly the failure
    that module's header warned about. This check only ever fires on verbs the
    table *does* recognise, which is what makes it safe to gate on.

    Two verbs pass when *some* pair of their levels is adjacent rather than every
    pair: `levels_for_verb` returns a list because the rubric puts one verb at
    several levels depending on cognitive demand, and a verb's level is settled
    by the object it takes, which this function cannot see.
    """
    verbs = scan_statement_verbs(action_verb_th)
    if len(verbs) <= 1:
        return False
    if len(verbs) > 2:
        return True
    first, second = verbs
    return not any(
        are_adjacent(a, b) for a in levels_for_verb(first) for b in levels_for_verb(second)
    )


def opens_with_declared_verb(statement_th: str, action_verb_th: str) -> bool:
    """S: the statement, after any "บัณฑิตสามารถ…" subject, opens with the declared
    verb. An empty declared verb opens nothing."""
    return bool(action_verb_th) and strip_outcome_prefix(statement_th).startswith(action_verb_th)


def hard_failures(
    statement_th: str,
    action_verb_th: str,
    source_need_ids: list[str],
    known_need_ids: set[str],
) -> list[HardCriterion]:
    """Code-level SMART hard checks (S verb leads and is one, M forbidden words, R evidence)."""
    fails: list[HardCriterion] = []
    if not opens_with_declared_verb(statement_th, action_verb_th):
        fails.append(HardCriterion.S_VERB)
    if declares_too_many_verbs(action_verb_th):
        fails.append(HardCriterion.S_MULTI_VERB)
    if forbidden_words_in(statement_th):
        fails.append(HardCriterion.M_FORBIDDEN)
    if not source_need_ids or not set(source_need_ids) <= known_need_ids:
        fails.append(HardCriterion.R_EVIDENCE)
    return fails
