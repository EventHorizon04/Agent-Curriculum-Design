from __future__ import annotations


def build_cluster_bloom_prompt(
    name_th: str,
    description_th: str,
    skill_names: list[str],
    skill_type: str,
) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE จัดระดับกลุ่มทักษะตาม Bloom's Taxonomy "
                "(remember|understand|apply|analyze|evaluate|create) "
                "หรือ Krathwohl (receiving|responding|valuing|organization|characterization) "
                "สำหรับกลุ่ม affective เท่านั้น "
                "และยืนยันว่าเป็นทักษะเฉพาะสาขา (specific) หรือทักษะทั่วไป (generic) "
                "ตอบเป็น JSON ตาม schema"
            ),
        },
        {
            "role": "user",
            "content": (
                f"กลุ่มทักษะ: {name_th}\n"
                f"คำอธิบาย: {description_th}\n"
                f"ประเภท: {skill_type}\n"
                f"ทักษะสมาชิก: {', '.join(skill_names[:10])}"
            ),
        },
    ]
