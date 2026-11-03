from __future__ import annotations

from curriculum_agent.models import BloomLevel
from curriculum_agent.smart_vocabulary import FORBIDDEN_WORDS_TH
from curriculum_agent.stages.bloom_verbs import verbs_for_level

_MAX_EXAMPLE_VERBS = 3

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
    # The level is named in English, not by a Thai label: the Thai names of the two
    # lowest levels are forbidden PLO words, and a note that used one would prime
    # the draft toward the very failure the SMART gate rejects.
    verbs = [v for v in verbs_for_level(suggested) if not any(w in v for w in FORBIDDEN_WORDS_TH)][
        :_MAX_EXAMPLE_VERBS
    ]
    note = (
        f"ผู้ตรวจชุด PLO เห็นว่า PLO ข้อนี้ควรอยู่ระดับ Bloom: {suggested.value.capitalize()} "
        "กรุณาเขียนผลลัพธ์การเรียนรู้ใหม่ในระดับนี้ โดยใช้กริยาที่วัดผลได้ในระดับนั้นเพียงตัวเดียว"
    )
    if verbs:
        note += f" ตัวอย่างกริยา: {', '.join(verbs)}"
    if reason:
        note += f' เหตุผลของผู้ตรวจ: "{reason}"'
    return note
