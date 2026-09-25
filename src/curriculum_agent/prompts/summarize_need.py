from __future__ import annotations

from curriculum_agent.models import BloomLevel, KSECCategory
from curriculum_agent.prompts.designer_note import NOTE_POLICY_TH, append_note

# The lower bound the prompt states and _NeedStatement enforces. Kept here so the
# instruction the model reads and the rule that rejects its answer cannot drift.
MIN_STATEMENT_CHARS = 40

# Bounds on rationale_th, here for the same reason. It is an explanation of why
# one skill group is one demand, so it needs room for a clause of substance and
# no more: it rides on every Need row, renders inside a card beside the sentence
# it explains, and is asked for on every call of the stage that writes a Need.
# The floor is what a real reason costs; a model that has nothing to say answers
# under it rather than padding.
MIN_RATIONALE_CHARS = 20
MAX_RATIONALE_CHARS = 240

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
    program_context: str | None = None,
) -> list[dict[str, str]]:
    """Turn one group of related skills into a single market-demand sentence.

    `program_context` is the program's field and degree level, from intake — the
    only thing here that says which program the sentence is for. It settles the
    wording a bare skill name leaves open ("การดูแล" in a nursing program is not
    the same demand as in an engineering one) and nothing more: the rule below
    forbids adding a capability the skill group never named, because the PLO
    drafted from this sentence has to trace to the evidence behind those skills.

    Sees the extracted skills and nothing else. Evidence text used to be pasted in
    as samples; it is gone on purpose — the skills already carry what extraction
    found in that evidence, and the raw quotes only gave the model longer
    Thai to drift on. Traceability is unaffected: a Need's source_evidence_ids
    still come from its member skills.

    The sentence becomes exactly one PLO downstream, so the rules below ask for
    the three parts a PLO needs (capability, specific object, work context) at
    the group's Bloom level, and name the two degenerate shapes — a vague
    placeholder and a joined skill list — that _NeedStatement rejects. The list
    rule names both punctuations on purpose: the Thai one (spaces closed by "และ")
    is the shape a Thai-first model actually produces, and the guard that only
    counted commas was really only catching the list written the English way.

    What the rules no longer ask for is a fixed opening. "ตลาดแรงงานต้องการ..."
    used to be mandatory; it carried nothing the rest of the sentence did not and
    spent characters against a 40-character floor, so several framings are now
    offered — "ต้องการบัณฑิตที่...", "ต้องการหลักสูตรที่...", "บัณฑิตต้องมี...".
    The boundary that opening used to carry is stated on its own instead: the
    sentence may be a requirement, but not a finished PLO. plo_synthesis is
    handed nothing but this sentence, so a Need already written as
    "บัณฑิตวิเคราะห์...ได้" leaves that stage nothing to do but copy, and the
    report can no longer show the step from what was asked for to what a graduate
    must therefore be able to do.

    Three rules guard the opposite failure, where the sentence is a legitimate
    demand that has been generalised until it is nobody's in particular: don't
    dilute a specialised group into a generic competency, name the professional
    function rather than the generic skill covering it, and — the check that
    catches what the other two miss — ask whether a reader could still tell which
    profession this demand belongs to with the field name removed. The last one
    cannot be pure code: "ทักษะการสื่อสาร" passes every guard in need_grouping
    (long enough, no list, no vague head/modifier pair) and is still a Need that
    could belong to any program in the country, which is exactly what the ceiling
    of ten core PLOs makes expensive. They come from
    prompts/guidances/market_need_synthesis.md rules 1, 7 and 8; that document's
    own examples write the subject as "ผู้ปฏิบัติงาน", which is deliberately not
    adopted — the openings above are a decision this repo already made, and
    changing the subject is a separate call, not a side effect of taking three
    rules about specificity. That call was made on 2026-09-18 and the answer was
    to keep บัณฑิต/หลักสูตร; `.scratch/prompt-guidances/issues/01` records why,
    and a test asserts "ผู้ปฏิบัติงาน" stays out of this prompt.

    One rule pushes the other way, and it is the only one that does. Every rule
    above drives toward a sentence specific enough to draft a PLO from, and none
    of them has a lower bound — so nothing stopped a Need from naming one task
    inside a profession's work ("แปลสัญญาซื้อขายสินค้า") while satisfying all of
    them. That matters because a Need becomes exactly one PLO and a program has
    ten core slots: a Need worth less than a tenth of the program spends one
    anyway. The boundary is written as a property of the sentence's **object** —
    a class of work the graduate repeats across situations, not one instance of
    it — precisely so it cannot be satisfied by writing more vaguely, which is
    the failure the three rules above exist to prevent. The prompt says that
    outright, because a model told "too narrow" will otherwise reach for
    "ทักษะการสื่อสาร".

    `rationale_th` is asked for alongside the sentence rather than in a second
    call, because the reason a group is one demand is what the model is already
    deciding while it writes the sentence — asked afterwards it would be
    reconstructed from the sentence rather than from the group. It is an
    explanation, **not** part of the evidence trail: `Need.source_evidence_ids`
    is code-owned and carries that, while this is free text nothing can check
    against the evidence. The prompt therefore forbids citing anything outside
    the skill names it was given, and the rules that reject an empty answer reuse
    `find_vague_phrase` rather than inventing a second vocabulary — "เป็นทักษะที่
    เกี่ยวข้องกัน" is caught by the same pattern that catches it in a statement.
    """
    # Only added alongside a context line: without one there is nothing to
    # over-read, and the rule would be an instruction about a field the prompt
    # never named.
    context_rule = (
        "- เขียนโดยตีความทักษะตามบริบทหลักสูตรที่ระบุ แต่บริบทนั้นใช้เลือกถ้อยคำเท่านั้น ห้ามเพิ่มเนื้อหาที่ไม่มีในกลุ่มทักษะ\n"
        if program_context
        else ""
    )
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการวิเคราะห์ความต้องการที่มีต่อบัณฑิตและหลักสูตร\n"
        "จากกลุ่มทักษะที่ให้มา จงสรุปเป็น 'ความต้องการ' หนึ่งประโยค\n"
        "ประโยคนี้จะถูกนำไปเขียนเป็นผลลัพธ์การเรียนรู้ (PLO) หนึ่งข้อโดยตรง "
        "จึงต้องเจาะจงพอที่จะเขียน PLO ได้ทันทีโดยไม่ต้องเดาเนื้อหาเพิ่ม\n\n"
        "กติกา:\n"
        "- เขียนเป็นประโยคเดียวที่ระบุ 'ข้อกำหนด' ขึ้นต้นได้หลายแบบ เช่น "
        "'ต้องการ...' 'ต้องการบัณฑิตที่...' 'ต้องการหลักสูตรที่...' หรือ 'บัณฑิตต้องมี...' "
        "เลือกแบบที่อ่านเป็นธรรมชาติที่สุดกับเนื้อหา ไม่ต้องใช้แบบเดียวกันทุกข้อ\n"
        "- ห้ามเขียนเป็นผลลัพธ์การเรียนรู้ (PLO) ที่เสร็จรูปแล้ว เช่น 'บัณฑิตวิเคราะห์...ได้' "
        "ประโยคนี้คือสิ่งที่ถูกเรียกร้อง ส่วนการแปลงเป็น PLO เป็นขั้นถัดไป\n"
        "- ต้องมีครบ 3 ส่วน: (1) ความสามารถที่ลงมือทำได้จริง "
        "(2) วัตถุหรือผลงานที่เจาะจง (3) บริบทของงานที่ใช้ความสามารถนั้น "
        "ตัวอย่างที่ครบทั้งสามส่วน: "
        "'ต้องการบัณฑิตที่ประเมินและปรับปรุงผลลัพธ์การแปลเอกสารธุรกิจระหว่างประเทศ "
        "ในบริบทการสื่อสารไทย-จีน'\n"
        "- หนึ่งประโยคคือหนึ่งสมรรถนะ ห้ามยัดหลายเรื่องที่ไม่เกี่ยวกันไว้ในประโยคเดียว\n"
        "- ประโยคนี้จะใช้สล็อต PLO ของทั้งหลักสูตรไป 1 ข้อจาก 10 ข้อ "
        "จึงต้องครอบ 'ประเภทของงาน' ที่บัณฑิตทำซ้ำได้หลายสถานการณ์ในสายวิชาชีพนั้น "
        "ไม่ใช่ภารกิจย่อยชิ้นเดียวภายในประเภทนั้น "
        "เช่น 'แปลและตรวจสอบเอกสารสัญญาทางธุรกิจ' อยู่ในระดับหลักสูตร "
        "แต่ 'แปลสัญญาซื้อขายสินค้า' แคบเกินไป เป็นงานหนึ่งชิ้นในประเภทเดียวกัน\n"
        "  ข้อนี้คุมเฉพาะ 'ขอบเขตของวัตถุ' ไม่ได้อนุญาตให้เขียนกว้างลอย ๆ "
        "การแก้ประโยคที่แคบเกินคือขยายให้ครอบประเภทของงาน ไม่ใช่ตัดรายละเอียดทิ้ง\n"
        "- ระดับความยากต้องตรงกับระดับ Bloom ที่ระบุให้ ไม่สูงหรือต่ำกว่านั้น\n"
        + context_rule
        + "- ห้ามใช้คำกว้างที่ไม่บอกว่าคืออะไร เช่น 'ทักษะที่จำเป็น' "
        "'ความรู้ที่เกี่ยวข้อง' 'สมรรถนะด้านต่างๆ' 'ความสามารถทางวิชาชีพ' 'ทักษะการทำงาน'\n"
        "- ห้ามลดทอนทักษะเฉพาะทางในกลุ่มให้เหลือเป็นสมรรถนะทั่วไป "
        "กลุ่ม 'การแปลสัญญา การจัดการคำศัพท์เฉพาะ' สรุปเป็น 'ทักษะการสื่อสาร' ไม่ได้ "
        "ต้องคงหน้าที่ทางวิชาชีพที่กลุ่มทักษะบอกไว้ เช่น 'แปลและตรวจสอบเอกสารสัญญาทางธุรกิจ'\n"
        "- เมื่อกลุ่มทักษะชี้ถึงหน้าที่ทางวิชาชีพ ให้เขียนด้วยหน้าที่นั้น ไม่ใช่ทักษะทั่วไปที่ครอบมันอยู่ "
        "เขียน 'ล่ามการเจรจาธุรกิจ' ไม่ใช่ 'การสื่อสาร' เขียน 'ตรวจแก้ผลลัพธ์จาก AI' ไม่ใช่ 'การใช้เทคโนโลยี' "
        "ยกเว้นกลุ่มทักษะนั้นพูดถึงสมรรถนะทั่วไปโดยตรงอยู่แล้ว\n"
        "- ห้ามวนกลับมาพูดว่า 'ตามที่ตลาดต้องการ' ต้องบอกให้ชัดว่าต้องการอะไร\n"
        "- ห้ามเป็นเพียงการนำชื่อทักษะมาต่อกัน ทั้งแบบใช้เครื่องหมายจุลภาค "
        "(ใช้จุลภาคได้ไม่เกิน 2 ตัว) และแบบไทยที่เว้นวรรคแล้วปิดท้ายด้วย 'และ' "
        "เช่น 'ต้องการการใช้ AI การแปล และการตรวจแก้คำแปล'\n"
        f"- ความยาว 1-2 บรรทัด และต้องไม่สั้นกว่า {MIN_STATEMENT_CHARS} ตัวอักษร\n"
        "- statement_th ต้องเป็นภาษาไทย ห้ามมีชื่อฟังก์ชัน ชื่อตัวแปร "
        "หรือโค้ดปนอยู่ (เช่น getDefault, get_default, obj.method) "
        "ชื่อเทคโนโลยีที่ใช้ในวงการจริง เช่น AI, ESG, Data Science ใช้ได้\n\n"
        "ก่อนตอบ ให้ทดสอบประโยคที่เขียนไว้ด้วยคำถามนี้: "
        "ถ้าลบชื่อสาขาออก ผู้อ่านยังบอกได้ไหมว่านี่คือความต้องการของสายวิชาชีพใด "
        "ถ้าประโยคใช้ได้กับหลายสาขาพร้อมกัน เช่น บริหารธุรกิจ นิเทศศาสตร์ การตลาด และรัฐศาสตร์ "
        "แปลว่ายังกว้างเกินไป ให้เขียนใหม่ก่อนตอบ\n\n"
        "ตอบเป็น JSON object ที่มี field:\n"
        "  statement_th: string (ประโยคภาษาไทย)\n"
        "  statement_en: string (ประโยคภาษาอังกฤษ)\n"
        f"  rationale_th: string ({MIN_RATIONALE_CHARS}-{MAX_RATIONALE_CHARS} ตัวอักษร) "
        "บอกว่าทักษะในกลุ่มนี้รวมกันเป็นความต้องการเดียวได้เพราะอะไร "
        "ต้องอ้างถึงหน้าที่หรืองานร่วมที่ทักษะเหล่านั้นใช้ทำ "
        "ห้ามตอบกว้าง ๆ ว่า 'เป็นทักษะที่เกี่ยวข้องกัน' หรือ 'อยู่ในสายงานเดียวกัน' "
        "และห้ามอ้างหลักฐานหรือแหล่งที่มาที่ไม่ได้อยู่ในรายชื่อทักษะที่ให้มา\n\n" + NOTE_POLICY_TH
    )
    label = _KSEC_LABEL_TH.get(ksec, ksec)
    bloom_label = _BLOOM_LABEL_TH.get(bloom_level, bloom_level)
    keywords = ", ".join(skill_names[:30])
    context_line = f"บริบทหลักสูตร: {program_context}\n" if program_context else ""
    user = (
        f"{context_line}"
        f"หมวดสมรรถนะ: {label} ({ksec})\n"
        f"ระดับที่ตลาดเรียกร้อง: {bloom_label} ({bloom_level})\n"
        f"ทักษะในกลุ่มนี้: {keywords}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": append_note(user, note_th)},
    ]
