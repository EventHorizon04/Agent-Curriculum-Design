from __future__ import annotations


def build_smart_soft_judge_prompt(
    statement_th: str,
    degree_level: str,
    duration_years: int,
    need_statements_th: list[str],
) -> list[dict[str, str]]:
    """Light-model soft checks against the project's SMART rubric.

    Five verdicts, none of which block: the hard checks in smart_rules.py drive
    escalation on their own. What the model is asked reflects the rubric's own
    definitions — Measurable is about whether a real assessment instrument could
    observe the outcome, not merely whether a forbidden word is absent, and
    Relevant is judged against the Needs the PLO cites rather than against a vision
    statement. The institutional half of Relevant is settled in code from
    Need.source_stakeholder_types.

    Time-bound defaults to true: a PLO carries "by the end of the program" by
    convention, so silence about time is correct and only a conflicting horizon is
    a finding.
    """
    system = (
        "คุณเป็นผู้ตรวจสอบคุณภาพ PLO ตามเกณฑ์ SMART ประเมิน 5 ข้อ ตอบเป็น JSON:\n"
        "specific_object_ok: กรรมของกริยาเจาะจง ระบุพฤติกรรม/ทักษะ/สมรรถนะที่ชัดเจน "
        "ไม่ใช่คำกว้างเช่น 'ความรู้' 'ทักษะที่จำเป็น'\n"
        "measurable_ok: สังเกตได้ และประเมินได้จริงด้วยเครื่องมือทางการศึกษา "
        "(ข้อสอบ ชิ้นงาน การปฏิบัติ แฟ้มผลงาน) — การไม่มีคำห้ามยังไม่นับว่าวัดได้\n"
        "achievable_ok: ระดับ Bloom สมเหตุสมผลกับระดับคุณวุฒิ และบรรลุได้ภายในระยะเวลาหลักสูตร\n"
        "relevant_needs_ok: ตอบสนองความต้องการของผู้มีส่วนได้ส่วนเสียที่อ้างถึงจริง "
        "และสะท้อนสมรรถนะที่ตลาดแรงงานต้องการ\n"
        "time_bound_ok: ค่าเริ่มต้นเป็น true — PLO ถือว่าบรรลุ 'เมื่อสิ้นสุดหลักสูตร' โดยปริยาย "
        "ให้ตอบ false เฉพาะเมื่อข้อความระบุกรอบเวลาอื่นที่ขัดกัน เช่น 'ภายในปีที่ 2'\n"
        "notes_th: เหตุผลสั้นๆ สำหรับข้อที่ไม่ผ่าน"
    )
    user = f"PLO: {statement_th}\nระดับคุณวุฒิ: {degree_level}\nระยะเวลาหลักสูตร: {duration_years} ปี"
    if need_statements_th:
        joined = "\n".join(f"- {n}" for n in need_statements_th)
        user += f"\nNeed ที่อ้างถึง:\n{joined}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
