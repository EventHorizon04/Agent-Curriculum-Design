from __future__ import annotations


def build_extract_skills_prompt(
    evidence_text: str,
    classification: str,
    field_th: str = "",
    program_name_th: str = "",
    scope_th: str = "",
) -> list[dict[str, str]]:
    """Extract skills from one evidence item, tagged and judged for field fit.

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
        "จากข้อความ evidence จงระบุทักษะที่ตลาดแรงงานต้องการ\n\n"
        "กติกา:\n"
        "- แต่ละทักษะต้องเป็น 'วลี' หรือกลุ่มคำที่สื่อความสามารถ ห้ามเป็นคำโดดคำเดียว\n"
        "- ทักษะแต่ละรายการต้องไม่ซ้ำและไม่คาบเกี่ยวกัน (unique, independent) "
        "ห้ามเขียนสิ่งเดียวกันด้วยถ้อยคำต่างกัน\n"
        "- evidence_span_th ต้องคัดลอกข้อความ 'ตรงตัว' จาก evidence ที่ทำให้สรุปทักษะนี้ได้ "
        "ห้ามเรียบเรียงใหม่ ห้ามแต่งเพิ่ม ถ้าไม่มีข้อความรองรับ ห้ามเสนอทักษะนั้น\n"
        "- evidence_span_th ต้องเป็นวลีที่สมบูรณ์ ยาวอย่างน้อยประมาณ 12 ตัวอักษร "
        "คัดลอกตรงตัวจาก evidence ห้ามตัดมาเป็นเศษคำหรืออักขระเดี่ยว ๆ\n"
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
