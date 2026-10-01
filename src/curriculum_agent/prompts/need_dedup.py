from __future__ import annotations

_SYSTEM_TH = """คุณคือผู้เชี่ยวชาญการออกแบบหลักสูตรอุดมศึกษาไทยตามแนวทาง Outcome-Based Education

งานของคุณ: อ่านรายการความต้องการ (Need) ของหลักสูตรหนึ่ง แล้วหาว่าข้อใดถามหาสมรรถนะเดียวกันของบัณฑิต จนผลลัพธ์การเรียนรู้ระดับหลักสูตร (PLO) ข้อเดียวรองรับได้โดยไม่ทิ้งสิ่งที่ข้อใดข้อหนึ่งขอ

กติกา:
1. Need สองข้อซ้ำกันเมื่องานหลักและวัตถุหลักเหมือนกัน แม้ถ้อยคำหรือบริบทต่างกัน เช่น "แปลเอกสารธุรกิจโดยใช้เทคโนโลยี" กับ "ประยุกต์ใช้เทคโนโลยีในการแปลเอกสารธุรกิจ" การพูดถึงหัวข้อเดียวกัน ใช้เครื่องมือเดียวกัน (เช่น AI หรือเทคโนโลยีดิจิทัล) หรือมาจากกลุ่มผู้มีส่วนได้ส่วนเสียเดียวกัน ยังไม่พอ
2. Need หนึ่งข้ออยู่ได้ไม่เกินหนึ่งกลุ่ม
3. หนึ่งกลุ่มมี 2-3 ข้อ และทุกข้อในกลุ่มต้องอยู่ในหมวด KSEC เดียวกัน
4. ข้อที่ไม่ซ้ำกับข้อใดเลยไม่ต้องใส่ในกลุ่มใด ถ้าไม่มีข้อใดซ้ำกันเลย ให้ตอบ groups เป็นรายการว่าง ซึ่งเป็นคำตอบที่ถูกต้องสำหรับชุดที่แยกกันชัดเจน
5. บางข้ออาจเป็นรายชื่อทักษะที่ยังไม่ได้เรียบเรียงเป็นประโยค ให้ตัดสินจากงานที่รายชื่อนั้นบอก
6. อ้างถึง Need ด้วยป้ายกำกับ (N1, N2, ...) เท่านั้น
7. reason_th: หนึ่งประโยคภาษาไทย บอกงานหลักและวัตถุหลักที่สมาชิกในกลุ่มมีร่วมกัน

ตอบเป็น JSON ตาม schema ที่กำหนด"""  # noqa: E501


def build_need_dedup_prompt(
    rows: list[tuple[str, str, str]],
    *,
    program_context: str | None = None,
) -> list[dict[str, str]]:
    """Ask which Needs in one program ask for the same graduate capability.

    `rows` is `(label, ksec_tag, statement_th)` in the order the caller wants
    them read — demand order, so N1 is the most-demanded Need. Labels, not
    `need_id`s: a UUID is 36 characters the model has to copy exactly, and a
    miscopied one is a group the code cannot map back. `supporting_indices` in
    summarize_need showed short indices are what a model returns reliably.

    Every structural rule here (2-3 members, one KSEC tag, one group per Need)
    is enforced again by `stages.need_dedup.accept_groups`, which drops a group
    that breaks one. The prompt states them anyway, because a group dropped for
    a rule the model never saw is a duplicate that ships as two PLOs.

    Rule 1 defines a duplicate as the same main task and main object, the
    checkable definition the 2026-09-29 pipeline proposal gives for set-level
    redundancy, with its example pair. It also carries the lesson of the
    measurement in the design doc: on the stored run, Needs drawn from the same
    few documents shared up to 55% of their evidence while asking for different
    things, so "same topic, same tool, same source" is named as not enough.
    Rule 4 exists because a model asked to find duplicates otherwise finds some.

    `program_context` is `build_program_context_th`'s line; None says nothing.
    """
    context = f"หลักสูตร: {program_context}\n\n" if program_context else ""
    listing = "\n".join(f"{label} | {tag} | {statement}" for label, tag, statement in rows)
    user = f"{context}รายการความต้องการ (ป้ายกำกับ | หมวด KSEC | ประโยค):\n{listing}"
    return [
        {"role": "system", "content": _SYSTEM_TH},
        {"role": "user", "content": user},
    ]
