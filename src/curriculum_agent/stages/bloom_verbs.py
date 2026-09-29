"""Thai Bloom action verbs, for the SMART validator to consult.

`references/obe-principles.md` carries the canonical verb table, but in English
("define, identify, state…"), and nothing in this repository held the Thai
vocabulary — only `models.BLOOM_ORDER`, which ranks the levels. So the rubric's
"exactly one recognized Bloom verb" rule and the "two verbs only if adjacent"
rule were prompt text with no code behind them.

**Advisory for the statement; authoritative for the declared verb.** This was
advisory only, held back from `smart_rules.hard_failures` "until the vocabulary
has seen real programs", because a PLO using a sound verb this table forgot
would hard-fail Specific and escalate — a worse outcome than the gap it closes.
The programs arrived, and measuring against them moved the line in one specific
place rather than removing it.

What the nine stored PLOs showed: six declared a *phrase* in `action_verb_th`
("ออกแบบและดำเนินการ", "ออกแบบและดำเนินการตรวจสอบ", "ตีความและอธิบาย"), and the S
hard check — `action_verb_th in statement_th` — passed all six, because synthesis
writes the phrase into the sentence it is checked against. So the rubric's "one
Bloom verb per outcome" rule was broken at the field that declares the verb,
while the check meant to catch it read the sentence.

The feared failure did not appear there, and a different one did. Scanning the
*statement* flags six of the nine, of which four are sound outcomes carrying a
means clause ("โดยใช้เทคโนโลยี"), a purpose clause ("เพื่อสร้างคอนเทนต์") or the
noun "แนวปฏิบัติ" — over-reporting, not a forgotten verb. Scanning the declared
phrase flags three, all three genuinely two levels apart or three verbs long,
and none of the six passes is an over-report. `smart_rules.declares_too_many_verbs`
is therefore the one caller allowed to gate on this table, and it gates only on
verbs the table *recognises*: a phrase that scans to nothing passes, so a gap in
this vocabulary still cannot escalate an outcome. Stored OPT4 declares
"ประพฤติตน", which is not here, and passes for exactly that reason.

Everything else stays advisory. `scan_statement_verbs` over a full statement
feeds the validator's `check_hard` and `bloom_lookup` observations so the agent
can *name* a two-verb sentence or a level mismatch in a repair instruction, and
that is all it may do — the measurement above is what says why. This table is
still a judgement call and still wants a Thai curriculum specialist's review;
adding a verb to it now widens what `S_multi_verb` can reject, so an entry costs
more than it did.

Lives beside `smart_rules.py` rather than in `models.py`: it is domain policy
that will grow to hundreds of strings, and `models.py` is schemas.
"""

from __future__ import annotations

from curriculum_agent.models import BLOOM_ORDER, BloomLevel

# Thai renderings of the rubric's per-level verb table. A verb may appear at
# more than one level on purpose — see `levels_for_verb`.
#
# Note what is absent: none of FORBIDDEN_WORDS_TH appears here, not even at the
# two lowest levels where รู้/จำ/เข้าใจ would be the natural translations. The
# Remember and Understand entries are observable alternatives ("ระบุ", "อธิบาย")
# precisely so that a model reaching for this table cannot pick a word the M
# hard check will reject.
BLOOM_VERBS_TH: dict[BloomLevel, frozenset[str]] = {
    BloomLevel.REMEMBER: frozenset(
        {
            "นิยาม",
            "ระบุ",
            "บอก",
            "ระบุชื่อ",
            "เรียกชื่อ",
            "แจกแจง",
            "จับคู่",
            "ระบุตำแหน่ง",
            "ระลึก",
        }
    ),
    BloomLevel.UNDERSTAND: frozenset(
        {
            "บรรยาย",
            "อธิบาย",
            "สรุป",
            "เปรียบเทียบ",
            "จำแนก",
            "ยกตัวอย่าง",
            "แปลความ",
            "ตีความ",
            "เรียบเรียงใหม่",
        }
    ),
    BloomLevel.APPLY: frozenset(
        {
            "ประยุกต์",
            "ประยุกต์ใช้",
            "แก้ปัญหา",
            "คำนวณ",
            "ดัดแปลง",
            "ดำเนินการ",
            "ควบคุม",
            "ใช้",
            "จัดเตรียม",
            "สาธิต",
            "ปฏิบัติ",
            "พยากรณ์",
            "จัดระบบ",
        }
    ),
    BloomLevel.ANALYZE: frozenset(
        {
            "วิเคราะห์",
            "แยกส่วน",
            "เปรียบเทียบ",
            "เทียบความต่าง",
            "แยกแยะ",
            "จำแนกความแตกต่าง",
            "ตรวจสอบ",
            "ทดลอง",
            "ทดสอบ",
            "วินิจฉัย",
        }
    ),
    BloomLevel.EVALUATE: frozenset(
        {
            "ประเมิน",
            "ประเมินค่า",
            "จัดลำดับ",
            "ตรวจสอบความถูกต้อง",
            "โต้แย้ง",
            "กำกับติดตาม",
            "ตัดสิน",
            "วิพากษ์",
            "สรุปผล",
            "ให้เหตุผลสนับสนุน",
        }
    ),
    BloomLevel.CREATE: frozenset(
        {
            "สร้าง",
            "สร้างสรรค์",
            "วางแผน",
            "ประพันธ์",
            "พัฒนา",
            "ประดิษฐ์",
            "ประกอบสร้าง",
            "ผลิต",
            "ออกแบบ",
            "คิดค้น",
            "จัดโครงสร้างใหม่",
            "บูรณาการ",
        }
    ),
}

# A level with no verbs would make `verbs_for_level` return an empty suggestion
# list and `levels_for_verb` silently unable to ever name it. Turn that into an
# import-time crash, the way `prompts/summarize_need.py` guards its label maps.
_uncovered_levels = {level.value for level in BloomLevel} - {
    level.value for level in BLOOM_VERBS_TH
}
if _uncovered_levels:
    raise AssertionError(f"BLOOM_VERBS_TH is missing verbs for: {sorted(_uncovered_levels)}")

_thin_levels = {level.value for level, verbs in BLOOM_VERBS_TH.items() if len(verbs) < 5}
if _thin_levels:
    raise AssertionError(f"BLOOM_VERBS_TH has too few verbs for: {sorted(_thin_levels)}")

# Longest first, so a compound verb is matched as itself rather than as the
# shorter verb it contains — see `scan_statement_verbs`.
_ALL_VERBS_LONGEST_FIRST: tuple[str, ...] = tuple(
    sorted({verb for verbs in BLOOM_VERBS_TH.values() for verb in verbs}, key=len, reverse=True)
)

# Common Thai words that contain a Bloom verb without being one. Thai has no
# word boundaries, so "โครงสร้างข้อมูล" reads as the Create verb "สร้าง" — and
# "โครงสร้าง" appears in engineering and IT outcomes constantly, so the
# one-verb rule would fire on almost every one of them. Same discipline as
# `smart_vocabulary`'s allowed compounds: an explicit list of documented false
# positives, not a heuristic.
#
# The other way out is to leave the short verb out of the table entirely, and
# that was right for "ทวน" (repeat): three characters, sitting inside "ทบทวน"
# (to review, a real verb at a higher level), and not a word anyone writes in a
# Thai PLO. Masking "ทบทวน" here instead would have hidden a legitimate verb.
#
# A verb is only discarded when its match sits *entirely inside* one of these,
# so the Create verb "จัดโครงสร้างใหม่" survives the "โครงสร้าง" in its middle.
_NON_VERB_CONTEXTS_TH: tuple[str, ...] = tuple(
    sorted(
        {
            "โครงสร้าง",
            "สิ่งก่อสร้าง",
            "การก่อสร้าง",
            "ผู้สร้าง",
            "ผู้ใช้",
            "ผลิตภัณฑ์",
            "ผลิตผล",
        },
        key=len,
        reverse=True,
    )
)


def _non_verb_spans(statement_th: str) -> list[tuple[int, int]]:
    """Half-open spans of `_NON_VERB_CONTEXTS_TH` occurrences, longest first."""
    masked = statement_th
    spans: list[tuple[int, int]] = []
    for context in _NON_VERB_CONTEXTS_TH:
        start = masked.find(context)
        while start != -1:
            spans.append((start, start + len(context)))
            masked = masked[:start] + " " * len(context) + masked[start + len(context) :]
            start = masked.find(context)
    return spans


def levels_for_verb(verb_th: str) -> list[BloomLevel]:
    """Every level this verb appears at, in `BLOOM_ORDER` order.

    A list, not a single level. The rubric is explicit that the same verb sits
    at different levels depending on cognitive demand — "design a flowchart
    from given specs" is Apply, "design a new architecture for an unsolved
    problem" is Create — so a table mapping each verb to one level would assert
    something the domain says is false, and the validator would then argue with
    the synthesis model about a level neither can settle from the verb alone.

    Empty when the verb is not in the table. That is a legitimate answer, and
    often the most useful one: it says "no recognized Bloom verb here".
    """
    return [level for level in BLOOM_ORDER if verb_th in BLOOM_VERBS_TH[level]]


def verbs_for_level(level: BloomLevel) -> list[str]:
    """The level's verbs, sorted, so a suggestion list is deterministic."""
    return sorted(BLOOM_VERBS_TH[level])


def scan_statement_verbs(statement_th: str) -> list[str]:
    """Recognized Bloom verbs appearing in the statement, longest match first.

    Longest-first with masking, so "จำแนกความแตกต่าง" is reported as itself and
    does not also report the "จำแนก" inside it — the rubric's one-verb rule
    would otherwise fail on a single correct verb. A match falling entirely
    inside a `_NON_VERB_CONTEXTS_TH` word is discarded, which is what stops
    "โครงสร้างข้อมูล" reporting the Create verb "สร้าง".

    Thai has no word boundaries, so this remains a substring scan and can still
    over-report a verb inside a word nobody listed. It is advisory input to a
    judgement, never a gate, which is what makes that acceptable here.

    Ordered by position in the statement, not by length, so the first verb
    reported is the first one written.
    """
    blocked = _non_verb_spans(statement_th)
    masked = statement_th
    found: list[tuple[int, str]] = []
    for verb in _ALL_VERBS_LONGEST_FIRST:
        start = masked.find(verb)
        while start != -1:
            end = start + len(verb)
            inside_a_non_verb_word = any(lo <= start and end <= hi for lo, hi in blocked)
            if not inside_a_non_verb_word:
                found.append((start, verb))
            masked = masked[:start] + " " * len(verb) + masked[end:]
            start = masked.find(verb)
    return [verb for _, verb in sorted(found)]


def are_adjacent(a: BloomLevel, b: BloomLevel) -> bool:
    """Whether two levels are the same or one step apart on `BLOOM_ORDER`.

    Built on the existing `BLOOM_ORDER` rather than a second ordering of its
    own: the project's "two verbs allowed only if at adjacent levels" rule must
    not acquire a rival definition of what adjacent means.
    """
    return abs(BLOOM_ORDER.index(a) - BLOOM_ORDER.index(b)) <= 1
