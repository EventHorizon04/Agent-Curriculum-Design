"""The PLO set review prompt: read the finished set, advise, change nothing.

Every other check reads one PLO against its own Needs. This one reads the set,
because redundancy between drafts, a domain that spans KSEC tags, and a Bloom
distribution are properties of the set. See
docs/superpowers/specs/2026-10-04-plo-set-review-design.md.

The answer is advice, so the prompt says outright that the reviewer rewrites
nothing — a reviewer handed the statements and no such line drifts into
proposing replacement sentences, which nothing downstream would check.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewItem:
    plo_id: str
    is_optional: bool
    statement_th: str
    action_verb_th: str
    bloom_level: str
    current_ksec: tuple[str, ...]
    need_statements_th: tuple[str, ...]


_SYSTEM_TH = """คุณเป็นกรรมการพิจารณาหลักสูตรอุดมศึกษาไทยตามแนว OBE และมาตรฐาน อว.
งานของคุณคือตรวจ PLO ทั้งชุดของหลักสูตรหนึ่ง แล้วรายงานข้อเสนอแนะให้ผู้ออกแบบหลักสูตร
คุณไม่ได้แก้ PLO ห้ามเขียนประโยค PLO ใหม่ ให้บอกเพียงว่าควรปรับอะไรและเพราะอะไร

ตรวจ 3 เรื่อง
1) redundancies (ความซ้ำซ้อน): กลุ่ม PLO 2-3 ข้อที่กรรมการหลักสูตรจะอ่านว่าเป็นผลลัพธ์เดียวกัน
   คือมีงานหลักเดียวกันกับวัตถุประเภทเดียวกัน ต่างกันแค่บริบท เครื่องมือ หรือถ้อยคำ
   การอยู่ในสาขาเดียวกันหรือใช้เครื่องมือเดียวกันไม่ถือว่าซ้ำ เช่น ทุกข้อของหลักสูตรการแปลมีการแปลอยู่แล้ว
   แต่ละกลุ่ม: plo_ids, reason_th (ซ้ำกันตรงไหน), suggestion_th (ควรรวม หรือควรแยกวัตถุให้ชัดอย่างไร)
2) ksec (หมวดสมรรถนะ): ทุก PLO ต้องมีหนึ่งรายการ ระบุหมวดที่ผลลัพธ์ตามที่เขียนไว้ควรอยู่
   เลือกได้มากกว่าหนึ่งหมวดจาก K S E C
   K = รู้และอธิบายองค์ความรู้, S = ลงมือทำงานของวิชาชีพ, E = คุณธรรมจริยธรรม,
   C = คุณลักษณะบุคคล เช่น การปรับตัว ภาวะผู้นำ การพัฒนาตนเอง
   ตัดสินจากสิ่งที่บัณฑิตทำในประโยค ไม่ใช่จากหมวดเดิม
   แต่ละรายการ: plo_id, suggested (list เช่น ["S","E"]), reason_th
3) bloom (ระดับ Bloom): ใส่เฉพาะ PLO ที่ระดับที่ประกาศไม่เหมาะกับกริยา กรรม และระดับปริญญา
   แต่ละรายการ: plo_id, suggested_level (remember understand apply analyze evaluate create),
   reason_th
   และ bloom_distribution_th: หนึ่งถึงสองประโยคเรื่องการกระจายระดับ Bloom ทั้งชุดเทียบกับระดับปริญญา

summary_th: สรุป 2-5 ประโยคให้ผู้ออกแบบ เรียงเรื่องสำคัญก่อน
ถ้าชุด PLO ไม่มีปัญหาในเรื่องใด ให้ส่งรายการของเรื่องนั้นว่าง แต่ ksec ต้องมีครบทุก PLO และต้องมี summary_th เสมอ
ใช้ plo_id ตามที่ให้มาเท่านั้น

ตอบเป็น JSON object เดียว:
{"redundancies": [...], "ksec": [...], "bloom": [...], "bloom_distribution_th": "...", "summary_th": "..."}"""  # noqa: E501


def _ksec_label(tags: tuple[str, ...]) -> str:
    return "|".join(tags) if tags else "-"


def build_plo_review_prompt(
    items: Sequence[ReviewItem], *, program_context: str | None = None
) -> list[dict[str, str]]:
    """The rubric, then the whole set in one user turn."""
    blocks: list[str] = []
    for item in items:
        needs = "\n".join(f"- {s}" for s in item.need_statements_th) or "- (ไม่พบ Need)"
        blocks.append(
            f"[{item.plo_id}] ({'เสริม' if item.is_optional else 'หลัก'})\n"
            f"ประโยค: {item.statement_th}\n"
            f"กริยา: {item.action_verb_th} | ระดับ Bloom: {item.bloom_level} | "
            f"KSEC ปัจจุบัน: {_ksec_label(item.current_ksec)}\n"
            f"Need ที่อ้างถึง:\n{needs}"
        )
    header = f"หลักสูตร: {program_context}\n" if program_context else ""
    user = f"{header}PLO ทั้งหมด {len(items)} ข้อ:\n\n" + "\n\n".join(blocks)
    return [
        {"role": "system", "content": _SYSTEM_TH},
        {"role": "user", "content": user},
    ]
