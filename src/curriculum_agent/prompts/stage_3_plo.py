from __future__ import annotations

from curriculum_agent.models import Need, ProgramMetadata


def build_plo_synthesis_prompt(
    metadata: ProgramMetadata,
    needs: list[Need],
) -> list[dict[str, str]]:
    need_summary = "\n".join(
        f"- [{n.need_id}] {n.statement_th} "
        f"(demand={n.demand_score:.2f}, evidence={len(n.source_evidence_ids)})"
        for n in needs
    )
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญด้านการออกแบบหลักสูตรตามแนว OBE (Outcome-Based Education) "
                "สร้าง PLO (Program Learning Outcomes) จำนวน 6-10 รายการ "
                "แต่ละ PLO ต้องมีกริยาแสดงพฤติกรรม Bloom ที่วัดได้ ไม่ใช้คำต้องห้าม "
                "(รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก) และผ่าน SMART"
            ),
        },
        {
            "role": "user",
            "content": (
                f"บริบทหลักสูตร:\n"
                f"- สาขาวิชา: {metadata.field}\n"
                f"- ระดับ: {metadata.degree_level} ({metadata.duration_years} ปี)\n"
                f"- มหาวิทยาลัย: {metadata.university} / คณะ: {metadata.faculty}\n"
                f"- วิสัยทัศน์: {metadata.vision_th}\n\n"
                f"Needs (สรุปจากหลักฐานผู้มีส่วนได้ส่วนเสีย):\n{need_summary}\n\n"
                "สังเคราะห์ PLO 6-10 รายการ พร้อม plo_id, statement_th, domain, "
                "ระดับตาม domain (cognitive → bloom_level, psychomotor → psychomotor_level, "
                "affective → krathwohl_level), "
                "action_verb_th, source_cluster_ids, และ rationale_th"
            ),
        },
    ]


def build_optional_plo_prompt(
    metadata: ProgramMetadata,
    needs: list[Need],
) -> list[dict[str, str]]:
    need_summary = "\n".join(f"- [{n.need_id}] {n.statement_th}" for n in needs)
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE สร้าง PLO เสริม (optional) จากทักษะประเภท want "
                "(ตลาดต้องการเพิ่มเติมแต่ไม่จำเป็นทุกคน) จำนวน 1-4 รายการ "
                "กติกาเดียวกับ PLO หลัก: กริยา Bloom วัดได้ ไม่ใช้คำต้องห้าม "
                "(รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก)"
            ),
        },
        {
            "role": "user",
            "content": (
                f"สาขาวิชา: {metadata.field} ระดับ {metadata.degree_level}\n"
                f"Want-based Needs:\n{need_summary}\n\n"
                "สังเคราะห์ PLO เสริม 1-4 รายการ พร้อม plo_id (นำหน้าด้วย OPT), statement_th, "
                "domain, ระดับตาม domain (cognitive → bloom_level, "
                "psychomotor → psychomotor_level, affective → krathwohl_level), "
                "action_verb_th, source_cluster_ids, rationale_th"
            ),
        },
    ]
