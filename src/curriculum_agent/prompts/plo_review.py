"""The PLO QA agent prompt: read the finished set, check a few suspicions, advise.

Stage 06. The agent is handed the set, the Need sentences behind it, and facts
code computed (spec 2026-10-12). It may check a suspicion with at most four tool
calls, then answers once. It sees no evidence text on purpose: the more upstream
detail a reviewer reads, the more it anchors on it instead of judging the set as
a curriculum committee reads it.

The answer is advice, so the prompt says outright that the reviewer rewrites
nothing — a reviewer handed the statements and no such line drifts into proposing
replacement sentences, which nothing downstream would check.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from curriculum_agent.stages.plo_review_facts import ReviewDossier


@dataclass(frozen=True)
class ReviewItem:
    plo_id: str
    is_optional: bool
    statement_th: str
    action_verb_th: str
    bloom_level: str
    current_ksec: tuple[str, ...]
    need_statements_th: tuple[str, ...]


_SYSTEM_TH = """คุณเป็นกรรมการตรวจคุณภาพหลักสูตรอุดมศึกษาไทยตามแนว OBE และมาตรฐาน อว.
งานของคุณคือตรวจ PLO ทั้งชุดที่ทำเสร็จแล้วของหลักสูตรหนึ่ง แล้วรายงานข้อเสนอแนะให้ผู้ออกแบบหลักสูตร
คุณไม่ได้แก้ PLO ห้ามเขียนประโยค PLO ใหม่ ให้บอกเพียงว่าควรปรับอะไรและเพราะอะไร
ตัวเลขในหัวข้อ "ข้อเท็จจริงที่ระบบนับให้" ถูกต้องแล้ว ไม่ต้องนับใหม่ ให้ตีความ

ตรวจ 6 เรื่อง
1) redundancies (ความซ้ำซ้อน): กลุ่ม PLO 2-3 ข้อที่กรรมการหลักสูตรจะอ่านว่าเป็นผลลัพธ์เดียวกัน
   คือมีงานหลักเดียวกันกับวัตถุประเภทเดียวกัน ต่างกันแค่บริบท เครื่องมือ หรือถ้อยคำ
   การอยู่ในสาขาเดียวกันหรือใช้เครื่องมือเดียวกันไม่ถือว่าซ้ำ เช่น ทุกข้อของหลักสูตรการแปลมีการแปลอยู่แล้ว
   แต่ละกลุ่ม: plo_ids, reason_th (ซ้ำกันตรงไหน), suggestion_th (ควรรวม หรือควรแยกวัตถุให้ชัดอย่างไร)
2) ksec (หมวดสมรรถนะรายข้อ): ทุก PLO ต้องมีหนึ่งรายการ ระบุหมวดที่ผลลัพธ์ตามที่เขียนไว้ควรอยู่
   เลือกได้มากกว่าหนึ่งหมวดจาก K S E C
   K = รู้และอธิบายองค์ความรู้, S = ลงมือทำงานของวิชาชีพ, E = คุณธรรมจริยธรรม,
   C = คุณลักษณะบุคคล เช่น การปรับตัว ภาวะผู้นำ การพัฒนาตนเอง
   ตัดสินจากสิ่งที่บัณฑิตทำในประโยค ไม่ใช่จากหมวดเดิม
   แต่ละรายการ: plo_id, suggested (list เช่น ["S","E"]), reason_th
3) bloom (ระดับ Bloom รายข้อ): ใส่เฉพาะ PLO ที่ระดับที่ประกาศไม่เหมาะกับกริยา กรรม และระดับปริญญา
   แต่ละรายการ: plo_id, suggested_level (remember understand apply analyze evaluate create), reason_th
4) coverage_th (KSEC ทั้งชุด): หนึ่งถึงสามประโยค ตีความจำนวน PLO ต่อหมวดที่ระบบนับให้
   หมวดไหนขาดหรือหนาแน่นเกิน และสำคัญอย่างไรกับหลักสูตรนี้
5) bloom_distribution_th (การกระจาย Bloom): หนึ่งถึงสามประโยค ตีความจำนวน PLO ต่อระดับเทียบระดับปริญญา
6) unused_needs (Need สำคัญที่ไม่ได้เป็น PLO): สำหรับแต่ละ Need ในรายการที่ให้มา
   need_id, verdict ("consider" = ควรพิจารณาใส่เป็น PLO, "ok_to_leave" = ปล่อยไว้ได้), reason_th
   Need ที่ยังไม่มีประโยค (ในรายการแสดงว่า "(ยังไม่มีประโยค Need ...)") ตัดสินว่า "consider" ไม่ได้จนกว่าผู้ออกแบบจะเขียนประโยคก่อน
   ให้ตอบ "ok_to_leave" หรือไม่ต้องใส่ในรายการ

summary_th: สรุป 2-5 ประโยคให้ผู้ออกแบบ เรียงเรื่องสำคัญก่อน

เครื่องมือ (ใช้ได้รวมไม่เกิน 4 ครั้ง ใช้เมื่อสงสัยจริงเท่านั้น ไม่ต้องใช้ก็ได้)
- bloom_lookup: arg = กริยาภาษาไทย ได้ระดับ Bloom ที่กริยานั้นอยู่ได้
- check_verbs: arg = plo_id ได้ผลตรวจกริยาของ PLO ข้อนั้นด้วยโค้ด
  (ประโยคขึ้นต้นด้วยกริยาที่ประกาศไหม กริยาที่ประกาศมีกี่คำ และอยู่ระดับใดได้บ้าง)
- need_detail: arg = need_id ของ Need ในรายการ Need ที่ไม่ได้เป็น PLO เท่านั้น
  ได้คำอธิบายของโมเดลที่เขียน Need นั้น จำนวนทักษะสมาชิก และจำนวนเสียงต่อกลุ่มผู้มีส่วนได้ส่วนเสีย

ทุกรอบตอบเป็น JSON object เดียว: {"reasoning_th": "...", "action": {...}}
เรียกเครื่องมือ: "action": {"kind": "call_tool", "tool": "check_verbs", "arg": "PLO3"}
สรุปผล: "action": {"kind": "finish", "redundancies": [...], "ksec": [...], "bloom": [...],
  "bloom_distribution_th": "...", "coverage_th": "...", "unused_needs": [...], "summary_th": "..."}
ถ้าชุด PLO ไม่มีปัญหาในเรื่องใด ให้ส่งรายการของเรื่องนั้นว่าง แต่ ksec ต้องมีครบทุก PLO และต้องมี summary_th เสมอ
ใช้ plo_id และ need_id ตามที่ให้มาเท่านั้น"""  # noqa: E501


# An unwritten Need's statement is "[ต้องทบทวน] " plus its member skill names, so
# printing it would hand the reviewer the skill-level detail it is kept away from.
# The stored finding keeps the real text; only the prompt is masked.
_UNWRITTEN_PLACEHOLDER_TH = "(ยังไม่มีประโยค Need — ผู้ออกแบบต้องเขียนก่อน)"
# The same, where a PLO's cited Need is the unwritten one (an older stored PLO).
UNWRITTEN_CITED_PLACEHOLDER_TH = "(Need นี้ยังไม่มีประโยค — ผู้ออกแบบต้องเขียนก่อน)"


def _ksec_label(tags: Sequence[str]) -> str:
    return "|".join(tags) if tags else "-"


def _counts_line(counts: Mapping[str, int], sep: str = " · ") -> str:
    return sep.join(f"{k} {v}" for k, v in counts.items())


def build_plo_review_prompt(dossier: ReviewDossier) -> list[dict[str, str]]:
    """The rubric, then the whole dossier in one user turn."""
    blocks: list[str] = []
    for item in dossier.items:
        needs = "\n".join(f"- {s}" for s in item.need_statements_th) or "- (ไม่พบ Need)"
        blocks.append(
            f"[{item.plo_id}] ({'เสริม' if item.is_optional else 'หลัก'})\n"
            f"ประโยค: {item.statement_th}\n"
            f"กริยา: {item.action_verb_th} | ระดับ Bloom: {item.bloom_level} | "
            f"KSEC ปัจจุบัน: {_ksec_label(item.current_ksec)}\n"
            f"Need ที่อ้างถึง:\n{needs}"
        )
    cov = dossier.ksec_coverage
    hist = dossier.bloom_histogram
    facts = (
        "ข้อเท็จจริงที่ระบบนับให้ (KSEC และ Bloom นับทุก PLO รวม PLO เสริม):\n"
        f"- PLO หลัก {dossier.core_count} ข้อ (นโยบาย 6-10 ข้อ)\n"
        f"- KSEC: {_counts_line(cov.counts)} | หมวดที่ไม่มี: {', '.join(cov.missing) or '-'} | "
        f"ธง: {', '.join(cov.flags) or '-'}\n"
        f"- Bloom ({hist.degree_level or '-'}): {_counts_line(hist.counts, ', ')} | "
        f"ธง: {', '.join(hist.flags) or '-'}"
    )
    if dossier.unused_needs:
        unused = "\n".join(
            f"[{u.need_id}] demand {u.demand_score:.2f} | KSEC {u.ksec_category} | "
            f"ผู้ขอ: {', '.join(u.stakeholder_types) or '-'} | เหตุที่ไม่ได้ใช้: {u.exclusion}\n"
            f"  {_UNWRITTEN_PLACEHOLDER_TH if u.unwritten else u.statement_th}"
            for u in dossier.unused_needs
        )
    else:
        unused = "ไม่มี Need สำคัญที่ไม่ได้เป็น PLO"
    header = f"หลักสูตร: {dossier.program_context}\n" if dossier.program_context else ""
    user = (
        f"{header}PLO ทั้งหมด {len(dossier.items)} ข้อ:\n\n"
        + "\n\n".join(blocks)
        + f"\n\n{facts}\n\nNeed สำคัญที่ไม่ได้เป็น PLO:\n{unused}"
    )
    return [
        {"role": "system", "content": _SYSTEM_TH},
        {"role": "user", "content": user},
    ]


def build_review_observation(tool: str, payload: Mapping[str, Any]) -> str:
    """A tool result, as the next user turn."""
    return f"ผลจาก {tool}:\n{json.dumps(payload, ensure_ascii=False)}"


def build_review_refusal(reason_th: str) -> str:
    """A refused tool call, as the next user turn."""
    return f"ปฏิเสธ: {reason_th}"
