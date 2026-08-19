from __future__ import annotations

from curriculum_agent.models import BloomLevel, KSECCategory
from curriculum_agent.prompts.designer_note import NOTE_POLICY_TH, append_note

# The lower bound the prompt states and _NeedStatement enforces. Kept here so the
# instruction the model reads and the rule that rejects its answer cannot drift.
MIN_STATEMENT_CHARS = 40

_KSEC_LABEL_TH: dict[str, str] = {
    "K": "ความรู้",
    "S": "ทักษะ",
    "EC": "คุณธรรมจริยธรรมและคุณลักษณะบุคคล",
    "E": "คุณธรรมจริยธรรม",
    "C": "คุณลักษณะบุคคล",
}

# How hard the market's ask is, in words. Glossed rather than left as the raw
# English code because the surrounding prompt is Thai, and phrased to avoid
# รู้/จำ/เข้าใจ — FORBIDDEN_WORDS_TH — so a model echoing the label back cannot
# plant an unmeasurable verb in the Need and from there in the PLO.
_BLOOM_LABEL_TH: dict[str, str] = {
    "remember": "ระบุและเรียกคืนข้อมูลได้",
    "understand": "อธิบายและตีความได้",
    "apply": "ประยุกต์ใช้ในงานจริงได้",
    "analyze": "วิเคราะห์แยกแยะได้",
    "evaluate": "ประเมินและตัดสินใจได้",
    "create": "สร้างและออกแบบสิ่งใหม่ได้",
}

# Plain dicts have no structural link to the enums they mirror, so nothing stops
# the two from drifting apart the next time a member is added, removed, or
# renamed. These assertions turn that drift into an import-time crash instead of
# a label that silently falls back to the raw code below — they are what makes
# the .get(...) fallbacks provably unreachable for every real enum value, not
# just today's.
_uncovered_ksec = {c.value for c in KSECCategory} - set(_KSEC_LABEL_TH)
if _uncovered_ksec:
    raise AssertionError(f"_KSEC_LABEL_TH is missing label(s) for: {sorted(_uncovered_ksec)}")

_uncovered_bloom = {b.value for b in BloomLevel} - set(_BLOOM_LABEL_TH)
if _uncovered_bloom:
    raise AssertionError(f"_BLOOM_LABEL_TH is missing label(s) for: {sorted(_uncovered_bloom)}")


def build_summarize_need_prompt(
    skill_names: list[str],
    ksec: str,
    bloom_level: str,
    *,
    note_th: str | None = None,
) -> list[dict[str, str]]:
    """Turn one group of related skills into a single market-demand sentence.

    Sees the extracted skills and nothing else. Evidence text used to be pasted in
    as samples; it is gone on purpose — the skills already carry what extraction
    found in that evidence, and the raw quotes only gave the light model longer
    Thai to drift on. Traceability is unaffected: a Need's source_evidence_ids
    still come from its member skills.

    The sentence becomes exactly one PLO downstream, so the rules below ask for
    the three parts a PLO needs (capability, specific object, work context) at
    the group's Bloom level, and name the two degenerate shapes — a vague
    placeholder and a comma-joined skill list — that _NeedStatement rejects.
    """
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ความต้องการของตลาดแรงงาน\n"
        "จากกลุ่มทักษะที่ให้มา จงสรุปเป็น 'ความต้องการของตลาด' หนึ่งประโยค\n"
        "ประโยคนี้จะถูกนำไปเขียนเป็นผลลัพธ์การเรียนรู้ (PLO) หนึ่งข้อโดยตรง "
        "จึงต้องเจาะจงพอที่จะเขียน PLO ได้ทันทีโดยไม่ต้องเดาเนื้อหาเพิ่ม\n\n"
        "กติกา:\n"
        "- เขียนเป็นประโยคเดียว มุมมองของ 'ตลาดแรงงานต้องการอะไร' "
        "ไม่ใช่มุมมองผู้เรียนหรือผลลัพธ์การเรียนรู้\n"
        "- ต้องมีครบ 3 ส่วน: (1) ความสามารถที่ลงมือทำได้จริง "
        "(2) วัตถุหรือผลงานที่เจาะจง (3) บริบทของงานที่ใช้ความสามารถนั้น\n"
        "- หนึ่งประโยคคือหนึ่งสมรรถนะ ห้ามยัดหลายเรื่องที่ไม่เกี่ยวกันไว้ในประโยคเดียว\n"
        "- ระดับความยากต้องตรงกับระดับ Bloom ที่ระบุให้ ไม่สูงหรือต่ำกว่านั้น\n"
        "- ห้ามใช้คำกว้างที่ไม่บอกว่าคืออะไร เช่น 'ทักษะที่จำเป็น' "
        "'ความรู้ที่เกี่ยวข้อง' 'สมรรถนะด้านต่างๆ'\n"
        "- ห้ามวนกลับมาพูดว่า 'ตามที่ตลาดต้องการ' ต้องบอกให้ชัดว่าตลาดต้องการอะไร\n"
        "- ห้ามเป็นเพียงการนำชื่อทักษะมาต่อกันด้วยเครื่องหมายจุลภาค "
        "(ใช้จุลภาคได้ไม่เกิน 2 ตัว)\n"
        f"- ความยาว 1-2 บรรทัด และต้องไม่สั้นกว่า {MIN_STATEMENT_CHARS} ตัวอักษร\n"
        "- statement_th ต้องเป็นภาษาไทย ห้ามมีชื่อฟังก์ชัน ชื่อตัวแปร "
        "หรือโค้ดปนอยู่ (เช่น getDefault, get_default, obj.method) "
        "ชื่อเทคโนโลยีที่ใช้ในวงการจริง เช่น AI, ESG, Data Science ใช้ได้\n\n"
        "ตอบเป็น JSON object ที่มี field:\n"
        "  statement_th: string (ประโยคภาษาไทย)\n"
        "  statement_en: string (ประโยคภาษาอังกฤษ)\n\n" + NOTE_POLICY_TH
    )
    label = _KSEC_LABEL_TH.get(ksec, ksec)
    bloom_label = _BLOOM_LABEL_TH.get(bloom_level, bloom_level)
    keywords = ", ".join(skill_names[:30])
    user = (
        f"หมวดสมรรถนะ: {label} ({ksec})\n"
        f"ระดับที่ตลาดเรียกร้อง: {bloom_label} ({bloom_level})\n"
        f"ทักษะในกลุ่มนี้: {keywords}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": append_note(user, note_th)},
    ]
