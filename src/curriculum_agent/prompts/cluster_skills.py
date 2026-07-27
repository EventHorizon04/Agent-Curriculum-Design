from __future__ import annotations


def build_cluster_skills_prompt(skill_names: list[str]) -> list[dict[str, str]]:
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ทักษะแรงงาน\n"
        "จงจัดกลุ่มทักษะต่อไปนี้ตามความหมายและบริบทการใช้งาน "
        "ทักษะที่ใช้ในงานลักษณะเดียวกันหรือความหมายใกล้เคียงกันควรอยู่กลุ่มเดียวกัน\n\n"
        "กติกา:\n"
        "- ทุก index ต้องถูกจัดเข้ากลุ่มครั้งเดียวเท่านั้น ห้ามซ้ำ ห้ามตกหล่น\n"
        "- ห้ามใช้ index ที่ไม่มีในรายการ\n"
        "- จำนวนกลุ่มตามความเหมาะสมของข้อมูล (โดยทั่วไป 4-12 กลุ่ม)\n\n"
        "ตอบเป็น JSON object:\n"
        "{ clusters: [ { label_th: ชื่อกลุ่มภาษาไทยสั้นๆ, "
        "member_indices: [index ของทักษะในกลุ่มนี้] } ] }"
    )
    numbered = "\n".join(f"{i}: {name}" for i, name in enumerate(skill_names))
    user = f"รายการทักษะ (index: ชื่อทักษะ):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_merge_clusters_prompt(cluster_labels: list[str]) -> list[dict[str, str]]:
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ทักษะแรงงาน\n"
        "รายการต่อไปนี้คือชื่อกลุ่มทักษะที่ได้จากการจัดกลุ่มทีละชุด "
        "บางกลุ่มมีความหมายเดียวกันและควรรวมเป็นกลุ่มเดียว\n\n"
        "กติกา:\n"
        "- ทุก index ต้องปรากฏใน groups ครั้งเดียวเท่านั้น\n"
        "- ห้ามใช้ index ที่ไม่มีในรายการ\n"
        "- กลุ่มที่ไม่ซ้ำกับกลุ่มอื่นให้อยู่เดี่ยวๆ เป็น group ของตัวเอง\n\n"
        "ตอบเป็น JSON object:\n"
        "{ groups: [ [index ของกลุ่มที่ควรรวมเข้าด้วยกัน] ] }"
    )
    numbered = "\n".join(f"{i}: {label}" for i, label in enumerate(cluster_labels))
    user = f"รายการกลุ่มทักษะ (index: ชื่อกลุ่ม):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_merge_to_target_prompt(
    cluster_labels: list[str], target_count: int
) -> list[dict[str, str]]:
    """Merge semantically-close groups until exactly `target_count` remain."""
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ทักษะแรงงาน\n"
        "รายการต่อไปนี้คือชื่อกลุ่มทักษะภายในหมวดสมรรถนะเดียวกัน "
        f"จงรวมกลุ่มที่มีความหมายใกล้เคียงกันเข้าด้วยกัน ให้เหลือ {target_count} กลุ่มพอดี\n\n"
        "กติกา:\n"
        f"- ผลลัพธ์ต้องมี {target_count} group พอดี ไม่มากไม่น้อยกว่านี้\n"
        "- ทุก index ต้องปรากฏใน groups ครั้งเดียวเท่านั้น ห้ามตกหล่น ห้ามซ้ำ\n"
        "- ห้ามใช้ index ที่ไม่มีในรายการ\n"
        "- เลือกรวมกลุ่มที่ทำงานลักษณะเดียวกันหรือใช้ทักษะร่วมกันก่อน "
        "ห้ามรวมกลุ่มที่ไม่เกี่ยวข้องกันเพียงเพื่อให้ครบจำนวน\n\n"
        "ตอบเป็น JSON object:\n"
        "{ groups: [ [index ของกลุ่มที่ควรรวมเข้าด้วยกัน] ] }"
    )
    numbered = "\n".join(f"{i}: {label}" for i, label in enumerate(cluster_labels))
    user = f"รายการกลุ่มทักษะ (index: ชื่อกลุ่ม):\n{numbered}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
