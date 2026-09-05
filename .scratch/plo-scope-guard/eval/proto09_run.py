"""Ticket 09 prototype: can the extraction prompt separate a graduate capability
from an activity of the institution?

Throwaway. Four treatments against ticket 02's control (A_none), same 14
evidence items, same model, so the numbers compare.

  T1_rule    system prompt gains one rule; schema untouched
  T2_field   schema gains is_graduate_capability; prompt describes it
  T3_rewrite model may restate an institution-side capability graduate-side
  T4_combo   T2 plus ticket 02's winning scope statement (C_narrow)

The original system prompt is read from the real builder and appended to, so a
change to the real prompt shows up here rather than silently drifting.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from curriculum_agent.llm import complete_extraction
from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt
from curriculum_agent.stages.skill_extraction import chunk_evidence_text

HERE = Path(__file__).parent
EVIDENCE = json.loads((HERE / "evidence.json").read_text(encoding="utf-8"))
OUT = HERE / "proto09_results.json"

FIELD_TH = "การแปลและการล่ามภาษาจีน-ไทยเพื่อธุรกิจ"
PROGRAM_TH = "วิทยาลัยนานาชาติไทย-จีนเพื่อการจัดการ"
SCOPE_C_NARROW = (
    "หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจและกฎหมายจีน-ไทย การล่ามการเจรจาธุรกิจ "
    "การตรวจแก้งานแปลที่ได้จากเครื่อง (post-editing) และความรู้ด้านวัฒนธรรมและ"
    "มารยาททางธุรกิจจีนที่จำเป็นต่องานแปลและล่าม"
)


# --- schemas -----------------------------------------------------------------
class _Base(BaseModel):
    skill_name_th: str = Field(min_length=1)
    skill_name_en: str | None = None
    ksec_category: Literal["K", "S", "E", "C"]
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
    evidence_span_th: str = Field(min_length=12)
    is_field_relevant: bool = True
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)

    @field_validator("skill_name_th", "evidence_span_th", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class _PlainResponse(BaseModel):
    skills: list[_Base]


class _FlagItem(_Base):
    is_graduate_capability: bool = True


class _FlagResponse(BaseModel):
    skills: list[_FlagItem]


class _RewriteItem(_Base):
    is_graduate_capability: bool = True
    # Set only when the model restated an institution-side ask graduate-side.
    original_phrasing_th: str | None = None


class _RewriteResponse(BaseModel):
    skills: list[_RewriteItem]


# --- prompt fragments ---------------------------------------------------------
RULE_TH = (
    "- ทักษะทุกข้อต้องเป็นสิ่งที่ 'บัณฑิตทำได้เมื่อสำเร็จการศึกษา' เท่านั้น "
    "ห้ามเสนอสิ่งที่หลักสูตร สถาบัน คณะ หรืออาจารย์เป็นผู้ทำ "
    "เช่น การดึงดูดนักศึกษา การบริหารทรัพยากรของสถาบัน การปรับปรุงหลักสูตร "
    "การวัดผลลัพธ์การเรียนรู้ของผู้เรียน หรือการพัฒนาศักยภาพอาจารย์\n"
)
FIELD_TH_RULE = (
    "- is_graduate_capability = true เมื่อทักษะนั้นเป็นสิ่งที่บัณฑิตคนหนึ่งทำได้เมื่อสำเร็จ"
    "การศึกษา; = false เมื่อเป็นสิ่งที่หลักสูตร สถาบัน คณะ หรืออาจารย์เป็นผู้ทำ "
    "(เช่น การดึงดูดนักศึกษา การบริหารทรัพยากรของสถาบัน การปรับปรุงหลักสูตร "
    "การวัดผลลัพธ์การเรียนรู้ของผู้เรียน การพัฒนาศักยภาพอาจารย์) "
    "ห้ามตัดทิ้งเอง ให้ติดธงไว้ ผู้ออกแบบหลักสูตรจะเป็นผู้ตัดสิน\n"
    "  เพิ่ม field is_graduate_capability: true|false ในทุกรายการ\n"
)
REWRITE_RULE_TH = (
    "- ถ้าข้อความ evidence พูดถึงสิ่งที่หลักสูตร สถาบัน คณะ หรืออาจารย์เป็นผู้ทำ "
    "ให้ 'เขียนใหม่' เป็นสมรรถนะฝั่งบัณฑิตถ้าเขียนได้ แล้วใส่ถ้อยคำเดิมไว้ที่ "
    "original_phrasing_th เช่น 'ต้องการหลักสูตรที่ผสาน AI เข้ากับการเรียนรู้' "
    "→ skill_name_th = 'การใช้ปัญญาประดิษฐ์ในงานแปลและล่าม', "
    "original_phrasing_th = 'หลักสูตรที่ผสาน AI เข้ากับการเรียนรู้'\n"
    "- ถ้าเขียนใหม่เป็นฝั่งบัณฑิตไม่ได้เลย (เช่น การดึงดูดนักศึกษา "
    "การบริหารทรัพยากรของสถาบัน การรับรองอัตราการได้งานทำ) "
    "ให้คงไว้แต่ตั้ง is_graduate_capability = false ห้ามตัดทิ้งเอง\n"
    "  เพิ่ม field is_graduate_capability: true|false และ original_phrasing_th "
    "(หรือ null ถ้าไม่ได้เขียนใหม่) ในทุกรายการ\n"
)

TREATMENTS: dict[str, tuple[type[BaseModel], str, str | None]] = {
    "T1_rule": (_PlainResponse, RULE_TH, None),
    "T2_field": (_FlagResponse, FIELD_TH_RULE, None),
    "T3_rewrite": (_RewriteResponse, REWRITE_RULE_TH, None),
    "T4_combo": (_FlagResponse, FIELD_TH_RULE, SCOPE_C_NARROW),
}


def build_messages(
    chunk: str, classification: str, extra_rule: str, scope_th: str | None
) -> list[dict[str, str]]:
    messages = build_extract_skills_prompt(
        chunk, classification, field_th=FIELD_TH, program_name_th=PROGRAM_TH
    )
    system = messages[0]["content"]
    # Append the treatment rule to the rules block, before the JSON spec, so it
    # reads as one of the rules rather than an afterthought.
    marker = "ตอบเป็น JSON object:"
    head, sep, tail = system.partition(marker)
    messages[0]["content"] = f"{head}{extra_rule}\n{sep}{tail}"
    if scope_th:
        user = messages[1]["content"]
        head_u, _, body = user.partition("\n" + chunk)
        messages[1]["content"] = f"{head_u}\n[ขอบเขตหลักสูตร: {scope_th}]\n{chunk}{body}"
    return messages


async def run_one(
    item: dict[str, Any],
    chunk: str,
    widx: int,
    name: str,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    schema, rule, scope = TREATMENTS[name]
    messages = build_messages(chunk, item["classification"], rule, scope)
    async with sem:
        try:
            result = await complete_extraction(schema, messages)
        except Exception as exc:  # noqa: BLE001 - prototype
            return {
                "variant": name,
                "evidence_id": item["evidence_id"],
                "window": widx,
                "error": repr(exc)[:300],
                "skills": [],
            }
    return {
        "variant": name,
        "evidence_id": item["evidence_id"],
        "stakeholder_type": item["stakeholder_type"],
        "window": widx,
        "skills": [
            {
                "name": s.skill_name_th,
                "ksec": s.ksec_category,
                "relevant": s.is_field_relevant,
                "graduate": getattr(s, "is_graduate_capability", None),
                "original": getattr(s, "original_phrasing_th", None),
            }
            for s in result.skills
        ],
    }


async def main() -> None:
    sem = asyncio.Semaphore(6)
    tasks = []
    for name in TREATMENTS:
        for item in EVIDENCE:
            chunks, _ = chunk_evidence_text(item["raw_text_th"])
            for widx, chunk in enumerate(chunks):
                tasks.append(run_one(item, chunk, widx, name, sem))
    print(f"firing {len(tasks)} calls...")
    results = await asyncio.gather(*tasks)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    errors = [r for r in results if r.get("error")]
    print(f"done. {len(results)} calls, {len(errors)} errors -> {OUT}")
    if errors:
        print("first error:", errors[0]["error"])


if __name__ == "__main__":
    asyncio.run(main())
