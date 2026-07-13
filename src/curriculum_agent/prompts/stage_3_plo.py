from __future__ import annotations

from curriculum_agent.models import ProgramMetadata, SkillCluster


def build_plo_synthesis_prompt(
    metadata: ProgramMetadata,
    clusters: list[SkillCluster],
) -> list[dict]:
    cluster_summary = "\n".join(
        f"- [{c.cluster_id}] {c.canonical_name_th}: {c.description_th} "
        f"(demand={c.demand_score:.2f}, evidence={len(c.source_evidence_ids)})"
        for c in clusters
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
                f"Skill clusters (สรุปจากหลักฐานผู้มีส่วนได้ส่วนเสีย):\n{cluster_summary}\n\n"
                "สังเคราะห์ PLO 6-10 รายการ พร้อม plo_id, statement_th, domain, bloom_level/krathwohl_level, "
                "action_verb_th, source_cluster_ids, และ rationale_th"
            ),
        },
    ]
