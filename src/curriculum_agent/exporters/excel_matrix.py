from __future__ import annotations

import io

import pandas as pd

from curriculum_agent.models import PLO, Need
from curriculum_agent.smart_vocabulary import FINDING_LABEL_TH, SmartFindingCode

# Column order of the exported sheet. Exposed so tests and any future consumer
# index by name rather than by position — a reordering here must not silently
# shift what a caller reads.
MATRIX_HEADERS = (
    "PLO",
    "ผลลัพธ์การเรียนรู้",
    "ระดับ Bloom",
    "หมวดสมรรถนะ",
    "ประเภท",
    "สถานะ",
    "ข้อสังเกต",
    "ข้อวินิจฉัย",
)


def _status_th(plo: PLO) -> str:
    """Three answers, not two.

    "ผ่าน" / "ต้องแก้ไข" was a false dichotomy: a hand-edited statement nothing
    has re-judged, and a verdict the pure checks reached alone because the
    validator could not run, are neither passed nor known to need repair. This
    file is what leaves the tool, so it must not overstate what was checked.
    """
    if plo.smart_escalated:
        return "ต้องแก้ไข"
    if plo.smart_validated_by in ("stale", "code_only"):
        return "ยังไม่ได้ตรวจครบ"
    return "ผ่าน"


def _findings_th(plo: PLO) -> str:
    """The soft findings in Thai.

    `"; ".join(plo.soft_flags)` used to drop raw English codes into a Thai
    workbook a designer sends to MHESI. The labels come from the same map the
    rubric and the frontend read.
    """
    soft = [f for f in plo.smart_check.findings if f.severity == "soft"]
    if soft:
        return "; ".join(
            f"{FINDING_LABEL_TH[f.criterion]}" + (f" ({f.note_th})" if f.note_th else "")
            for f in soft
        )
    # Rows written before findings existed still carry the flat code list.
    return "; ".join(
        FINDING_LABEL_TH.get(SmartFindingCode(flag), flag)
        if flag in {c.value for c in SmartFindingCode}
        else flag
        for flag in plo.soft_flags
    )


def _ksec_tags(plo: PLO, needs_by_id: dict[str, Need]) -> str:
    """The competency domains behind one PLO, deduplicated, in first-seen order.

    A PLO carries no KSEC tag of its own — the domain is a property of the Needs
    it answers, so this is the only place the two meet. An id that resolves to
    nothing yields no tag rather than raising: `plo_report` already warns about
    unresolved ids, and the designer needs the file to see which outcome lost its
    trail.
    """
    tags: list[str] = []
    for need_id in plo.source_need_ids:
        need = needs_by_id.get(need_id)
        if need is None:
            continue
        value = need.ksec_category.value
        if value not in tags:
            tags.append(value)
    return ", ".join(tags)


def export_matrix_xlsx(plos: list[PLO], needs_by_id: dict[str, Need] | None = None) -> bytes:
    """Export the PLO set as an Excel workbook, one row per outcome.

    `needs_by_id` is optional so a caller holding only PLOs can still export;
    without it the competency-domain column is empty, since that value lives on
    the Needs.

    Escalated outcomes are exported with a status marking them for repair rather
    than filtered out — a PLO that failed the SMART gate must stay visible to the
    designer, and an export that quietly omitted it would hide work that has to
    be done.
    """
    if not plos:
        raise ValueError("ไม่มี PLO สำหรับส่งออก — รัน PLO Synthesis ก่อน")

    resolved = needs_by_id or {}
    rows = [
        {
            "PLO": plo.plo_id,
            "ผลลัพธ์การเรียนรู้": plo.statement_th,
            "ระดับ Bloom": plo.bloom_level.value,
            "หมวดสมรรถนะ": _ksec_tags(plo, resolved),
            "ประเภท": "เสริม" if plo.is_optional else "หลัก",
            "สถานะ": _status_th(plo),
            "ข้อสังเกต": _findings_th(plo),
            # The whole point of the validator is that its diagnosis is
            # actionable, and this file is what a designer works from.
            "ข้อวินิจฉัย": plo.smart_diagnosis_th or "",
        }
        for plo in plos
    ]

    df = pd.DataFrame(rows, columns=list(MATRIX_HEADERS))
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()
