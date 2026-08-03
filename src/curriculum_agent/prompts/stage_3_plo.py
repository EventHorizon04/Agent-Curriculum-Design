from __future__ import annotations

from curriculum_agent.models import Need, ProgramMetadata
from curriculum_agent.prompts.designer_note import NOTE_POLICY_TH, append_note


def build_plo_from_need_prompt(
    metadata: ProgramMetadata, needs: list[Need], *, note_th: str | None = None
) -> list[dict[str, str]]:
    """Restate one or more market Needs as a single graduate-side PLO.

    Takes a list because the designer may merge several Needs into one PLO; the
    1:1 stage path passes a single-element list.
    """
    plural = len(needs) > 1
    system = (
        "คุณเป็นผู้เชี่ยวชาญ OBE ตามมาตรฐาน MHESI\n"
        + (
            "จงรวม 'ความต้องการของตลาด' ที่ให้มาทั้งหมด ให้เป็น PLO เพียงหนึ่งข้อ\n\n"
            if plural
            else "จงแปลง 'ความต้องการของตลาด' หนึ่งข้อ ให้เป็น PLO หนึ่งข้อ\n\n"
        )
        + "กติกา:\n"
        "- เขียนจากมุมผู้เรียน: 'บัณฑิตทำอะไรได้' ไม่ใช่ 'ตลาดต้องการอะไร'\n"
        "- ใช้คำกริยาแสดงพฤติกรรมตาม Bloom เพียง 1 คำ\n"
        "- ห้ามใช้คำที่วัดไม่ได้: รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก\n"
        "- ต้องระบุวัตถุของกริยาให้เจาะจง ห้ามใช้คำกว้างเช่น 'ความรู้ที่จำเป็น'\n"
        "- source_need_ids ต้องเป็น need_id ที่ให้มาทั้งหมด ห้ามเพิ่มหรือตัดทิ้ง\n"
        + ("- ต้องครอบคลุมสาระของทุกความต้องการที่ให้มา ห้ามละข้อใดข้อหนึ่ง\n" if plural else "")
        + "\nตอบเป็น JSON object ที่มี field: plo (object) โดย plo มี field:\n"
        "  statement_th, statement_en, bloom_level,\n"
        "  action_verb_th, source_need_ids, rationale_th, distinctive_feature_th\n"
        "(ไม่ต้องระบุ evidence ใด ๆ — ระบบจะผูก evidence จาก need ที่ให้มาเอง)\n\n" + NOTE_POLICY_TH
    )
    need_block = "\n\n".join(
        f"need_id: {n.need_id}\n"
        f"ความต้องการของตลาด: {n.statement_th}\n"
        f"หมวดสมรรถนะ: {n.ksec_category.value}\n"
        f"ระดับ Bloom ที่เหมาะสม: {n.bloom_level.value}\n"
        f"ความถี่ที่ถูกกล่าวถึง: {n.freq} ครั้ง (demand {n.demand_score})"
        for n in needs
    )
    user = (
        f"หลักสูตร: {metadata.name_th} ({metadata.degree_level}, {metadata.duration_years} ปี)\n"
        f"สาขา: {metadata.field}\n\n"
        f"{need_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": append_note(user, note_th)},
    ]
