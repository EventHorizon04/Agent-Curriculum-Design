from __future__ import annotations


def build_extract_skills_prompt(evidence_text: str, classification: str) -> list[dict[str, str]]:
    system = (
        "คุณเป็นผู้เชี่ยวชาญวิเคราะห์ทักษะจากข้อความ\n"
        "จากข้อความ evidence จงระบุทักษะที่ตลาดแรงงานต้องการ\n"
        "ตอบเป็น JSON object: { skills: [ { "
        "skill_name_th: ชื่อทักษะภาษาไทย, "
        "skill_name_en: ชื่อทักษะภาษาอังกฤษมาตรฐาน "
        "(เช่น 'Python', 'Data Analysis', 'Communication') ห้ามเว้นว่าง, "
        "skill_type (knowledge|psychomotor|affective|mixed), "
        "is_subject_specific, "
        "bloom_level (remember|understand|apply|analyze|evaluate|create) "
        "— ระดับ Bloom's Taxonomy ด้าน Cognitive (Knowledge/Thinking) เท่านั้น "
        "ที่ทักษะนี้ต้องใช้ในการปฏิบัติงาน ไม่ต้องพิจารณา scale ของ psychomotor/affective, "
        "ksec_category (K|S|E|C) ตามกรอบ มคอ./TQF — "
        "K=ความรู้, S=ทักษะ (ทางปัญญา/ปฏิบัติ/ความสัมพันธ์ระหว่างบุคคล/วิเคราะห์ตัวเลข-สื่อสาร-IT), "
        "E=คุณธรรมจริยธรรม, C=คุณลักษณะบุคคล, "
        "confidence } ] }\n"
        "สกัดไม่เกิน 8 ทักษะต่อข้อความ เน้นทักษะที่วัดได้จริง"
    )
    user = f"[ประเภทหลักฐาน: {classification}]\n{evidence_text}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
