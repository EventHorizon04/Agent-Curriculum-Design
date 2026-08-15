from __future__ import annotations

from curriculum_agent.models import KSECCategory
from curriculum_agent.prompts.designer_note import NOTE_POLICY_TH, append_note

_KSEC_LABEL_TH: dict[str, str] = {
    "K": "ความรู้",
    "S": "ทักษะ",
    "EC": "คุณธรรมจริยธรรมและคุณลักษณะบุคคล",
    "E": "คุณธรรมจริยธรรม",
    "C": "คุณลักษณะบุคคล",
}

# A plain dict has no structural link to KSECCategory, so nothing stops the two
# from drifting apart the next time the enum gains, loses, or renames a member.
# This assertion is what turns that drift into an import-time crash instead of
# a label that silently falls back to the raw code below — it is what makes
# the .get(...) fallback provably unreachable for every real KSECCategory
# value, not just today's five.
_uncovered_ksec = {c.value for c in KSECCategory} - set(_KSEC_LABEL_TH)
if _uncovered_ksec:
    raise AssertionError(f"_KSEC_LABEL_TH is missing label(s) for: {sorted(_uncovered_ksec)}")


def build_summarize_need_prompt(
    skill_names: list[str],
    sample_evidence: list[str],
    ksec: str,
    *,
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
        "- ความยาวไม่เกิน 2 บรรทัด\n"
        "- statement_th ต้องเป็นภาษาไทย ห้ามมีชื่อฟังก์ชัน ชื่อตัวแปร "
        "หรือโค้ดปนอยู่ (เช่น getDefault, get_default, obj.method) "
        "ชื่อเทคโนโลยีที่ใช้ในวงการจริง เช่น AI, ESG, Data Science ใช้ได้\n\n"
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
