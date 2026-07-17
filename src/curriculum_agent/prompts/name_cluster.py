from __future__ import annotations


def build_name_cluster_prompt(
    skill_keywords: list[str], sample_evidence: list[str]
) -> list[dict[str, str]]:
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ทักษะแรงงานในตลาด\n"
        "จากกลุ่มคีย์เวิร์ดทักษะที่ให้มา จงตั้งชื่อและอธิบาย skill cluster นี้\n\n"
        "ตอบเป็น JSON object ที่มี field:\n"
        "  canonical_name_th: string (ชื่อกลุ่มทักษะภาษาไทย กระชับ ≤8 คำ)\n"
        "  canonical_name_en: string (ชื่อภาษาอังกฤษ)\n"
        "  description_th: string (อธิบายสิ่งที่ผู้เรียนต้องทำได้ ≤3 ประโยค ภาษาไทย)\n"
        "  skill_type: string (knowledge|psychomotor|affective|mixed)\n"
        "  is_subject_specific: boolean (true=เฉพาะสาขา, false=ทั่วไป)\n"
        "  sample_quotes_th: array of string (อ้างอิงตรงจาก evidence ≤3 รายการ)"
    )

    keywords_str = ", ".join(skill_keywords[:30])
    evidence_str = "\n".join(f"- {q[:200]}" for q in sample_evidence[:5])

    user = f"คีย์เวิร์ดในกลุ่มนี้: {keywords_str}\n\nตัวอย่างข้อความ evidence:\n{evidence_str}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
