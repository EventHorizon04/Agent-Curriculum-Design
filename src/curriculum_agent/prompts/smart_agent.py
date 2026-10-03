"""Prompts for the SMART validation agent, and its repair request.

The rubric wording here is inherited from the light soft judge it replaces
(`prompts/smart_validator.py`), and four of its clauses have scar tissue behind
them — keep them:

- Measurable asks whether a real instrument could observe the outcome. The
  absence of a forbidden word is explicitly *not* evidence of that.
- Relevant is judged against the Needs shown and nothing else. It used to add
  "and reflects what the labour market wants", which was not checkable from a
  prompt the market is not in, and which marked down a correctly-sourced PLO
  for not sounding like a job ad.
- Time-bound defaults to true: a PLO carries "by the end of the program" by
  convention, so silence about time is correct.
- วิสัยทัศน์ appears nowhere. The institution's direction is a program-level
  check on `Need.source_stakeholder_types`, not a per-PLO text comparison.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from curriculum_agent.stages.smart_agent_tools import ToolObservation

_SYSTEM_TH = """คุณเป็นผู้ตรวจสอบคุณภาพ PLO ตามเกณฑ์ SMART ของหลักสูตรอุดมศึกษาไทย (มคอ./อว.)
คุณสืบค้นข้อมูลได้ด้วยเครื่องมือ แล้วจึงสรุปผล ตอบเป็น JSON object เดียวต่อหนึ่งรอบ:
{"reasoning_th": "...", "action": {...}}

action มีสามแบบ
1) เรียกเครื่องมือ: {"kind":"call_tool","tool":"<ชื่อ>", <อาร์กิวเมนต์>}
   - check_hard — ผลตรวจเกณฑ์ที่ตัดสินด้วยโค้ด (S ประโยคขึ้นต้นด้วย action_verb_th, S action_verb_th
     ประกาศกริยาเกินหนึ่งตัว, M คำที่วัดไม่ได้, R ร่องรอยหลักฐาน) พร้อมจำนวนกริยา Bloom ที่พบ
     ใส่ statement_th/action_verb_th เพื่อทดลองสำนวนใหม่ก่อนสั่งแก้ก็ได้
     **ให้เรียกเครื่องมือนี้เป็นรอบแรกเสมอ**
   - bloom_lookup — กริยาที่ระบุอยู่ระดับ Bloom ใด เทียบกับระดับที่ PLO ประกาศไว้ (ต้องมี verb_th)
   - get_need — Need ที่ PLO นี้อ้างถึง (ต้องมี need_id)
   - get_evidence — ข้อความหลักฐานบางส่วนที่ PLO นี้อ้างถึง อ่านได้ไม่เกิน 3 รายการ (ต้องมี evidence_id)
   - list_sibling_plos — PLO อื่นในชุดเดียวกัน เพื่อดูว่าซ้ำซ้อนกันหรือไม่
2) สั่งแก้ประโยค: {"kind":"request_repair","instruction_th":"...",
   "criteria":["M_forbidden"],"keep_th":"..."}
   - คุณไม่ได้เขียนประโยคเอง โมเดลที่เขียนภาษาไทยจะแก้ตามคำสั่งของคุณ แล้วคุณตรวจซ้ำ
   - instruction_th ต้องอยู่ได้ด้วยตัวเอง ระบุว่าอะไรผิดและต้องแก้อย่างไร
   - keep_th คือสาระที่ต้องคงไว้
3) สรุปผล: {"kind":"finish", <ผลตรวจ 7 ข้อ>, "findings_th":{...}, "diagnosis_th":"..."}

ผลตรวจ 7 ข้อใน finish (true = ผ่าน)
- specific_object_ok: กรรมของกริยาเจาะจง ระบุพฤติกรรม/ทักษะ/สมรรถนะที่ชัดเจน
  ไม่ใช่คำกว้างเช่น 'ความรู้' 'ทักษะที่จำเป็น' และไม่ใช่ประโยคที่ใช้ได้กับทุกหลักสูตร
  (PLO ที่แทบแยกไม่ออกจาก PLO อื่นในชุด ให้ถือว่าไม่ผ่านข้อนี้)
- measurable_ok: สังเกตได้ และประเมินได้จริงด้วยเครื่องมือทางการศึกษา
  (ข้อสอบ ชิ้นงาน การปฏิบัติ แฟ้มผลงาน) — การไม่มีคำห้ามยังไม่นับว่าวัดได้
- achievable_ok: ระดับ Bloom สมเหตุสมผลกับระดับคุณวุฒิ และบรรลุได้ภายในระยะเวลาหลักสูตร
- actor_ok: ผู้ลงมือทำในประโยคคือบัณฑิตรายบุคคล ไม่ใช่สถาบัน องค์กร หลักสูตร หรือผู้บริหาร
  เช่น 'สร้างเครือข่ายความร่วมมือกับมหาวิทยาลัยต่างประเทศ' หรือ 'ออกแบบโครงสร้างหลักสูตร'
  เป็นงานของสถาบัน ไม่ใช่สิ่งที่บัณฑิตคนหนึ่งทำได้เมื่อจบการศึกษา
- scope_ok: งานในประโยคอยู่ในขอบเขตวิชาชีพที่หลักสูตรนี้ผลิตบัณฑิต
  ตัดสินจาก 'ขอบเขตวิชาชีพของหลักสูตร' ถ้าแสดงไว้ มิฉะนั้นจากสาขาในบรรทัด 'หลักสูตร'
  งานของวิชาชีพอื่นที่เกิดขึ้นในบริบทของสาขา ถือว่าไม่ผ่าน
  เช่น พัฒนาโมเดล AI หรือเขียนซอฟต์แวร์ ในหลักสูตรการแปล
  แต่การ 'ใช้' เครื่องมือของวิชาชีพอื่นเพื่อทำงานของสาขา ถือว่าผ่าน เช่น ใช้ AI ช่วยแปล
  ถ้าไม่ได้แสดงขอบเขตวิชาชีพหรือสาขาไว้ ให้ scope_ok เป็น true
- relevant_needs_ok: ประโยคนี้ "ตอบ" Need ที่แสดงไว้หรือไม่ ตัดสินจาก Need และหลักฐานที่อ้างถึงเท่านั้น
  ห้ามอ้างกรอบอื่นที่ไม่ได้แสดงไว้
  **ไม่ใช่คำถามว่าประโยคอ้าง need_id ใด** ประโยคไม่ต้องมี need_id อยู่ในนั้น
- time_bound_ok: ค่าเริ่มต้นเป็น true — PLO ถือว่าบรรลุ 'เมื่อสิ้นสุดหลักสูตร' โดยปริยาย
  ให้ตอบ false เฉพาะเมื่อข้อความระบุกรอบเวลาอื่นที่ขัดกัน เช่น 'ภายในปีที่ 2'

findings_th: เหตุผลสั้น ๆ ต่อข้อที่ไม่ผ่าน ใช้ชื่อรหัสเป็นคีย์
(S_object, M_assessable, A_level, A_actor, A_scope, R_needs, T_horizon)
diagnosis_th: สรุปให้นักออกแบบหลักสูตรอ่าน ระบุว่าต้องแก้อะไรหรือเหตุใดจึงผ่าน

หมายเหตุ
- S_multi_verb ตัดสินจาก action_verb_th ไม่ใช่จากประโยค ประโยคมีกริยาในอนุประโยครอง
  ('โดยใช้...' 'เพื่อสร้าง...') ได้ตามปกติ สิ่งที่ผิดคือ action_verb_th เขียนเป็นวลีหลายกริยา
  การแก้คือเลือกกริยาที่เป็นผลลัพธ์จริงหนึ่งตัว แล้วแก้ทั้ง action_verb_th และประโยคให้ตรงกัน
- เกณฑ์ที่ตัดสินด้วยโค้ด (S กริยา, S จำนวนกริยาที่ประกาศ, M คำห้าม, R หลักฐาน) คุณประกาศว่าผ่านเองไม่ได้
  โค้ดจะตรวจประโยคสุดท้ายอีกครั้งเสมอ ทางเดียวที่จะแก้ได้คือสั่ง request_repair
- ร่องรอยหลักฐานของ PLO (source_need_ids) ถูกตรึงด้วยโค้ดจาก Need ที่เลือกไว้ก่อนเรียกคุณ
  request_repair เปลี่ยนมันไม่ได้ ถ้าเห็นว่าประโยคไม่ตรงกับ Need ให้สั่งแก้ *ประโยค* ให้ตอบ Need ที่มีอยู่
  ไม่ใช่สั่งให้เปลี่ยน Need ที่อ้างถึง
- ถ้า actor_ok หรือ scope_ok ไม่ผ่านเพราะสาระของ Need เอง (Need คืองานของสถาบันเอง
  หรือคืองานของวิชาชีพอื่น) ห้ามสั่ง request_repair เพราะแก้ถ้อยคำแล้วสาระของผลลัพธ์จะเปลี่ยน
  ให้ finish แล้วเขียนใน diagnosis_th ว่าควรตัดข้อนี้หรือส่งกลับขั้น Need
  สั่งแก้ได้เฉพาะเมื่อประโยคเติมส่วนที่เกินขอบเขตเข้ามาเองทั้งที่ Need ไม่ได้ขอ
- get_need รับเฉพาะ need_id ที่แสดงไว้เท่านั้น ส่งข้อความของ Need เป็น need_id ไม่ได้
- อย่าเรียกเครื่องมือเดิมด้วยอาร์กิวเมนต์เดิมซ้ำ
- ถ้าข้อมูลพอแล้วให้สรุปด้วย finish ทันที ไม่ต้องเรียกเครื่องมือให้ครบทุกตัว"""


def build_smart_agent_prompt(
    *,
    statement_th: str,
    bloom_level: str,
    action_verb_th: str,
    degree_level: str,
    duration_years: int,
    cited_needs: Sequence[tuple[str, str]],
    cited_evidence_ids: list[str],
    sibling_count: int,
    program_context: str | None = None,
    scope_th: str | None = None,
) -> list[dict[str, str]]:
    """The opening two turns: the rubric, then this PLO.

    `program_context` (field and degree, from intake) and `scope_th` (the
    designer's own statement of what the program covers) are what `scope_ok` is
    judged against. The validator used to see the degree and the duration and
    never the field, so "is this work inside the profession" had nothing to be
    answered against. `scope_th` is empty on most programs — the real one this
    was measured on included — which is why the field line is the fallback
    yardstick rather than scope_th alone: a verdict that needed scope_th would
    have been a no-op everywhere it was deployed. With neither, both lines are
    omitted and the rubric tells the validator to answer true.

    `cited_needs` carries each Need as `(need_id, statement_th)` because the ids
    are the arguments `get_need` accepts. Listing the statements alone left the
    tool uncallable: on a live run the agent passed a Need's *sentence* as
    `need_id`, was refused, read the refusal as a broken evidence trail, and
    spent two of its three repairs instructing the writer to make the Thai
    sentence cite a UUID. Four of eight PLOs came back carrying a spurious
    `R_needs` finding from the same misreading.

    No `note_th` parameter, and none is wanted. The designer's note reaches the
    draft prompt and nothing else; a validator that could read it could relay
    the wording into a repair instruction, and the note would arrive at a repair
    prompt second-hand.
    """
    lines = [
        f"PLO ที่ต้องตรวจ: {statement_th}",
        f"ระดับ Bloom ที่ประกาศไว้: {bloom_level}",
        f"action_verb_th: {action_verb_th}",
        f"ระดับคุณวุฒิ: {degree_level}",
        f"ระยะเวลาหลักสูตร: {duration_years} ปี",
    ]
    if program_context:
        lines.append(f"หลักสูตร: {program_context}")
    if scope_th:
        lines.append(f"ขอบเขตวิชาชีพของหลักสูตร: {scope_th}")
    if cited_needs:
        joined = "\n".join(f"- {need_id}: {statement}" for need_id, statement in cited_needs)
        lines.append(f"Need ที่อ้างถึง (need_id ตรึงด้วยโค้ด แก้ไม่ได้):\n{joined}")
    if cited_evidence_ids:
        lines.append(f"หลักฐานที่อ้างถึง (อ่านได้ด้วย get_evidence): {', '.join(cited_evidence_ids)}")
    if sibling_count:
        lines.append(f"มี PLO อื่นในชุดนี้ {sibling_count} รายการ (ดูด้วย list_sibling_plos)")
    lines.append("เริ่มด้วย check_hard")
    return [
        {"role": "system", "content": _SYSTEM_TH},
        {"role": "user", "content": "\n".join(lines)},
    ]


def build_tool_observation(observation: ToolObservation) -> str:
    """One tool result as the next user turn."""
    if not observation.ok:
        return f"ผลของ {observation.tool}: ปฏิเสธ — {observation.error_th}"
    payload = json.dumps(observation.payload, ensure_ascii=False, sort_keys=True)
    return f"ผลของ {observation.tool}:\n{payload}"


def build_refusal_observation(reason_th: str) -> str:
    return f"ระบบปฏิเสธคำสั่งล่าสุด: {reason_th}"


def build_repair_observation(
    *,
    before_statement: str,
    after_statement: str,
    before_failures: list[str],
    after_failures: list[str],
) -> str:
    """The rewrite *and* the code's verdict on it.

    Both, always. Handed only the new sentence, the agent has to trust its own
    reading of a criterion pure code just decided — and cannot tell a rewrite it
    likes from a rewrite that passes.
    """
    before = ", ".join(before_failures) or "(ไม่มี)"
    after = ", ".join(after_failures) or "(ไม่มี)"
    return (
        "ผลการแก้ประโยค\n"
        f"ประโยคเดิม: {before_statement}\n"
        f"ประโยคใหม่: {after_statement}\n"
        f"เกณฑ์ที่ตัดสินด้วยโค้ด: {before} -> {after}"
    )


def build_agent_repair_prompt(
    *,
    statement_th: str,
    bloom_level: str,
    action_verb_th: str,
    degree_level: str,
    instruction_th: str,
    criteria: list[str],
    keep_th: str | None = None,
) -> list[dict[str, str]]:
    """Ask the synthesis slot to rewrite one statement.

    **There is no `note_th` parameter, and adding one would be a mistake.** The
    designer's note reaches the draft prompt only. That invariant used to rest
    on `_build_fix_prompt` happening not to take the argument; here it rests on
    the signature.

    The instruction must stand on its own, because the model that wrote the
    diagnosis is not the model that writes the fix. So the prompt carries the
    instruction, the original statement, and nothing else — no tool results, no
    sibling PLOs, no rubric recital.
    """
    named = ", ".join(criteria) if criteria else "(ไม่ระบุรหัส)"
    user = [
        f"PLO เดิม:\n{statement_th}",
        f"ระดับ Bloom: {bloom_level}, action_verb_th: {action_verb_th}",
        f"ระดับคุณวุฒิ: {degree_level}",
        f"เกณฑ์ที่ไม่ผ่าน: {named}",
        f"สิ่งที่ต้องแก้:\n{instruction_th}",
    ]
    if keep_th:
        user.append(f"สาระที่ต้องคงไว้: {keep_th}")
    user.append(
        "เขียน PLO ใหม่ให้แก้ประเด็นข้างต้น โดยคงสาระเดิมและระดับ Bloom เดิมไว้ "
        "ถ้าเปลี่ยนกริยาในประโยค ต้องแก้ action_verb_th ให้ตรงกันด้วย "
        "ตอบเป็น JSON object field เหมือน PLO เดิม"
    )
    return [
        {
            "role": "system",
            "content": (
                "คุณเป็นผู้เชี่ยวชาญ OBE เขียนข้อความ PLO ภาษาไทยสำหรับหลักสูตรอุดมศึกษาไทย "
                "แก้ประโยคตามที่ผู้ตรวจระบุ โดยคงสาระสำคัญเดิม "
                "ห้ามใช้คำ รู้ จำ เข้าใจ ซาบซึ้ง ตระหนัก ศรัทธา รัก "
                "และใช้กริยาแสดงพฤติกรรมเพียงตัวเดียว "
                "ตอบเป็น JSON object field เหมือน PLO เดิม"
            ),
        },
        {"role": "user", "content": "\n\n".join(user)},
    ]
