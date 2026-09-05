"""Ticket 13: does the scope statement still leak into extractions from the
system prompt, the way it does from the user header?

Throwaway. Does NOT touch src/. Same C_narrow statement as ticket 02, same
evidence set, same model — only the position moves. Both variants carry the
is_graduate_capability flag ticket 11 settled on, so the comparison is position
alone rather than position plus schema.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from curriculum_agent.llm import complete_extraction, describe_target
from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt
from curriculum_agent.stages.skill_extraction import chunk_evidence_text

HERE = Path(__file__).parent
EVIDENCE = json.loads((HERE / "evidence.json").read_text(encoding="utf-8"))
OUT = HERE / "proto13_results.json"

FIELD_TH = "การแปลและการล่ามภาษาจีน-ไทยเพื่อธุรกิจ"
PROGRAM_TH = "วิทยาลัยนานาชาติไทย-จีนเพื่อการจัดการ"

SCOPE_TH = (
    "หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจและกฎหมายจีน-ไทย การล่ามการเจรจาธุรกิจ "
    "การตรวจแก้งานแปลที่ได้จากเครื่อง (post-editing) และความรู้ด้านวัฒนธรรมและ"
    "มารยาททางธุรกิจจีนที่จำเป็นต่องานแปลและล่าม"
)

GRAD_RULE = (
    "- is_graduate_capability = true เมื่อทักษะนั้นเป็นสิ่งที่บัณฑิตคนหนึ่งทำได้เมื่อสำเร็จ"
    "การศึกษา; false เมื่อเป็นกิจกรรมหรือภารกิจของสถาบัน/หลักสูตร (เช่น การบริหารหลักสูตร "
    "การจัดหางบประมาณ การสร้างความร่วมมือระดับองค์กร) ให้คงไว้แต่ตั้งเป็น false "
    "ห้ามตัดทิ้งเอง\n"
)

SCOPE_RULE = (
    f"- ขอบเขตของหลักสูตรนี้: {SCOPE_TH}\n"
    "  ใช้บรรทัดนี้เป็นเกณฑ์ตัดสิน is_field_relevant เท่านั้น "
    "ห้ามสกัดทักษะจากบรรทัดนี้ ทักษะทุกรายการต้องมาจากข้อความ evidence เท่านั้น\n"
)

_MARKER = "ตอบเป็น JSON object:"


class _Item(BaseModel):
    skill_name_th: str
    skill_name_en: str | None = None
    ksec_category: str
    bloom_level: str
    evidence_span_th: str
    is_field_relevant: bool = True
    is_graduate_capability: bool = True
    confidence: float = Field(default=0.8, ge=0, le=1)


class _Response(BaseModel):
    skills: list[_Item]


def build_messages(chunk: str, classification: str, variant: str) -> list[dict[str, str]]:
    messages = build_extract_skills_prompt(
        chunk, classification, field_th=FIELD_TH, program_name_th=PROGRAM_TH
    )
    system = messages[0]["content"]
    extra = GRAD_RULE + (SCOPE_RULE if variant == "S_system" else "")
    head, sep, tail = system.partition(_MARKER)
    schema_line = (
        "  is_graduate_capability: true|false — เป็นสมรรถนะของบัณฑิตหรือไม่,\n"
    )
    tail = tail.replace("  confidence: 0.0-1.0\n", schema_line + "  confidence: 0.0-1.0\n", 1)
    messages[0]["content"] = f"{head}{extra}\n{sep}{tail}"

    if variant == "U_user":
        user = messages[1]["content"]
        head_u, _, body = user.partition("\n" + chunk)
        messages[1]["content"] = f"{head_u}\n[ขอบเขตหลักสูตร: {SCOPE_TH}]\n{chunk}{body}"
    return messages


async def extract_one(
    item: dict[str, Any], chunk: str, widx: int, variant: str, sem: asyncio.Semaphore
) -> dict[str, Any]:
    messages = build_messages(chunk, item["classification"], variant)
    async with sem:
        try:
            result = await complete_extraction(_Response, messages)
        except Exception as exc:  # noqa: BLE001 - prototype: record and move on
            return {
                "variant": variant,
                "evidence_id": item["evidence_id"],
                "window": widx,
                "error": repr(exc)[:300],
                "skills": [],
            }
    return {
        "variant": variant,
        "evidence_id": item["evidence_id"],
        "stakeholder_type": item["stakeholder_type"],
        "window": widx,
        "skills": [
            {
                "name": s.skill_name_th,
                "ksec": s.ksec_category,
                "relevant": s.is_field_relevant,
                "graduate": s.is_graduate_capability,
                "span": s.evidence_span_th,
            }
            for s in result.skills
        ],
    }


async def main() -> None:
    print(describe_target())
    sem = asyncio.Semaphore(6)
    tasks = []
    for variant in ("U_user", "S_system"):
        for item in EVIDENCE:
            chunks, unread = chunk_evidence_text(item["raw_text_th"])
            for widx, chunk in enumerate(chunks):
                tasks.append(extract_one(item, chunk, widx, variant, sem))

    print(f"firing {len(tasks)} extraction calls...")
    results = await asyncio.gather(*tasks)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    errors = [r for r in results if r.get("error")]
    print(f"done. {len(results)} calls, {len(errors)} errors -> {OUT}")
    if errors:
        print("first error:", errors[0]["error"])


if __name__ == "__main__":
    asyncio.run(main())
