from __future__ import annotations

from curriculum_agent.models import PLO, ProgramMetadata, FORBIDDEN_WORDS_TH


def build_ylo_derivation_prompt(
    metadata: ProgramMetadata,
    plo: PLO,
    avoid_words: set[str] | None = None,
) -> list[dict]:
    avoid_note = ""
    if avoid_words:
        avoid_note = f"\n\n**ห้ามใช้คำเหล่านี้เด็ดขาด:** {', '.join(sorted(avoid_words))}"

    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญด้านการออกแบบ Year Learning Outcomes (YLO) "
                "สร้าง YLO สำหรับแต่ละปีของหลักสูตร โดย Bloom level ต้องเพิ่มขึ้นตามปี "
                "(monotonically non-decreasing) และไม่ใช้คำต้องห้าม"
                + avoid_note
            ),
        },
        {
            "role": "user",
            "content": (
                f"หลักสูตร {metadata.duration_years} ปี — {metadata.field}\n\n"
                f"PLO: [{plo.plo_id}] {plo.statement_th}\n"
                f"Domain: {plo.domain.value}, "
                f"Bloom (graduation): {plo.bloom_level.value if plo.bloom_level else plo.krathwohl_level.value if plo.krathwohl_level else 'N/A'}\n\n"
                f"สร้าง YLO สำหรับปีที่ 1-{metadata.duration_years} "
                "แต่ละปีต้องมี ylo_id, year, statement_th, bloom_level/krathwohl_level, action_verb_th, และ rationale_th"
                + avoid_note
            ),
        },
    ]
