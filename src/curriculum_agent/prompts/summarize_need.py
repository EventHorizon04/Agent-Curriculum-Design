from __future__ import annotations

from collections.abc import Sequence

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

# How many member names one call is shown. It was a bare `[:30]` on a
# comma-joined string, which cost nothing while nothing cited a position. Now
# supporting_indices does, so the cap is named: a name past it carries no index,
# cannot be claimed, and counts against coverage — which is honest, since the
# sentence was never written from it. The caller orders names most-mentioned
# first so that what the cap drops is the rarest of them.
MAX_LISTED_SKILLS = 30

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
#
# "apply" used to read "ประยุกต์ใช้ในงานจริงได้". Every stored Need at this level
# came out wrapped as "ประยุกต์ใช้ <resource> ในการ <task>" — the model was
# copying the label's own verb into the sentence it was asked to write, which is
# exactly the wrapper shape the rules below now forbid. The replacement names
# the same cognitive demand without handing back a verb to copy.
_BLOOM_LABEL_TH: dict[str, str] = {
    "remember": "ระบุและเรียกคืนข้อมูลได้",
    "understand": "อธิบายและตีความได้",
    "apply": "นำไปลงมือทำงานจริงได้",
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
    skill_frequencies: Sequence[int] | None = None,
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
    task, object and — only when the group itself shares one — work context, at
    the group's Bloom level, and name the two degenerate shapes — a vague
    placeholder and a joined skill list — that _NeedStatement rejects. The list
    rule names both punctuations on purpose: the Thai one (spaces closed by "และ")
    is the shape a Thai-first model actually produces, and the guard that only
    counted commas was really only catching the list written the English way.

    The three-part rule used to be unconditional ("ต้องมีครบ 3 ส่วน"), which asked
    for a work context every group may not actually share. It is now **"what most
    of the group shares"**, not a frequency threshold: on the stored corpus every
    skill name has frequency 1 (91/91), so a rule like "under X% of the group's
    total frequency must not decide the object" is degenerate — with 18 equal
    members, each is 5.5%, and any X above that bans every member at once. The
    rule is written in terms of a majority instead, and `skill_frequencies` is
    passed to the model precisely so the rule starts to bite once a corpus has
    names that repeat, rather than being dead weight until then.

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

    Four more rules were added from reading the stored corpus rather than from a
    failure mode predicted in advance. The **actor** rule rejects a sentence
    describing what the institution or its administrators do (building
    partnerships, setting policy) rather than what one new graduate does —
    those members belong in `not_covered_indices` instead, reason
    `not_graduate`. The **off-profession** rule rejects another profession's
    work (building a translation tool, in a translation program) as the
    sentence's main task — those go to `not_covered_indices` with
    `off_task`; *using* that other profession's tool to do this profession's
    work is still fine and stays in the sentence. The **wrapper** rule is the
    direct fix for the apply-label bug above: a stored Need read "ประยุกต์ใช้
    <resource> ในการ <task>" because the model was copying the Bloom label's own
    verb, so the prompt now forbids that shape outright and asks for the task as
    the main verb with the resource moved into a "โดยใช้..." clause. The
    **added-qualifier** rule bans a level word like "อย่างลึกซึ้ง", "เชิงยุทธศาสตร์"
    or "ขั้นสูง" unless most of the group shares it — not merely "not in any
    member's name", which measurement showed is the wrong bar: stored PLO2's
    "อย่างลึกซึ้ง" does appear, in 1 of that Need's 18 member names
    ("การตรวจทานคำศัพท์เทคนิคเฉพาะทางกฎหมายอย่างลึกซึ้ง"), and another stored Need's
    "ขั้นสูง" came from 1 of 15 — both one-member outliers a model generalised
    into the whole sentence. Only "เชิงลึก" was invented outright, present in
    none of its group's 3 names. A rule banning only words absent from every
    name would have let the first two through; the rule is written on the same
    majority test as the context-only-when-shared rule above. A fifth rule
    forbids a floating quantifier ("หลายด้าน", "อย่างรอบด้าน") in place of naming
    which ones.

    `not_covered_indices` is where a member the sentence cannot honestly speak
    for goes, with a reason code (`low_freq`, `not_graduate`, `off_task`) and a
    short note — the same discipline as `supporting_indices` below: a
    measurement, never a thing that can fail the call. `designer_input_used`
    records whether the optional designer note changed a word choice, which is
    logged (`need_combination._log_coverage` and the per-run summary) rather than
    stored, for the same reason `supporting_indices` is not graded — there is no
    threshold yet, only a first distribution to look at.

    `supporting_indices` is the sentence's own account of which listed members it
    speaks for, and the names are numbered for that reason alone. Before, they
    arrived as one comma-joined string, so a sentence could not say what it
    covered even if it tried — which is why ticket 18's silent case, a
    fifteen-name group whose sentence spoke for three while the Need claimed all
    ten evidence items, was undetectable by construction. The prompt says outright
    that leaving a member out is a correct answer and that the sentence must not
    grow to cover more: asked which members it reflected, a model otherwise
    claims all of them, and the figure measures nothing while the sentence drifts
    toward the joined list the no-list rule forbids. It is self-report, not a
    reading of the sentence; `need_grouping.supporting_coverage` turns it into a
    number and says so.

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
        "จากกลุ่มทักษะที่ให้มา จงสรุปเป็น 'ความต้องการ' หนึ่งประโยค "
        "ที่สะท้อนสิ่งที่ทักษะส่วนใหญ่ในกลุ่มเรียกร้องจากบัณฑิต\n"
        "ประโยคนี้จะถูกนำไปเขียนเป็นผลลัพธ์การเรียนรู้ (PLO) หนึ่งข้อโดยตรง "
        "จึงต้องเจาะจงพอที่จะเขียน PLO ได้ทันทีโดยไม่ต้องเดาเนื้อหาเพิ่ม\n\n"
        "กติกา:\n"
        "- เขียนเป็นประโยคเดียวที่ระบุ 'ข้อกำหนด' ขึ้นต้นได้หลายแบบ เช่น "
        "'ต้องการ...' 'ต้องการบัณฑิตที่...' 'ต้องการหลักสูตรที่...' หรือ 'บัณฑิตต้องมี...' "
        "เลือกแบบที่อ่านเป็นธรรมชาติที่สุดกับเนื้อหา ไม่ต้องใช้แบบเดียวกันทุกข้อ\n"
        "- ห้ามเขียนเป็นผลลัพธ์การเรียนรู้ (PLO) ที่เสร็จรูปแล้ว เช่น 'บัณฑิตวิเคราะห์...ได้' "
        "ประโยคนี้คือสิ่งที่ถูกเรียกร้อง ส่วนการแปลงเป็น PLO เป็นขั้นถัดไป\n"
        "- โครงสร้างประโยค: (1) งานที่บัณฑิตทำ (2) วัตถุหรือผลงานที่เจาะจง (3) บริบทของงาน\n"
        "  ใส่ส่วนที่ (3) เฉพาะเมื่อทักษะส่วนใหญ่ในกลุ่ม (นับตามความถี่) มีบริบทนั้นร่วมกัน "
        "มิฉะนั้นให้ตัดส่วนที่ (3) ออก\n"
        "  ตัวอย่าง: 'ต้องการบัณฑิตที่ประเมินและปรับปรุงผลลัพธ์การแปลเอกสารธุรกิจระหว่างประเทศ "
        "ในบริบทการสื่อสารไทย-จีน'\n"
        "- ยึดสิ่งที่ทักษะส่วนใหญ่มีร่วมกัน: งาน วัตถุ และบริบทของประโยคต้องมาจากสิ่งที่ทักษะส่วนใหญ่ในกลุ่มมีร่วมกัน\n"
        "  ห้ามให้ทักษะเพียงหนึ่งหรือสองรายการที่ความถี่ต่ำเป็นตัวกำหนดวัตถุหรือบริบทของทั้งประโยค\n"
        "  เช่น ถ้ามีเพียงทักษะเดียวที่พูดถึง 'เอกสารทางการทูต' ห้ามใช้ 'เอกสารทางการทูต' เป็นวัตถุของประโยค\n"
        "- หนึ่งประโยคคือหนึ่งสมรรถนะ ห้ามยัดหลายเรื่องที่ไม่เกี่ยวกันไว้ในประโยคเดียว\n"
        "- ประโยคนี้จะใช้สล็อต PLO ของทั้งหลักสูตรไป 1 ข้อจาก 10 ข้อ "
        "จึงต้องครอบ 'ประเภทของงาน' ที่บัณฑิตทำซ้ำได้หลายสถานการณ์ในสายวิชาชีพนั้น "
        "ไม่ใช่ภารกิจย่อยชิ้นเดียวภายในประเภทนั้น "
        "เช่น 'แปลและตรวจสอบเอกสารสัญญาทางธุรกิจ' อยู่ในระดับหลักสูตร "
        "แต่ 'แปลสัญญาซื้อขายสินค้า' แคบเกินไป เป็นงานหนึ่งชิ้นในประเภทเดียวกัน\n"
        "  ข้อนี้คุมเฉพาะ 'ขอบเขตของวัตถุ' ไม่ได้อนุญาตให้เขียนกว้างลอย ๆ "
        "การแก้ประโยคที่แคบเกินคือขยายให้ครอบประเภทของงาน ไม่ใช่ตัดรายละเอียดทิ้ง\n"
        "- ระดับความยากต้องตรงกับระดับ Bloom ที่ระบุให้ ไม่สูงหรือต่ำกว่านั้น\n"
        "- ผู้ลงมือทำคือบัณฑิตจบใหม่: ประโยคต้องบรรยายงานที่บัณฑิตจบใหม่คนหนึ่งทำได้ "
        "ไม่ใช่พันธกิจของสถาบัน องค์กร หรือผู้บริหาร เช่น การสร้างความร่วมมือกับมหาวิทยาลัย หรือการกำหนดนโยบาย "
        "ทักษะในกลุ่มที่เป็นลักษณะนี้ ให้ใส่ไว้ใน not_covered_indices แทนการเขียนลงในประโยค\n"
        "- งานของวิชาชีพอื่นที่ไม่ใช่งานของสาขานี้ (เช่น พัฒนาซอฟต์แวร์หรือเครื่องมือ ในหลักสูตรการแปล) "
        "ห้ามเป็นงานหลักของประโยค ให้ใส่ไว้ใน not_covered_indices "
        "ส่วนการ 'ใช้' เครื่องมือเหล่านั้นทำงานของสาขาเขียนได้\n"
        "- ห้ามเขียนในรูป 'ประยุกต์ใช้/ใช้ <ความรู้ ทักษะ เทคโนโลยี หรือเครื่องมือ> ในการ <งาน>' "
        "ให้เขียน <งาน> เป็นงานที่บัณฑิตทำโดยตรง และย้ายสิ่งที่ใช้ไปไว้ในวลี 'โดยใช้...'\n"
        "- ห้ามใช้คำขยายเชิงระดับ เช่น 'เชิงยุทธศาสตร์' 'นวัตกรรม' 'ระดับนโยบาย' 'ระดับนานาชาติ' "
        "'ชั้นนำ' 'อย่างลึกซึ้ง' 'เชิงลึก' 'ขั้นสูง' เว้นแต่ทักษะส่วนใหญ่ในกลุ่มใช้คำนั้นร่วมกัน "
        "คำขยายที่มาจากทักษะเพียงหนึ่งหรือสองรายการ หรือไม่มีในชื่อทักษะเลย ห้ามใส่\n"
        "- ห้ามใช้คำบอกปริมาณลอย ๆ เช่น 'หลายด้าน' 'อย่างรอบด้าน' ให้ระบุว่าด้านใด\n"
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
        "(เชื่อมคำนามหรือคำกริยาด้วย 'และ' หรือ ',' ได้ไม่เกิน 2 คำ) และแบบไทยที่เว้นวรรคแล้วปิดท้ายด้วย 'และ' "
        "เช่น 'ต้องการการใช้ AI การแปล และการตรวจแก้คำแปล'\n"
        f"- ความยาว 1-2 บรรทัด และต้องไม่สั้นกว่า {MIN_STATEMENT_CHARS} ตัวอักษร\n"
        "- statement_th ต้องเป็นภาษาไทย ห้ามมีชื่อฟังก์ชัน ชื่อตัวแปร "
        "หรือโค้ดปนอยู่ (เช่น getDefault, get_default, obj.method) "
        "ชื่อเทคโนโลยีที่ใช้ในวงการจริง เช่น AI, ESG, Data Science ใช้ได้\n"
        "- ข้อกำหนดเพิ่มเติมจากผู้ออกแบบหลักสูตร (ถ้ามี) ใช้เลือกถ้อยคำ หรือเลือกเน้นระหว่างทักษะที่มีอยู่ในกลุ่มเท่านั้น\n"
        "  ห้ามใช้เพื่อเพิ่มงาน วัตถุ หรือบริบทที่ไม่มีในทักษะของกลุ่ม ถ้าใช้ ให้ระบุใน designer_input_used\n\n"
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
        "และห้ามอ้างหลักฐานหรือแหล่งที่มาที่ไม่ได้อยู่ในรายชื่อทักษะที่ให้มา\n"
        "  supporting_indices: list[int] เลขลำดับของทักษะที่ประโยคนี้สะท้อนจริง "
        "ใส่เฉพาะข้อที่ผู้อ่านเห็นได้จากประโยคว่าถูกพูดถึง ไม่ต้องพยายามให้ครบทุกข้อ "
        "การเว้นข้อที่ประโยคไม่ได้พูดถึงคือคำตอบที่ถูกต้อง "
        "และห้ามเขียนประโยคให้ยาวขึ้นเพื่อครอบทุกข้อ\n"
        '  not_covered_indices: list ของ {"index": int, '
        '"reason_code": "low_freq" | "not_graduate" | "off_task", "note_th": string}\n'
        "    ทักษะที่ประโยคไม่ได้สะท้อนและเหตุผล (low_freq = ความถี่ต่ำ ไม่ใช่สิ่งที่กลุ่มส่วนใหญ่มีร่วมกัน, "
        "not_graduate = เป็นงานของสถาบันหรือองค์กร, off_task = เป็นงานของวิชาชีพอื่นหรือไม่ใช่งานของสาขา)\n"
        '  designer_input_used: {"used": true|false, "detail_th": string} '
        "ใช้ข้อกำหนดจากผู้ออกแบบหรือไม่ และใช้อย่างไร\n\n" + NOTE_POLICY_TH
    )
    label = _KSEC_LABEL_TH.get(ksec, ksec)
    bloom_label = _BLOOM_LABEL_TH.get(bloom_level, bloom_level)
    shown_names = skill_names[:MAX_LISTED_SKILLS]
    # Only listed alongside the names: a frequency column a caller never passes
    # would be a third column with nothing in it, not a feature.
    if skill_frequencies is None:
        header = "ทักษะในกลุ่มนี้ (เลขลำดับ | ทักษะ):"
        listed = "\n".join(f"{i} | {name}" for i, name in enumerate(shown_names))
    else:
        shown_freqs = list(skill_frequencies)[:MAX_LISTED_SKILLS]
        header = "ทักษะในกลุ่มนี้ (เลขลำดับ | ทักษะ | ความถี่):"
        listed = "\n".join(
            f"{i} | {name} | {freq}"
            for i, (name, freq) in enumerate(zip(shown_names, shown_freqs, strict=True))
        )
    context_line = f"บริบทหลักสูตร: {program_context}\n" if program_context else ""
    user = (
        f"{context_line}"
        f"หมวดสมรรถนะ: {label} ({ksec})\n"
        f"ระดับที่ตลาดเรียกร้อง: {bloom_label} ({bloom_level})\n"
        f"{header}\n{listed}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": append_note(user, note_th)},
    ]
