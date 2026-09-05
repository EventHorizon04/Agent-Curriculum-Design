"""Ticket 02 prototype, part 1: split the real stakeholder docx into evidence items.

Throwaway. Mirrors how the real pipeline would ingest this document: one
StakeholderEvidence row per stakeholder voice, each with its own type, rather
than one giant blob. The split is by the section headings the document itself
uses.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

DOCX = Path("E:/SideProject/Agent-Curriculum-Design/Data/ความต้องการของผู้มีส่วนได้ส่วนเสีย การแป.docx")
OUT = Path(__file__).with_name("evidence.json")

# Heading -> stakeholder_type. The headings are verbatim from the document.
SECTIONS: list[tuple[str, str, str]] = [
    ("การพัฒนาประเทศตามแผนพัฒนาเศรษฐกิจ", "ev01", "institutional_direction"),
    ("แผนการอุดมศึกษาเพื่อผลิตและพัฒนากำลังคน", "ev02", "institutional_direction"),
    ("วิสัยทัศน์มหาวิทยาลัยหอการค้าไทย", "ev03", "institutional_direction"),
    ("วิสัยทัศน์วิทยาลัยนานาชาติไทย-จีน", "ev04", "institutional_direction"),
    ("ปรัชญา วิทยาลัยนานาชาติไทย-จีน", "ev05", "institutional_direction"),
    ("ผู้ประกอบการด้านการเจรจาธุรกิจ", "ev06", "employer"),
    ("ผู้ประกอบการด้านกฎหมาย", "ev07", "employer"),
    ("ผู้ประกอบการด้านมีเดีย", "ev08", "employer"),
    ("ชุมชน / สังคม", "ev09", "community"),
    ("ผู้บริหารคณะ", "ev10", "administrator"),
    ("อาจารย์ผู้รับผิดชอบหลักสูตร", "ev11", "program_committee"),
    ("อาจารย์ผู้สอน", "ev12", "faculty"),
    ("ผู้คาดหวังเข้าศึกษาต่อ (นักเรียน", "ev13", "applicant"),
    ("ศิษย์เก่าสาขาใกล้เคียง", "ev14", "alumni"),
]


def docx_lines(path: Path) -> list[str]:
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return [ln.strip() for ln in xml.split("\n")]


def main() -> None:
    lines = docx_lines(DOCX)
    # Index of the line that starts each section.
    starts: list[tuple[int, str, str]] = []
    for needle, eid, stype in SECTIONS:
        for i, ln in enumerate(lines):
            if ln.startswith(needle) and not any(s[0] == i for s in starts):
                starts.append((i, eid, stype))
                break
        else:
            raise SystemExit(f"heading not found: {needle!r}")
    starts.sort()

    items = []
    for pos, (i, eid, stype) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        body = " ".join(ln for ln in lines[i:end] if ln)
        items.append(
            {
                "evidence_id": eid,
                "stakeholder_type": stype,
                # classify_evidence_type in code: requirement for
                # professional_council / institutional_direction, else general.
                "classification": (
                    "requirement" if stype == "institutional_direction" else "general"
                ),
                "raw_text_th": body,
                "chars": len(body),
            }
        )

    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(items)} evidence items -> {OUT}")
    for it in items:
        print(f"  {it['evidence_id']} {it['stakeholder_type']:24} {it['chars']:5} chars")


if __name__ == "__main__":
    main()
