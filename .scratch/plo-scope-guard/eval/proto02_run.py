"""Ticket 02 prototype, part 2: does a scope statement move is_field_relevant?

Throwaway. Does NOT touch src/: the scope line is injected into the user header
the same way ticket 03 proposes to add it (conditional append after
[สาขาวิชา: ...]), so the real prompt builder stays unmodified and the real
contract fingerprint is unaffected.

Five variants, including a no-scope baseline that must reproduce today's
behaviour byte-for-byte in the prompt.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from curriculum_agent.llm import complete_extraction
from curriculum_agent.prompts.extract_skills import build_extract_skills_prompt
from curriculum_agent.stages.skill_extraction import (
    _ExtractedSkillsResponse,
    chunk_evidence_text,
)

HERE = Path(__file__).parent
EVIDENCE = json.loads((HERE / "evidence.json").read_text(encoding="utf-8"))
OUT = HERE / "proto02_results.json"

FIELD_TH = "การแปลและการล่ามภาษาจีน-ไทยเพื่อธุรกิจ"
PROGRAM_TH = "วิทยาลัยนานาชาติไทย-จีนเพื่อการจัดการ"

# The five scope statements under test. "A" is the control.
VARIANTS: dict[str, str | None] = {
    "A_none": None,
    "B_broad": (
        "หลักสูตรนี้ผลิตบัณฑิตด้านการแปลและการล่ามภาษาจีน-ไทย "
        "สำหรับงานธุรกิจและการค้าระหว่างประเทศ"
    ),
    "C_narrow": (
        "หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจและกฎหมายจีน-ไทย การล่ามการเจรจาธุรกิจ "
        "การตรวจแก้งานแปลที่ได้จากเครื่อง (post-editing) และความรู้ด้านวัฒนธรรมและ"
        "มารยาททางธุรกิจจีนที่จำเป็นต่องานแปลและล่าม"
    ),
    "D_with_exclusions": (
        "หลักสูตรนี้ครอบคลุมการแปลเอกสารธุรกิจและกฎหมายจีน-ไทย การล่ามการเจรจาธุรกิจ "
        "การตรวจแก้งานแปลที่ได้จากเครื่อง (post-editing) และความรู้ด้านวัฒนธรรมและ"
        "มารยาททางธุรกิจจีนที่จำเป็นต่องานแปลและล่าม\n"
        "ไม่รวมถึง: การตลาดดิจิทัลและการผลิตคอนเทนต์เพื่อการขาย การบริหารธุรกิจทั่วไป "
        "การเป็นผู้ประกอบการ การพัฒนาซอฟต์แวร์หรือระบบ AI "
        "และงานบริหารจัดการของสถาบันการศึกษา"
    ),
    "E_vague": "หลักสูตรนี้เน้นผลิตบัณฑิตคุณภาพสูงที่ตอบโจทย์ตลาดแรงงานยุคใหม่",
}


def build_messages(chunk: str, classification: str, scope_th: str | None) -> list[dict[str, str]]:
    """Real builder, then the conditional scope line ticket 03 proposes."""
    messages = build_extract_skills_prompt(
        chunk, classification, field_th=FIELD_TH, program_name_th=PROGRAM_TH
    )
    if scope_th:
        user = messages[1]["content"]
        # Insert after the [สาขาวิชา: ...] header line, before the evidence body.
        head, _, body = user.partition("\n" + chunk)
        messages[1]["content"] = f"{head}\n[ขอบเขตหลักสูตร: {scope_th}]\n{chunk}{body}"
    return messages


async def extract_one(
    item: dict[str, Any], chunk: str, widx: int, variant: str, scope: str | None, sem: asyncio.Semaphore
) -> dict[str, Any]:
    messages = build_messages(chunk, item["classification"], scope)
    async with sem:
        try:
            result = await complete_extraction(_ExtractedSkillsResponse, messages)
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
            }
            for s in result.skills
        ],
    }


async def main() -> None:
    sem = asyncio.Semaphore(6)
    tasks = []
    for variant, scope in VARIANTS.items():
        for item in EVIDENCE:
            chunks, unread = chunk_evidence_text(item["raw_text_th"])
            if unread:
                print(f"WARN {item['evidence_id']} left {unread} chars unread")
            for widx, chunk in enumerate(chunks):
                tasks.append(extract_one(item, chunk, widx, variant, scope, sem))

    print(f"firing {len(tasks)} extraction calls...")
    results = await asyncio.gather(*tasks)
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    errors = [r for r in results if r.get("error")]
    print(f"done. {len(results)} calls, {len(errors)} errors -> {OUT}")
    if errors:
        print("first error:", errors[0]["error"])


if __name__ == "__main__":
    asyncio.run(main())
