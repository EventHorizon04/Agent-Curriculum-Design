from __future__ import annotations


def build_extract_metadata_prompt(doc_text: str) -> list[dict[str, str]]:
    system = (
        "คุณเป็นผู้ช่วยสกัดข้อมูลจากเอกสารของมหาวิทยาลัยไทย\n"
        "จงอ่านเนื้อหาเอกสารแล้วสกัดข้อมูล 4 รายการต่อไปนี้ (ถ้ามี):\n"
        "  vision_th: วิสัยทัศน์ (ของมหาวิทยาลัยหรือหลักสูตร)\n"
        "  mission_th: พันธกิจ\n"
        "  institutional_identity_th: เอกลักษณ์สถาบัน\n"
        "  student_identity_th: อัตลักษณ์บัณฑิต/อัตลักษณ์นักศึกษา\n\n"
        "กติกาสำคัญ:\n"
        "- คัดลอกหรือเรียบเรียงจากเนื้อหาที่ปรากฏในเอกสารเท่านั้น\n"
        "- ถ้าไม่พบข้อมูลรายการใดในเอกสาร ให้ตอบรายการนั้นเป็น null\n"
        "- ห้ามแต่งหรือเดาข้อมูลที่ไม่มีในเอกสารเด็ดขาด\n"
        "- ตอบเป็นภาษาไทยตามต้นฉบับ\n\n"
        "ตอบเป็น JSON object ที่มี field: vision_th, mission_th, "
        "institutional_identity_th, student_identity_th (string หรือ null)"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"เนื้อหาเอกสาร:\n{doc_text}"},
    ]
