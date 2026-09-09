from __future__ import annotations

from enum import StrEnum

from curriculum_agent.smart_vocabulary import forbidden_words_in


class HardCriterion(StrEnum):
    S_VERB = "S_verb"
    M_FORBIDDEN = "M_forbidden"
    R_EVIDENCE = "R_evidence"


CRITERION_FIX_HINTS_TH: dict[HardCriterion, str] = {
    HardCriterion.S_VERB: (
        "Specific ไม่ผ่าน: action_verb_th ต้องปรากฏใน statement_th และเป็นกริยา Bloom เพียงตัวเดียวที่ชัดเจน"
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


def hard_failures(
    statement_th: str,
    action_verb_th: str,
    source_need_ids: list[str],
    known_need_ids: set[str],
) -> list[HardCriterion]:
    """Code-level SMART hard checks (S verb presence, M forbidden words, R evidence)."""
    fails: list[HardCriterion] = []
    if not action_verb_th or action_verb_th not in statement_th:
        fails.append(HardCriterion.S_VERB)
    if forbidden_words_in(statement_th):
        fails.append(HardCriterion.M_FORBIDDEN)
    if not source_need_ids or not set(source_need_ids) <= known_need_ids:
        fails.append(HardCriterion.R_EVIDENCE)
    return fails
