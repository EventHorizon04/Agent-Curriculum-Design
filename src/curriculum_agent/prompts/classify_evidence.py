from __future__ import annotations

from curriculum_agent.models import StakeholderEvidence


def build_classify_evidence_prompt(evidence: StakeholderEvidence) -> list[dict[str, str]]:
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการออกแบบหลักสูตร OBE ตามมาตรฐาน MHESI\n"
        "จงจัดประเภทข้อมูลความต้องการจากผู้มีส่วนได้ส่วนเสียออกเป็น 1 ประเภท:\n"
        "- need: ความต้องการพื้นฐานที่ขาดไม่ได้ (must-have)\n"
        "- requirement: ข้อกำหนด/มาตรฐานที่ต้องปฏิบัติตาม (compliance)\n"
        "- want: ความต้องการที่ดี แต่ไม่จำเป็น (nice-to-have)\n"
        "- unclassified: ข้อมูลที่ไม่ชัดเจนพอที่จะจัดประเภท\n\n"
        "ตอบเป็น JSON object ที่มี field:\n"
        "  classification: string (need|requirement|want|unclassified)\n"
        "  classification_rationale_th: string (เหตุผลสั้น ๆ ภาษาไทย ไม่เกิน 2 ประโยค)"
    )

    user_parts = [
        f"แหล่งที่มา: {evidence.source_name} ({evidence.stakeholder_type.value})",
        f"ข้อความ: {evidence.raw_text_th[:800]}",
    ]
    if evidence.raw_text_en:
        user_parts.append(f"(EN) {evidence.raw_text_en[:400]}")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
