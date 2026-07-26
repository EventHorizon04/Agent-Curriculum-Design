from __future__ import annotations


def build_plo_classify_prompt(
    statement_th: str,
    bloom_level: str,
    need_summaries: list[str],
) -> list[dict[str, str]]:
    """Light-model prompt to classify a PLO as generic vs specific.

    need_summaries: each ≤200-token line describing one market Need.
    Returns OpenAI-style messages for Instructor structured output.
    """
    summary_block = "\n".join(f"- {s}" for s in need_summaries) or "(ไม่มี Market Needs)"
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE ทำหน้าที่จำแนกประเภทของ PLO "
                "ว่าเป็น 'generic' (ทักษะทั่วไปที่ถ่ายโอนข้ามสาขาได้ เช่น การสื่อสาร "
                "การคิดวิเคราะห์ การทำงานเป็นทีม) หรือ 'specific' "
                "(ทักษะ/ความรู้เฉพาะสาขาหรือวิชาชีพ) "
                "ตอบเป็น JSON ที่มี field 'classification' (ค่า 'generic' หรือ 'specific') "
                "และ 'rationale_th' (เหตุผลสั้น ๆ เป็นภาษาไทย)"
            ),
        },
        {
            "role": "user",
            "content": (
                f"PLO statement:\n{statement_th}\n\n"
                f"Bloom level: {bloom_level}\n\n"
                f"ความต้องการตลาด (Market Needs) ที่เกี่ยวข้อง:\n{summary_block}"
            ),
        },
    ]
