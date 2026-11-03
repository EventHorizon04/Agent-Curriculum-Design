from __future__ import annotations

from curriculum_agent.models import BloomLevel

_LEVEL_TH: dict[BloomLevel, str] = {
    BloomLevel.REMEMBER: "จำ (remember)",
    BloomLevel.UNDERSTAND: "เข้าใจ (understand)",
    BloomLevel.APPLY: "ประยุกต์ใช้ (apply)",
    BloomLevel.ANALYZE: "วิเคราะห์ (analyze)",
    BloomLevel.EVALUATE: "ประเมินค่า (evaluate)",
    BloomLevel.CREATE: "สร้างสรรค์ (create)",
}

# The reviewer's reason is quoted, not paraphrased; this keeps the whole note well
# inside the 500-character limit a designer's note has.
_MAX_REASON_CHARS = 280


def build_bloom_redraft_note_th(suggested: BloomLevel, reason_th: str) -> str:
    """The note sent with a Bloom redraft: write the outcome at `suggested`.

    Goes through the `note_th` channel of `draft_from_needs`, so it is read as
    guidance on wording, not as a rule that overrides the PLO prompt. The reason
    is the reviewer's own words; an empty one is simply left out.
    """
    reason = reason_th.strip()
    if len(reason) > _MAX_REASON_CHARS:
        reason = reason[:_MAX_REASON_CHARS].rstrip() + "…"
    note = (
        f"ผู้ตรวจชุด PLO เห็นว่า PLO ข้อนี้ควรอยู่ระดับ Bloom: {_LEVEL_TH[suggested]} "
        "กรุณาเขียนผลลัพธ์การเรียนรู้ใหม่ในระดับนี้ โดยใช้กริยาที่วัดผลได้ในระดับนั้นเพียงตัวเดียว"
    )
    if reason:
        note += f' เหตุผลของผู้ตรวจ: "{reason}"'
    return note
