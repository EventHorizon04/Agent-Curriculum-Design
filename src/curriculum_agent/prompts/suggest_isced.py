from __future__ import annotations

from curriculum_agent.data.isced import all_detailed_fields


def build_suggest_isced_prompt(
    name_th: str,
    name_en: str,
    field: str,
    retry_invalid_code: str | None = None,
) -> list[dict[str, str]]:
    field_list = "\n".join(f"{f.code}\t{f.name_en}" for f in all_detailed_fields())

    system_parts = [
        "คุณเป็นผู้เชี่ยวชาญด้านการจำแนกหลักสูตรอุดมศึกษาตามมาตรฐาน ISCED-F 2013 (UNESCO)\n"
        "จงจำแนกหลักสูตรที่ได้รับเข้ารหัส ISCED detailed field (4 หลัก) "
        "และแนะนำชื่อหลักสูตรมาตรฐาน\n\n"
        "รายการรหัส ISCED detailed field ที่เลือกได้ (code<TAB>ชื่อภาษาอังกฤษ):\n"
        f"{field_list}\n\n"
        "กติกาสำคัญ:\n"
        "- ต้องเลือก isced_code จากรายการข้างต้นเท่านั้น ห้ามสร้างรหัสขึ้นเอง\n"
        "- suggested_names: แนะนำชื่อหลักสูตรมาตรฐาน 2-3 ชื่อ ตามแบบแผนการตั้งชื่อ"
        'หลักสูตร/ปริญญาไทย (เช่น "หลักสูตรวิทยาศาสตรบัณฑิต สาขาวิชา...") '
        'คู่กับชื่อภาษาอังกฤษ (เช่น "Bachelor of Science Program in ...")\n'
        "- rationale_th: เหตุผลสั้น ๆ ไม่เกิน 2 ประโยค\n"
    ]

    if retry_invalid_code is not None:
        system_parts.append(
            f'\nครั้งก่อนคุณตอบ isced_code = "{retry_invalid_code}" ซึ่งไม่อยู่ในรายการข้างต้น '
            "กรุณาเลือกรหัสใหม่จากรายการเท่านั้น"
        )

    user = f"ชื่อหลักสูตร (ไทย): {name_th}\nชื่อหลักสูตร (อังกฤษ): {name_en}\nสาขาวิชา: {field}"

    return [
        {"role": "system", "content": "".join(system_parts)},
        {"role": "user", "content": user},
    ]
