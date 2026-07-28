from __future__ import annotations

from curriculum_agent.prompts.designer_note import NOTE_POLICY_TH, append_note

_KSEC_LABEL_TH = {
    "K": "ความรู้",
    "GS": "ทักษะทั่วไป",
    "SS": "ทักษะเฉพาะสาขา",
    "C": "คุณลักษณะบุคคล",
    "E": "คุณธรรมจริยธรรม",
}


def build_summarize_need_prompt(
    skill_names: list[str],
    sample_evidence: list[str],
    ksec: str,
    note_th: str | None = None,
) -> list[dict[str, str]]:
    """Turn one group of related skills into a single market-demand sentence."""
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ความต้องการของตลาดแรงงาน\n"
        "จากกลุ่มทักษะที่ให้มา จงสรุปเป็น 'ความต้องการของตลาด' หนึ่งประโยค\n\n"
        "กติกา:\n"
        "- เขียนเป็นประโยคเดียว มุมมองของ 'ตลาดแรงงานต้องการอะไร' "
        "ไม่ใช่มุมมองผู้เรียนหรือผลลัพธ์การเรียนรู้\n"
        "- ต้องสื่อถึงความสามารถจริงที่ใช้ทำงานได้ ไม่ใช่แค่ชื่อหมวดทักษะ\n"
        "- ห้ามเป็นเพียงการนำชื่อทักษะมาต่อกันด้วยเครื่องหมายจุลภาค\n"
        "- ความยาวไม่เกิน 2 บรรทัด\n\n"
        "ตอบเป็น JSON object ที่มี field:\n"
        "  statement_th: string (ประโยคภาษาไทย)\n"
        "  statement_en: string (ประโยคภาษาอังกฤษ)\n\n" + NOTE_POLICY_TH
    )
    label = _KSEC_LABEL_TH.get(ksec, ksec)
    keywords = ", ".join(skill_names[:30])
    evidence_block = "\n".join(f"- {q[:200]}" for q in sample_evidence[:5]) or "(ไม่มีตัวอย่าง)"
    user = (
        f"หมวดสมรรถนะ: {label} ({ksec})\n"
        f"ทักษะในกลุ่มนี้: {keywords}\n\n"
        f"ตัวอย่างข้อความ evidence:\n{evidence_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": append_note(user, note_th)},
    ]
