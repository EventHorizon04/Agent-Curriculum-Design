from __future__ import annotations


def build_smart_validate_prompt(statement_th: str, context_th: str = "") -> list[dict]:
    """Run on LIGHT model as a separate validation pass after PLO/YLO generation."""
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้ตรวจสอบ SMART criteria สำหรับ PLO/YLO ในหลักสูตรระดับอุดมศึกษา "
                "ประเมินว่าข้อความผลลัพธ์การเรียนรู้นี้ผ่านเกณฑ์ SMART หรือไม่ "
                "(Specific, Measurable, Achievable, Relevant, Timely) "
                "พร้อมเหตุผลสั้น ๆ เป็นภาษาไทยสำหรับรายการที่ไม่ผ่าน"
            ),
        },
        {
            "role": "user",
            "content": (
                f"ข้อความ PLO/YLO:\n{statement_th}"
                + (f"\n\nบริบทเพิ่มเติม: {context_th}" if context_th else "")
            ),
        },
    ]
