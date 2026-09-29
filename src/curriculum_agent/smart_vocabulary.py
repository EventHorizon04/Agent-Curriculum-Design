"""Shared SMART vocabulary: the forbidden-word rule, and the finding codes.

A leaf module on purpose. Both `models.py` (the Pydantic validator) and
`stages/smart_rules.py` (the hard checks) need the forbidden-word rule, and the
dependency already runs `smart_rules -> models`, so putting the scan in either
one makes the other's import circular. The finding codes live here for the same
reason plus one more: the exporter needs the Thai labels, and it should not have
to import a stage to render a spreadsheet cell.

Nothing here imports from the package.
"""

from __future__ import annotations

from enum import StrEnum

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


class SmartFindingCode(StrEnum):
    """Every code a SMART verdict can carry, hard and soft in one vocabulary.

    One enum rather than two, so a finding needs no discriminated union and the
    Thai label map has exactly one key set. The hard three mirror
    `stages.smart_rules.HardCriterion` by value; `HARD_CODES` below and a drift
    test are what keep the two from separating — the same failure class as the
    extraction cache key, which worked until two names for one thing diverged.
    """

    # Hard — pure code decides these, and they are the only things that escalate.
    S_VERB = "S_verb"
    S_MULTI_VERB = "S_multi_verb"
    M_FORBIDDEN = "M_forbidden"
    R_EVIDENCE = "R_evidence"
    # Soft — the validator judges these, and none of them block.
    S_OBJECT = "S_object"
    M_ASSESSABLE = "M_assessable"
    A_LEVEL = "A_level"
    R_NEEDS = "R_needs"
    T_HORIZON = "T_horizon"


HARD_CODES = frozenset(
    {
        SmartFindingCode.S_VERB,
        SmartFindingCode.S_MULTI_VERB,
        SmartFindingCode.M_FORBIDDEN,
        SmartFindingCode.R_EVIDENCE,
    }
)

# One Thai label per code, in Python, so the exporter and the rubric share the
# frontend's wording instead of each inventing it. `soft_flags` used to reach an
# Excel file a designer sends to MHESI as raw English codes, and both frontend
# pages carried their own copy of a map that had been stale for months.
FINDING_LABEL_TH: dict[SmartFindingCode, str] = {
    SmartFindingCode.S_VERB: "กริยาที่ประกาศไว้ไม่ปรากฏในประโยค",
    SmartFindingCode.S_MULTI_VERB: "ประกาศกริยาเกินหนึ่งตัว หรือสองตัวที่ระดับ Bloom ห่างกัน",
    SmartFindingCode.M_FORBIDDEN: "ใช้คำที่วัดผลไม่ได้",
    SmartFindingCode.R_EVIDENCE: "ร่องรอยหลักฐานไม่ครบหรืออ้างถึง Need ที่ไม่มีอยู่",
    SmartFindingCode.S_OBJECT: "กรรมของกริยากว้างเกินไป",
    SmartFindingCode.M_ASSESSABLE: "ไม่ชัดว่าประเมินด้วยเครื่องมือใด",
    SmartFindingCode.A_LEVEL: "ระดับ Bloom ไม่สมเหตุสมผลกับระดับคุณวุฒิ",
    SmartFindingCode.R_NEEDS: "ยังไม่ตอบ Need ที่อ้างถึง",
    SmartFindingCode.T_HORIZON: "กรอบเวลาขัดกับการสำเร็จหลักสูตร",
}

_uncovered_codes = {code.value for code in SmartFindingCode} - {
    code.value for code in FINDING_LABEL_TH
}
if _uncovered_codes:
    raise AssertionError(f"FINDING_LABEL_TH is missing label(s) for: {sorted(_uncovered_codes)}")
