"""Shared SMART vocabulary: the forbidden-word rule and its Thai word boundaries.

A leaf module on purpose. Both `models.py` (the Pydantic validator) and
`stages/smart_rules.py` (the hard checks) need the forbidden-word rule, and the
dependency already runs `smart_rules -> models`, so putting the scan in either
one makes the other's import circular. Nothing here imports from the package.
"""

from __future__ import annotations

# Words forbidden in PLO statements (Thai). Cause SMART measurable to fail.
FORBIDDEN_WORDS_TH = {"รู้", "จำ", "เข้าใจ", "ซาบซึ้ง", "ตระหนัก", "ศรัทธา", "รัก"}

# Compounds that contain a forbidden word but are not one. Thai has no word
# boundaries, so a plain substring scan flags every one of these — and each is a
# legitimate PLO verb or object that used to escalate a sound outcome after
# burning all three repair rounds against a hint telling it to remove a word it
# never used. "จำแนก" (classify) is an Understand-level Bloom verb; "รักษา"
# belongs in every nursing PLO; "ความรู้" as the object of a verb is a soft
# S_object finding, never a hard Measurable failure.
#
# An explicit list, not a heuristic: every entry is a documented false positive
# rather than a guess, and it is testable. A real tokenizer (pythainlp — not a
# dependency, and its own segmenter is fallible on curriculum vocabulary) is the
# long-term answer, and `forbidden_words_in` is the one place to swap it in.
ALLOWED_COMPOUNDS_TH = frozenset(
    {
        # รัก
        "รักษา",
        "การรักษา",
        "รักษาการ",
        "อนุรักษ์",
        # จำ
        "จำแนก",
        "จำลอง",
        "จำกัด",
        "จำเป็น",
        "จำนวน",
        "จำหน่าย",
        "จำเพาะ",
        "ประจำ",
        # รู้
        "ความรู้",
        "เรียนรู้",
        "รู้จัก",
        "ผู้รู้",
        "รู้เท่าทัน",
    }
)


def forbidden_words_in(statement_th: str) -> list[str]:
    """Forbidden unmeasurable words that actually appear as words, in order.

    One definition, two callers: `smart_rules.hard_failures` and
    `PLO.check_no_forbidden_words`. They implemented the same substring scan
    independently, which is how they could disagree — and the whole point of the
    hard checks being pure code is that there is exactly one of each.

    Allowed compounds are masked longest-first so "การรักษา" is consumed before
    "รักษา" could match inside it. Masking with a space rather than deleting
    keeps offsets from merging two neighbours into a new false match.
    """
    masked = statement_th
    for allowed in sorted(ALLOWED_COMPOUNDS_TH, key=len, reverse=True):
        masked = masked.replace(allowed, " " * len(allowed))

    found = [(masked.index(word), word) for word in FORBIDDEN_WORDS_TH if word in masked]
    return [word for _, word in sorted(found)]
