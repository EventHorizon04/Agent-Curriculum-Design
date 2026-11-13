from __future__ import annotations

from collections.abc import Sequence

from curriculum_agent.models import BloomLevel
from curriculum_agent.smart_vocabulary import FORBIDDEN_WORDS_TH, mask_forbidden_words
from curriculum_agent.stages.bloom_verbs import verbs_for_level

_MAX_EXAMPLE_VERBS = 3

# The reviewer's reason and suggestion are quoted, not paraphrased; each is capped
# so that a note stays inside `MAX_NOTE_CHARS` together with the old statements.
_MAX_REASON_CHARS = 280
MAX_NOTE_CHARS = 900
_OLD_LABEL = "ร่างเดิมที่ผู้ตรวจติ:"
_MIN_STATEMENT_CHARS = 40


def _clip(text: str, limit: int) -> str:
    """Mask forbidden words, then cap at `limit` characters (masking first: it
    changes the length)."""
    text = mask_forbidden_words(text.strip())
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _quoted_review(reason_th: str, suggestion_th: str, cap: int = _MAX_REASON_CHARS) -> str:
    parts = []
    reason = _clip(reason_th, cap)
    if reason:
        parts.append(f' เหตุผลของผู้ตรวจ: "{reason}"')
    suggestion = _clip(suggestion_th, cap)
    if suggestion:
        parts.append(f' ข้อเสนอของผู้ตรวจ: "{suggestion}"')
    return "".join(parts)


def _old_statements(statements: Sequence[str], each: int) -> str:
    """The old drafts under one label, each cut to `each` characters."""
    statements = [s for s in statements if s.strip()]
    if not statements:
        return ""
    quoted = " ".join(f'"{_clip(s, each)}"' for s in statements)
    return f" {_OLD_LABEL} {quoted}"


def _assemble(head: str, reason_th: str, suggestion_th: str, statements: Sequence[str]) -> str:
    """Head, the reviewer's words, then the old drafts, within `MAX_NOTE_CHARS`.

    The reviewer's reason and suggestion keep their own 280-character cap and the
    old drafts share what is left; when that is too little, the reviewer's words
    give way before the old drafts drop below `_MIN_STATEMENT_CHARS` each."""
    n = len([s for s in statements if s.strip()])
    overhead = 12 * n + len(_OLD_LABEL) + 8 if n else 0
    stmt_floor = n * _MIN_STATEMENT_CHARS + overhead
    cap = _MAX_REASON_CHARS
    review = _quoted_review(reason_th, suggestion_th, cap)
    while len(head) + len(review) + stmt_floor > MAX_NOTE_CHARS and cap > 20:
        cap -= 20
        review = _quoted_review(reason_th, suggestion_th, cap)
    each = (MAX_NOTE_CHARS - len(head) - len(review) - overhead) // n if n else 0
    return head + review + _old_statements(statements, max(each, 1) if n else 0)


def build_redundancy_redraft_note_th(
    reason_th: str, suggestion_th: str, old_statements_th: Sequence[str]
) -> str:
    """The note for one PLO drafted from the union of the Needs of PLOs the review
    found to say the same thing. Goes through the `note_th` channel of
    `draft_from_needs`: guidance on wording, not a rule over the PLO prompt."""
    head = (
        "ผู้ตรวจชุด PLO เห็นว่า PLO เหล่านี้ซ้ำซ้อนกัน "
        "กรุณาเขียนผลลัพธ์การเรียนรู้ข้อเดียวที่ครอบคลุมทุก Need และไม่ซ้ำกับข้ออื่น"
    )
    return _assemble(head, reason_th, suggestion_th, old_statements_th)


def build_alignment_redraft_note_th(
    reason_th: str, suggestion_th: str, old_statement_th: str
) -> str:
    """The note for a PLO that does not answer what its own Needs ask for."""
    head = "ผู้ตรวจชุด PLO เห็นว่า PLO ข้อนี้ยังไม่ตอบสิ่งที่ Need ของมันต้องการ กรุณาเขียนใหม่ให้ตรงกับ Need"
    return _assemble(head, reason_th, suggestion_th, [old_statement_th])


def build_bloom_redraft_note_th(
    suggested: BloomLevel | None,
    reason_th: str,
    *,
    suggested_verb_th: str | None = None,
    suggestion_th: str = "",
    old_statement_th: str = "",
) -> str:
    """The note sent with a Bloom redraft: write the outcome at `suggested` and/or
    with `suggested_verb_th`. Either may be absent (a verb-only finding names no
    level change). Goes through the `note_th` channel of `draft_from_needs`.
    """
    # The level is named in English, not by a Thai label: the Thai names of the two
    # lowest levels are forbidden PLO words, and a note that used one would prime
    # the draft toward the very failure the SMART gate rejects.
    head = "ผู้ตรวจชุด PLO เห็นว่า PLO ข้อนี้ควรปรับให้เหมาะกับงานที่ทำ"
    if suggested is not None:
        head = (
            f"ผู้ตรวจชุด PLO เห็นว่า PLO ข้อนี้ควรอยู่ระดับ Bloom: {suggested.value.capitalize()} "
            "กรุณาเขียนผลลัพธ์การเรียนรู้ใหม่ในระดับนี้ โดยใช้กริยาที่วัดผลได้ในระดับนั้นเพียงตัวเดียว"
        )
        verbs = [
            v for v in verbs_for_level(suggested) if not any(w in v for w in FORBIDDEN_WORDS_TH)
        ][:_MAX_EXAMPLE_VERBS]
        if verbs:
            head += f" ตัวอย่างกริยา: {', '.join(verbs)}"
    verb = mask_forbidden_words((suggested_verb_th or "").strip())
    if verb:
        head += f" ผู้ตรวจเสนอกริยา: {verb[:40]}"
    return _assemble(head, reason_th, suggestion_th, [old_statement_th])


def build_unused_redraft_note_th(reason_th: str) -> str:
    """The note for a PLO drafted from one Need that no PLO cites yet."""
    head = "ผู้ตรวจชุด PLO เห็นว่า Need นี้ยังไม่มี PLO รองรับ กรุณาเขียนผลลัพธ์การเรียนรู้จาก Need นี้"
    return _assemble(head, reason_th, "", [])


def build_ksec_gap_note_th(category: str) -> str:
    """The note for a PLO drafted to fill a K/S/E/C category the set has none of."""
    return (
        f"ชุด PLO ยังไม่มีผลลัพธ์ด้านหมวด {category} "
        f"กรุณาเขียนผลลัพธ์การเรียนรู้จาก Need นี้ให้สะท้อนด้านหมวด {category}"
    )
