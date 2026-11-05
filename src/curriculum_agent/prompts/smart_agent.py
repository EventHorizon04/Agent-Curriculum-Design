"""Prompts for the SMART judge runs, and the repair instruction built from their vote.

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
- "ประยุกต์ใช้ <resource> ในการ <real task>" wraps the real task: the wrapper
  verb is always apply-level, so it passed S (opens with the declared verb)
  and A_level while the real task — another Bloom level, or another
  profession's work — sat hidden in the "ในการ..." clause. One diagnosis said
  a repair had moved a create-level verb there on purpose to make
  "ประยุกต์ใช้" the main verb. specific_object_ok, scope_ok and achievable_ok
  all read through the wrapper to the real task now.
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

action มีสองแบบ
1) เรียกเครื่องมือ: {"kind":"call_tool","tool":"<ชื่อ>", <อาร์กิวเมนต์>}
   - check_hard — ผลตรวจเกณฑ์ที่ตัดสินด้วยโค้ด (S ประโยคขึ้นต้นด้วย action_verb_th, S action_verb_th
     ประกาศกริยาเกินหนึ่งตัว, M คำที่วัดไม่ได้, R ร่องรอยหลักฐาน) พร้อมจำนวนกริยา Bloom ที่พบ
     ใส่ statement_th/action_verb_th เพื่อทดลองสำนวนอื่นเทียบดูก็ได้
     **ให้เรียกเครื่องมือนี้เป็นรอบแรกเสมอ**
   - bloom_lookup — กริยาที่ระบุอยู่ระดับ Bloom ใด เทียบกับระดับที่ PLO ประกาศไว้ (ต้องมี verb_th)
   - get_need — Need ที่ PLO นี้อ้างถึง (ต้องมี need_id)
   - get_evidence — ข้อความหลักฐานบางส่วนที่ PLO นี้อ้างถึง อ่านได้ไม่เกิน 3 รายการ (ต้องมี evidence_id)
   - list_sibling_plos — PLO อื่นในชุดเดียวกัน เพื่อดูว่าซ้ำซ้อนกันหรือไม่
2) สรุปผล: {"kind":"finish", <ผลตรวจ 7 ข้อ>, "findings_th":{...}, "diagnosis_th":"...",
   "repair_hint_th":"..."}
   - คุณไม่ได้เขียนประโยคเอง และไม่ได้สั่งแก้ประโยคโดยตรง ระบบรวมผลจากผู้ตรวจหลายรอบ
     แล้วโมเดลที่เขียนภาษาไทยจะแก้ตามข้อเสนอที่ผู้ตรวจส่วนใหญ่เห็นตรงกัน

ผลตรวจ 7 ข้อใน finish (true = ผ่าน)
- specific_object_ok: กรรมของกริยาเจาะจง ระบุพฤติกรรม/ทักษะ/สมรรถนะที่ชัดเจน
  ไม่ใช่คำกว้างเช่น 'ความรู้' 'ทักษะที่จำเป็น' และไม่ใช่ประโยคที่ใช้ได้กับทุกหลักสูตร
  (PLO ที่แทบแยกไม่ออกจาก PLO อื่นในชุด ให้ถือว่าไม่ผ่านข้อนี้)
  เมื่อกริยาคือ 'ประยุกต์ใช้'/'ใช้' และกรรมเป็นทรัพยากร (ความรู้ ทักษะ เทคโนโลยี เครื่องมือ)
  ขณะที่งานที่ทำจริงอยู่ในอนุประโยค 'ในการ.../เพื่อ...' ให้ถือว่าไม่ผ่านข้อนี้ (S_object)
  วิธีแก้คือทำให้กริยาของงานที่ทำจริงนั้นเป็นกริยาหลักของประโยค
- measurable_ok: สังเกตได้ และประเมินได้จริงด้วยเครื่องมือทางการศึกษา
  (ข้อสอบ ชิ้นงาน การปฏิบัติ แฟ้มผลงาน) — การไม่มีคำห้ามยังไม่นับว่าวัดได้
- achievable_ok: ระดับ Bloom สมเหตุสมผลกับระดับคุณวุฒิ และบรรลุได้ภายในระยะเวลาหลักสูตร
  ตัดสินระดับ Bloom จากกริยาของงานที่ทำจริง ไม่ใช่บนกริยา 'ประยุกต์ใช้' ที่เป็นเปลือกหุ้ม
- actor_ok: ผู้ลงมือทำในประโยคคือบัณฑิตรายบุคคล ไม่ใช่สถาบัน องค์กร หลักสูตร หรือผู้บริหาร
  เช่น 'สร้างเครือข่ายความร่วมมือกับมหาวิทยาลัยต่างประเทศ' หรือ 'ออกแบบโครงสร้างหลักสูตร'
  เป็นงานของสถาบัน ไม่ใช่สิ่งที่บัณฑิตคนหนึ่งทำได้เมื่อจบการศึกษา
- scope_ok: งานในประโยคอยู่ในขอบเขตวิชาชีพที่หลักสูตรนี้ผลิตบัณฑิต
  ตัดสินจาก 'ขอบเขตวิชาชีพของหลักสูตร' ถ้าแสดงไว้ มิฉะนั้นจากสาขาในบรรทัด 'หลักสูตร'
  งานของวิชาชีพอื่นที่เกิดขึ้นในบริบทของสาขา ถือว่าไม่ผ่าน
  เช่น พัฒนาโมเดล AI หรือเขียนซอฟต์แวร์ ในหลักสูตรการแปล
  แต่การ 'ใช้' เครื่องมือของวิชาชีพอื่นเพื่อทำงานของสาขา ถือว่าผ่าน เช่น ใช้ AI ช่วยแปล
  ตัดสินรวมงานที่อยู่ในอนุประโยค 'ในการ.../เพื่อ...' ด้วย เช่น
  'ประยุกต์ใช้เทคโนโลยีในการพัฒนาเครื่องมือ' คืองาน 'พัฒนาเครื่องมือ' ไม่ใช่การ 'ใช้' เทคโนโลยี
  ถ้าไม่ได้แสดงขอบเขตวิชาชีพหรือสาขาไว้ ให้ scope_ok เป็น true
- relevant_needs_ok: ประโยคนี้ "ตอบ" Need ที่แสดงไว้หรือไม่ ตัดสินจาก Need และหลักฐานที่อ้างถึงเท่านั้น
  ห้ามอ้างกรอบอื่นที่ไม่ได้แสดงไว้
  **ไม่ใช่คำถามว่าประโยคอ้าง need_id ใด** ประโยคไม่ต้องมี need_id อยู่ในนั้น
- time_bound_ok: ค่าเริ่มต้นเป็น true — PLO ถือว่าบรรลุ 'เมื่อสิ้นสุดหลักสูตร' โดยปริยาย
  ให้ตอบ false เฉพาะเมื่อข้อความระบุกรอบเวลาอื่นที่ขัดกัน เช่น 'ภายในปีที่ 2'

findings_th: เหตุผลสั้น ๆ ต่อข้อที่ไม่ผ่าน ใช้ชื่อรหัสเป็นคีย์
(S_object, M_assessable, A_level, A_actor, A_scope, R_needs, T_horizon)
diagnosis_th: สรุปให้นักออกแบบหลักสูตรอ่าน ระบุว่าต้องแก้อะไรหรือเหตุใดจึงผ่าน
repair_hint_th: ถ้ามีข้อที่ไม่ผ่านและแก้ได้ที่ถ้อยคำ ให้บอกสั้น ๆ ว่า "ควรแก้อะไร" (ไม่เกิน 400 ตัวอักษร)
เช่น 'เปลี่ยนกรรมจากคำกว้างเป็นงานที่ระบุได้' ห้ามเขียนประโยค PLO ใหม่เต็มประโยค
ถ้าผ่านทุกข้อ หรือที่ไม่ผ่านแก้ด้วยถ้อยคำไม่ได้ ให้ปล่อยว่าง

หมายเหตุ
- S_multi_verb ตัดสินจาก action_verb_th ไม่ใช่จากประโยค ประโยคมีกริยาในอนุประโยครอง
  ('โดยใช้...' 'เพื่อสร้าง...') ได้ตามปกติ สิ่งที่ผิดคือ action_verb_th เขียนเป็นวลีหลายกริยา
  การแก้คือเลือกกริยาที่เป็นผลลัพธ์จริงหนึ่งตัว แล้วแก้ทั้ง action_verb_th และประโยคให้ตรงกัน
  ข้อนี้ไม่ขัดกับกฎเปลือกหุ้ม 'ประยุกต์ใช้...ในการ...' ข้างต้น: วลีเสริมบอกวิธีการ ('โดยใช้...')
  ผ่านได้ตามปกติ แต่งานที่ทำจริงซึ่งซ่อนอยู่ในอนุประโยค 'ในการ...'/'เพื่อ...' ใต้กริยา
  'ประยุกต์ใช้'/'ใช้' ไม่ใช่กรณีนั้น ให้ถือว่า S_object และ achievable_ok ไม่ผ่านตามที่ระบุไว้ข้างต้น
- เกณฑ์ที่ตัดสินด้วยโค้ด (S กริยา, S จำนวนกริยาที่ประกาศ, M คำห้าม, R หลักฐาน) คุณประกาศว่าผ่านเองไม่ได้
  โค้ดจะตรวจประโยคสุดท้ายอีกครั้งเสมอ
- ร่องรอยหลักฐานของ PLO (source_need_ids) ถูกตรึงด้วยโค้ดจาก Need ที่เลือกไว้ก่อนเรียกคุณ
  การแก้ประโยคเปลี่ยนมันไม่ได้ ถ้าเห็นว่าประโยคไม่ตรงกับ Need ให้เสนอแก้ *ประโยค* ให้ตอบ Need ที่มีอยู่
  ไม่ใช่เสนอให้เปลี่ยน Need ที่อ้างถึง
- ถ้า actor_ok หรือ scope_ok ไม่ผ่านเพราะสาระของ Need เอง (Need คืองานของสถาบันเอง
  หรือคืองานของวิชาชีพอื่น) การแก้ถ้อยคำทำให้สาระของผลลัพธ์เปลี่ยน ระบบจึงไม่แก้ข้อนี้ให้
  ให้ finish แล้วเขียนใน diagnosis_th ว่าควรตัดข้อนี้หรือส่งกลับขั้น Need และอย่าเขียน repair_hint_th
  เพื่อข้อนี้ เสนอแก้ได้เฉพาะเมื่อประโยคเติมส่วนที่เกินขอบเขตเข้ามาเองทั้งที่ Need ไม่ได้ขอ
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


def build_turns_left_note(turns_left: int) -> str:
    """Said near the end, because the model is otherwise never told the budget."""
    return f"เหลืออีก {turns_left} รอบ — เตรียมสรุปผลตรวจด้วย finish จากข้อมูลที่มีแล้ว ไม่ต้องเรียกเครื่องมือเพิ่ม"


def build_closing_instruction(turns: int) -> str:
    """The one extra call after the turns are used up: a Finish and nothing else."""
    return f"ใช้ครบ {turns} รอบแล้ว สรุปผลตรวจด้วย finish ตอนนี้จากข้อมูลที่มีอยู่ ห้ามเรียกเครื่องมืออีก"


def build_closing_after_malformed_instruction() -> str:
    """The one extra call after repeated malformed answers: a Finish and nothing else."""
    return "คำตอบก่อนหน้านี้ไม่ตรงรูปแบบ สรุปผลตรวจด้วย finish ตอนนี้จากข้อมูลที่มีอยู่ ห้ามเรียกเครื่องมืออีก"


# Longest instruction the repair prompt is given. The same ceiling the old
# request_repair schema carried: the repair model reads the instruction and the
# old sentence and nothing else, so it has to stay short enough to be read whole.
_MAX_REPAIR_INSTRUCTION_CHARS = 800

# Verdicts a rewrite cannot fix, because they are properties of the Need. Mirrors
# smart_vote.REPAIR_EXCLUDED, by value so this module imports nothing from stages.
_NEED_LEVEL_CODES = frozenset({"A_actor", "A_scope"})


def build_vote_repair_instruction_th(
    hard_hints_th: Sequence[str],
    soft_findings: Sequence[tuple[str, str]],
    hint_th: str,
) -> str:
    """The one instruction the repair model gets, built from what the code and
    the majority of judge runs agreed on.

    `soft_findings` is `(code, note_th)` for the criteria a majority failed.
    A_actor and A_scope are dropped here as well as by the caller: rewording
    cannot change who does the work or which profession it belongs to, and a
    repair spent on them is budget taken from the hard failures. Capped at 800
    characters, cut at the end, so the hint is what is lost first.
    """
    parts: list[str] = []
    if hard_hints_th:
        parts.append("เกณฑ์ที่โค้ดตรวจไม่ผ่าน:\n" + "\n".join(f"- {h}" for h in hard_hints_th))
    fixable = [(code, note) for code, note in soft_findings if code not in _NEED_LEVEL_CODES]
    if fixable:
        parts.append(
            "เกณฑ์ที่ผู้ตรวจส่วนใหญ่เห็นว่าไม่ผ่าน:\n"
            + "\n".join(f"- {code}: {note}" if note else f"- {code}" for code, note in fixable)
        )
    if hint_th:
        parts.append(f"ข้อเสนอของผู้ตรวจ: {hint_th}")
    text = "\n".join(parts)
    if len(text) > _MAX_REPAIR_INSTRUCTION_CHARS:
        text = text[: _MAX_REPAIR_INSTRUCTION_CHARS - 1] + "…"
    return text


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
