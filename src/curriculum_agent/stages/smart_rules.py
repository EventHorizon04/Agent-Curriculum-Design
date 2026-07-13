from __future__ import annotations

from enum import Enum

from curriculum_agent.models import FORBIDDEN_WORDS_TH


class HardCriterion(str, Enum):
    S_VERB = "S_verb"
    M_FORBIDDEN = "M_forbidden"
    R_EVIDENCE = "R_evidence"


CRITERION_FIX_HINTS_TH: dict[HardCriterion, str] = {
    HardCriterion.S_VERB: (
        "Specific ไม่ผ่าน: action_verb_th ต้องปรากฏใน statement_th "
        "และเป็นกริยา Bloom เพียงตัวเดียวที่ชัดเจน"
    ),
    HardCriterion.M_FORBIDDEN: (
        "Measurable ไม่ผ่าน: ห้ามใช้คำ รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก "
        "ให้แทนด้วยกริยาที่สังเกตได้ เช่น อธิบาย วิเคราะห์ ออกแบบ"
    ),
    HardCriterion.R_EVIDENCE: (
        "Relevant ไม่ผ่าน: source_cluster_ids ต้องอ้างอิง cluster ที่มีอยู่จริง "
        "อย่างน้อย 1 รายการ"
    ),
}


def hard_failures(
    statement_th: str,
    action_verb_th: str,
    source_cluster_ids: list[str],
    known_cluster_ids: set[str],
) -> list[HardCriterion]:
    """Code-level SMART hard checks (S verb presence, M forbidden words, R evidence)."""
    fails: list[HardCriterion] = []
    if not action_verb_th or action_verb_th not in statement_th:
        fails.append(HardCriterion.S_VERB)
    if any(word in statement_th for word in FORBIDDEN_WORDS_TH):
        fails.append(HardCriterion.M_FORBIDDEN)
    if not source_cluster_ids or not set(source_cluster_ids) <= known_cluster_ids:
        fails.append(HardCriterion.R_EVIDENCE)
    return fails
