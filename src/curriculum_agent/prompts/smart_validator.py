from __future__ import annotations


def build_smart_soft_judge_prompt(
    statement_th: str, vision_th: str, degree_level: str
) -> list[dict]:
    """Light-model soft checks: S object quality, A level plausibility, R vision alignment."""
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้ตรวจสอบคุณภาพ PLO ประเมิน 3 ข้อ ตอบเป็น JSON:\n"
                "specific_object_ok: กรรมของกริยาเจาะจง (ไม่ใช่คำกว้างเช่น 'ความรู้' 'ทักษะที่จำเป็น')\n"
                "achievable_ok: ระดับ Bloom เหมาะกับระดับปริญญา\n"
                "relevant_alignment_ok: สอดคล้องกับวิสัยทัศน์หลักสูตร\n"
                "notes_th: เหตุผลสั้นๆ สำหรับข้อที่ไม่ผ่าน"
            ),
        },
        {
            "role": "user",
            "content": (f"PLO: {statement_th}\nระดับปริญญา: {degree_level}\nวิสัยทัศน์: {vision_th}"),
        },
    ]
