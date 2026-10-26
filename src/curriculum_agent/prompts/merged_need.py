from __future__ import annotations

from curriculum_agent.prompts.summarize_need import (
    _BLOOM_LABEL_TH,
    _KSEC_LABEL_TH,
    MAX_RATIONALE_CHARS,
    MIN_RATIONALE_CHARS,
    NEED_SENTENCE_RULES_HEAD_TH,
    NEED_SENTENCE_RULES_TAIL_TH,
)


def build_merged_need_prompt(
    top_skill_names: list[str],
    ksec_tags: list[str],
    bloom_level: str,
    reason_th: str,
    *,
    program_context: str | None,
) -> list[dict[str, str]]:
    """One sentence for a Need merged from several Needs that ask for one capability.

    The rules are `build_summarize_need_prompt`'s own (`NEED_SENTENCE_RULES_*_TH`),
    because the answer is validated as `need_combination.NeedStatement` and has to
    be as usable as a PLO source as any other Need. What differs is the input:
    not one cluster's member names but the merged Need's **top skills** (the
    highest `importance_score` ones, at most `need_merge.TOP_SKILL_CAP`), plus the
    dedup model's `reason_th` for why the originals are one capability. The reason
    tells the model what to keep common between them; it is a hint, not a source,
    so the sentence is still forbidden from adding what the skills never named.

    `ksec_tags` may hold several tags ("K", "S"): the originals sat in different
    buckets, and the sentence has to be one requirement that still covers each.
    No designer note: a merge runs after the sentences were written under the
    note, and the note applies to the originals those sentences came from.
    """
    context_rule = (
        "- เขียนโดยตีความทักษะตามบริบทหลักสูตรที่ระบุ แต่บริบทนั้นใช้เลือกถ้อยคำเท่านั้น ห้ามเพิ่มเนื้อหาที่ไม่มีในกลุ่มทักษะ\n"
        if program_context
        else ""
    )
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ความต้องการที่มีต่อบัณฑิตและหลักสูตร\n"
        "ความต้องการหลายข้อของหลักสูตรนี้ถูกตรวจแล้วว่าถามหาสมรรถนะเดียวกัน "
        "จึงถูกรวมเป็นความต้องการข้อเดียว จากทักษะเด่นของความต้องการเหล่านั้นที่ให้มา "
        "จงเขียน 'ความต้องการ' หนึ่งประโยคที่ครอบสมรรถนะร่วมนั้น\n"
        "ประโยคนี้จะถูกนำไปเขียนเป็นผลลัพธ์การเรียนรู้ (PLO) หนึ่งข้อโดยตรง "
        "จึงต้องเจาะจงพอที่จะเขียน PLO ได้ทันทีโดยไม่ต้องเดาเนื้อหาเพิ่ม\n\n"
        "กติกา:\n"
        "- เหตุผลที่ตรวจพบว่าซ้ำกันใช้บอกว่าอะไรคือสิ่งร่วมของความต้องการเดิม ให้เขียนตามสิ่งร่วมนั้น "
        "แต่ห้ามเพิ่มงาน วัตถุ หรือบริบทที่ไม่มีในรายชื่อทักษะ\n"
        "- ความต้องการเดิมอาจอยู่คนละหมวด KSEC (เช่น ความรู้กับทักษะ) "
        "ประโยคเดียวต้องสะท้อนสมรรถนะที่ทั้งสองหมวดร่วมกัน "
        "ไม่ใช่เลือกเขียนหมวดใดหมวดหนึ่งแล้วทิ้งอีกหมวด\n"
        + NEED_SENTENCE_RULES_HEAD_TH
        + context_rule
        + NEED_SENTENCE_RULES_TAIL_TH
        + "\nตอบเป็น JSON object ที่มี field:\n"
        "  statement_th: string (ประโยคภาษาไทย)\n"
        "  statement_en: string (ประโยคภาษาอังกฤษ)\n"
        f"  rationale_th: string ({MIN_RATIONALE_CHARS}-{MAX_RATIONALE_CHARS} ตัวอักษร) "
        "บอกว่าทักษะเหล่านี้รวมกันเป็นความต้องการเดียวได้เพราะอะไร "
        "ต้องอ้างถึงหน้าที่หรืองานร่วมที่ทักษะเหล่านั้นใช้ทำ "
        "ห้ามตอบกว้าง ๆ ว่า 'เป็นทักษะที่เกี่ยวข้องกัน' หรือ 'อยู่ในสายงานเดียวกัน' "
        "และห้ามอ้างหลักฐานหรือแหล่งที่มาที่ไม่ได้อยู่ในรายชื่อทักษะที่ให้มา\n"
        "  supporting_indices: list[int] เลขลำดับของทักษะที่ประโยคนี้สะท้อนจริง "
        "การเว้นข้อที่ประโยคไม่ได้พูดถึงคือคำตอบที่ถูกต้อง\n"
        '  not_covered_indices: list ของ {"index": int, '
        '"reason_code": "low_freq" | "not_graduate" | "off_task", "note_th": string}\n'
    )
    labels = " + ".join(f"{_KSEC_LABEL_TH.get(tag, tag)} ({tag})" for tag in ksec_tags)
    bloom_label = _BLOOM_LABEL_TH.get(bloom_level, bloom_level)
    listed = "\n".join(f"{i} | {name}" for i, name in enumerate(top_skill_names))
    context_line = f"บริบทหลักสูตร: {program_context}\n" if program_context else ""
    user = (
        f"{context_line}"
        f"หมวดสมรรถนะของความต้องการเดิม: {labels}\n"
        f"ระดับที่ตลาดเรียกร้อง: {bloom_label} ({bloom_level})\n"
        f"เหตุผลที่รวม: {reason_th}\n"
        "ทักษะเด่น (เลขลำดับ | ทักษะ):\n"
        f"{listed}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
