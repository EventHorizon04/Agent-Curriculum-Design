from __future__ import annotations


def build_extract_skills_prompt(
    evidence_text: str,
    classification: str,
    field_th: str = "",
    program_name_th: str = "",
    scope_th: str = "",
) -> list[dict[str, str]]:
    """Extract skills from one evidence item, tagged and judged for field fit.

    The task line names no single source of demand. It used to ask for
    "ทักษะที่ตลาดแรงงานต้องการ", which is the wrong question in front of most of the
    corpus: evidence carries every StakeholderType, and the prompt is told only
    `requirement`/`general`, never which type it is reading. A สภาวิชาชีพ standard,
    an alumni interview and the institution's own vision were all being mined for
    what a labour market wants. institutional_direction is the sharpest case,
    because the rules below then ask the model to *flag* institutional activity
    rather than drop it — a framing that filters it out before the flag is
    reached defeats the flag.

    Three rules come from `guidances/skill_extraction.md` (the definition of a
    skill, the "these are not skills" list, occupational identity, and the job
    identity test), and two of them carry a caveat the guidance does not:

    - The "not a skill" list is a statement about *what a skill is*, not a licence
      to filter. Its first draft also named the institution's own problems, goals,
      policy, budget and partnerships — which the graduate-capability rule below
      asks the model to *flag and keep*. The whole scope guard runs on flags, not
      on filtering: a skill has to be extracted before it can be flagged, counted
      into `in_field_ratio` / `graduate_capability_ratio`, and shown to the
      designer as an unused Need. Those five were cut, and the sentence saying the
      list is not a licence to drop anything is what keeps the rest from being
      read that way.
    - The job identity test pushes toward a more specific name, and a model told
      "too broad" will otherwise invent the specificity. `evidence_span_th` has to
      be a verbatim quote, so the test carries its own bound: whatever the name
      becomes must still be supported by the text.

      That bound was briefly believed to have failed. The first eval run after
      this rule landed showed ungrounded spans up and a skill named out of the
      scope statement, the rule was removed on that reading, and a control run of
      the *pre-rule* prompts under the corrected scorer then produced both
      symptoms anyway — contamination 1, with "การแปลเอกสารธุรกิจและกฎหมาย" lifted
      straight out of `SCOPE_TH`, and ungrounded spans in the same range. The
      model was already copying from its own context, including the program field
      in the user header. The rule is back; what the episode actually measured is
      that single runs of this eval cannot resolve a difference this small.

    The `ksec_category` rule (decide from the head of the skill name, not its
    modifier) exists because the prompt used to give four labels and "pick
    exactly one" with no line between S and E/C, so task-plus-attitude names
    (e.g. certifying a legal translation "responsibly") landed in E/C and the EC
    groups came out as hybrids that read like their S neighbours. Measured A/B
    2026-11-13 (`.scratch/reports/2026-11-13-ec-fold-measure.md` §3): S names
    sitting among E/C-tagged rows went 18 of 51 to 9 of 49 under blind judgement,
    skill count and grounding unchanged. Spread between repeats is as large as
    the arm difference, and certification names still sometimes land in E.

    `field_th` and `program_name_th` are what make the "no off-field skills" rule
    answerable — before they existed the model was told to exclude skills outside
    the program's field without being told what the field was. They default to
    empty so the contract fingerprint can call this with the text alone.

    `scope_th` is the designer's own statement of what the program covers, and it
    goes in the *system* message, appended conditionally after the rules. Two
    reasons, both measured:

    - In the user message, next to the evidence, the model reads it as evidence:
      eight skills whose name and `evidence_span_th` were copied out of the scope
      statement word for word, on two evidence items that contain none of those
      words. The span is a verbatim quote of the wrong document, so is_grounded()
      only catches it while the two texts happen to share no phrase.
    - Moving it here removed all eight while recall and false positives stayed
      identical, so the position costs nothing.

    It defaults to empty, and an empty one appends nothing, so a program without a
    scope statement gets the previous prompt byte for byte — which is also what
    keeps `_extraction_contract_fingerprint` stable across programs. The scope
    belongs in the cache key instead: it varies per program, and the fingerprint
    is a promise about the shape of a stored payload, not about its content.
    """
    system = (
        "คุณเป็นผู้เชี่ยวชาญวิเคราะห์ทักษะจากข้อความ\n"
        "จากข้อความ evidence จงระบุทักษะหรือสมรรถนะที่ข้อความนั้นเรียกร้อง\n"
        "evidence มาจากผู้มีส่วนได้ส่วนเสียได้หลายกลุ่ม เช่น ผู้ใช้บัณฑิต สภาวิชาชีพ ศิษย์เก่า "
        "ชุมชน หรือทิศทางของสถาบันเอง ไม่ใช่ประกาศรับสมัครงานเท่านั้น "
        "ให้อ่านตามสิ่งที่ข้อความนั้นเรียกร้องจริง\n\n"
        "ทักษะในที่นี้คือความสามารถหรือสมรรถนะที่บุคคลเรียนรู้ พัฒนา ถ่ายทอด ประเมิน "
        "และนำไปใช้ซ้ำได้ในหลายสถานการณ์\n\n"
        "กติกา:\n"
        "- แต่ละทักษะต้องเป็น 'วลี' หรือกลุ่มคำที่สื่อความสามารถ ห้ามเป็นคำโดดคำเดียว\n"
        "- สิ่งต่อไปนี้ไม่ใช่ทักษะ ห้ามเสนอเป็นรายการ: ชื่อตำแหน่งงาน ชื่ออาชีพ "
        "กิจกรรมที่เกิดขึ้นครั้งเดียว และชื่อเครื่องมือ ซอฟต์แวร์ หรือเทคโนโลยีที่ยืนเดี่ยว ๆ "
        "เช่น 'Power BI' ไม่ใช่ทักษะ แต่ 'การวิเคราะห์ข้อมูลด้วยเครื่องมือ Business Intelligence' ใช่ "
        "ข้อนี้บอกว่าอะไรไม่ใช่ทักษะเท่านั้น ไม่ได้อนุญาตให้ตัดทักษะที่อยู่นอกขอบเขตทิ้ง "
        "ของนอกขอบเขตให้ติดธงตามกติกาด้านล่าง\n"
        "- ต้องคงอัตลักษณ์วิชาชีพที่ปรากฏใน evidence ห้ามลดทอนทักษะเฉพาะทางให้เหลือสมรรถนะทั่วไป "
        "'การแปลเอกสารกฎหมายระหว่างประเทศ' ห้ามย่อเป็น 'การสื่อสาร' "
        "'การล่ามเจรจาธุรกิจไทย-จีน' ห้ามย่อเป็น 'การสื่อสารระหว่างบุคคล'\n"
        "- ทักษะแต่ละรายการต้องไม่ซ้ำและไม่คาบเกี่ยวกัน (unique, independent) "
        "ห้ามเขียนสิ่งเดียวกันด้วยถ้อยคำต่างกัน\n"
        "- evidence_span_th ต้องคัดลอกข้อความ 'ตรงตัว' จาก evidence ที่ทำให้สรุปทักษะนี้ได้ "
        "ห้ามเรียบเรียงใหม่ ห้ามแต่งเพิ่ม ถ้าไม่มีข้อความรองรับ ห้ามเสนอทักษะนั้น\n"
        "- evidence_span_th ต้องเป็นวลีที่สมบูรณ์ ยาวอย่างน้อยประมาณ 12 ตัวอักษร "
        "คัดลอกตรงตัวจาก evidence ห้ามตัดมาเป็นเศษคำหรืออักขระเดี่ยว ๆ\n"
        "- ksec_category ให้ตัดสินจาก 'แก่น' ของชื่อทักษะ ไม่ใช่จากคำขยาย: "
        "ถ้าแก่นเป็นงานของวิชาชีพที่ลงมือทำหรือผลิตผลงานได้ ให้เป็น S "
        "แม้จะมีคำขยายเชิงเจตคติหรือคุณภาพกำกับ เช่น 'อย่างมีจริยธรรม' "
        "'ด้วยความรับผิดชอบ' 'อย่างแม่นยำ' งานประเมิน ตรวจสอบ "
        "หรือรับรองคุณภาพของผลงานก็เป็น S; ให้เป็น E "
        "เฉพาะเมื่อแก่นเป็นหลักคุณธรรมจริยธรรมหรือจรรยาบรรณเอง; ให้เป็น C "
        "เฉพาะเมื่อแก่นเป็นคุณลักษณะของตัวบุคคล เช่น การปรับตัว ภาวะผู้นำ "
        "การเรียนรู้ตลอดชีวิต\n"
        "- ทักษะที่อ่านแล้วไม่เข้าข่ายสาขาวิชาของหลักสูตรเลย ให้คงไว้แต่ตั้ง "
        "is_field_relevant = false ห้ามตัดทิ้งเอง ผู้ออกแบบหลักสูตรจะเป็นผู้ตัดสิน\n"
        # Wording verbatim from the prototype that measured 56% recall at 3% false
        # positives. It asks for a flag and forbids dropping anything, because the
        # variant that let the model drop off-scope skills itself also took 3 core
        # skills and 6 institutional ones with it, leaving no trace of either.
        "- is_graduate_capability = true เมื่อทักษะนั้นเป็นสิ่งที่บัณฑิตคนหนึ่งทำได้เมื่อสำเร็จ"
        "การศึกษา; false เมื่อเป็นกิจกรรมหรือภารกิจของสถาบัน/หลักสูตร (เช่น การบริหารหลักสูตร "
        "การจัดหางบประมาณ การสร้างความร่วมมือระดับองค์กร) ให้คงไว้แต่ตั้งเป็น false "
        "ห้ามตัดทิ้งเอง\n"
    )
    if scope_th:
        # Both sentences are load-bearing. The second one is what stops the model
        # treating the scope statement as another piece of evidence to mine.
        system += (
            f"- ขอบเขตของหลักสูตรนี้: {scope_th}\n"
            "  ใช้บรรทัดนี้เป็นเกณฑ์ตัดสิน is_field_relevant เท่านั้น "
            "ห้ามสกัดทักษะจากบรรทัดนี้ ทักษะทุกรายการต้องมาจากข้อความ evidence เท่านั้น\n"
        )
    system += (
        "\nก่อนตอบ ให้ทดสอบชื่อทักษะทุกรายการด้วยคำถามนี้: "
        "ผู้เชี่ยวชาญอ่านชื่อนี้แล้วเดาได้ไหมว่าเป็นสายวิชาชีพใด "
        "ถ้าชื่อนั้นใช้ได้กับหลายวิชาชีพที่ไม่เกี่ยวกันเลย แปลว่ากว้างเกินไป ให้เขียนให้เฉพาะขึ้นก่อนตอบ "
        "เช่น 'การสื่อสาร' เขียนเป็น 'การล่ามข้ามวัฒนธรรม' "
        "'การแก้ปัญหา' เขียนเป็น 'การประเมินคุณภาพงานแปล' "
        "การเขียนให้เฉพาะขึ้นต้องยังมีข้อความใน evidence รองรับ "
        "ห้ามเติมความเฉพาะเจาะจงที่ evidence ไม่ได้บอก\n"
        "\nตอบเป็น JSON object: { skills: [ {\n"
        "  skill_name_th: วลีทักษะภาษาไทย,\n"
        "  skill_name_en: ชื่อภาษาอังกฤษมาตรฐาน (เช่น 'Data Analysis') ห้ามเว้นว่าง,\n"
        "  ksec_category: K|S|E|C — K=ความรู้, S=ทักษะ, "
        "E=คุณธรรมจริยธรรม, C=คุณลักษณะบุคคล "
        "(เลือกได้เพียงค่าเดียว ห้ามตอบว่าผสมกัน),\n"
        "  bloom_level: remember|understand|apply|analyze|evaluate|create "
        "— ระดับ Bloom ด้าน Cognitive เท่านั้น,\n"
        "  evidence_span_th: ข้อความที่คัดลอกตรงตัวจาก evidence,\n"
        "  is_field_relevant: true|false — ทักษะนี้อยู่ในขอบเขตของสาขาวิชาหรือไม่,\n"
        "  is_graduate_capability: true|false — เป็นสมรรถนะของบัณฑิตหรือไม่,\n"
        "  confidence: 0.0-1.0\n"
        "} ] }\n"
        "สกัดไม่เกิน 8 ทักษะต่อข้อความ เน้นทักษะที่วัดได้จริง"
    )
    header = f"[ประเภทหลักฐาน: {classification}]"
    if program_name_th:
        header += f"\n[หลักสูตร: {program_name_th}]"
    if field_th:
        header += f"\n[สาขาวิชา: {field_th}]"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{header}\n{evidence_text}"},
    ]
