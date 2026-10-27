"""The answer shape of a Need-sentence call, in a leaf module.

`need_combination` writes a Need's sentence through this model and `need_merge`
writes a merged Need's sentence through the same one, so both import it from
here. It used to live in `need_combination`, which made `need_merge` import it
from there while `need_combination` imported `need_merge` lazily to avoid the
cycle. Nothing here imports either stage.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from curriculum_agent.prompts.summarize_need import (
    MAX_RATIONALE_CHARS,
    MIN_RATIONALE_CHARS,
    MIN_STATEMENT_CHARS,
)
from curriculum_agent.stages.need_grouping import (
    find_code_identifier,
    find_vague_phrase,
    looks_like_a_skill_list,
)

# Output cap for a Need-sentence call. The provider default (512 on opentyphoon)
# truncated the JSON: 30 listed members with a note each, plus the statement and
# rationale, need ~1.6k tokens. Measured finish_reason='length' at 512 on 2026-10-27.
STATEMENT_MAX_TOKENS = 2048


# The three reasons a shown member can be left out of the sentence. Checked
# against the raw answer in the never-fail validator below — an entry naming
# anything else is dropped rather than raised, the same discipline as
# supporting_indices.
NOT_COVERED_REASONS = {"low_freq", "not_graduate", "off_task"}


class NotCovered(BaseModel):
    """One shown member the sentence does not speak for, and why.

    A measurement, like supporting_indices — it is read by `_log_coverage` and
    never stored, so nothing here can turn a well-written sentence into a
    `[ต้องทบทวน]` fallback.
    """

    index: int
    reason_code: Literal["low_freq", "not_graduate", "off_task"]
    note_th: str = ""


class DesignerInputUse(BaseModel):
    """Whether the optional designer note changed a word choice, and how.

    Logged once per run (`need_combination.run`), not stored — there is no
    threshold yet, only a first distribution to look at, the same reasoning
    ticket 18 gives for supporting_indices.
    """

    used: bool
    detail_th: str = ""


class NeedStatement(BaseModel):
    statement_th: str = Field(min_length=1)
    statement_en: str | None = None
    rationale_th: str = Field(min_length=1)
    # Positions into the listed names that the sentence says it speaks for.
    # Deliberately unvalidated: it is a measurement, and a validator that raised
    # here would send Instructor round again and, three misses later, turn a
    # well-written sentence into a `[ต้องทบทวน]` fallback. `supporting_coverage`
    # discards what it cannot use instead. None — the model sent no list — is kept
    # apart from [] so a dropped field cannot read as "covers nothing".
    supporting_indices: list[int] | None = None
    # Shown members the sentence does not speak for, and why. Same measurement
    # discipline as supporting_indices: never-fail, logged, never stored.
    not_covered_indices: list[NotCovered] | None = None
    # Whether the designer's optional note changed a word choice. Logged once
    # per run, not stored — see the class docstring.
    designer_input_used: DesignerInputUse | None = None

    @field_validator("supporting_indices", mode="before")
    @classmethod
    def _never_fail_on_the_measurement(cls, value: Any) -> list[int] | None:
        """Reduce whatever arrived to its integers, or to None if it is not a list.

        Leaving the field unvalidated is not enough: pydantic still type-checks
        `list[int]`, so an answer of "0,1,2" would fail the call over a number
        the stage only logs.
        """
        if not isinstance(value, list):
            return None
        kept: list[int] = []
        for item in value:
            if isinstance(item, bool):
                continue
            if isinstance(item, int) or (isinstance(item, float) and item.is_integer()):
                kept.append(int(item))
            elif isinstance(item, str) and item.strip().isdigit():
                kept.append(int(item.strip()))
        return list(dict.fromkeys(kept))

    @field_validator("not_covered_indices", mode="before")
    @classmethod
    def _never_fail_on_not_covered(cls, value: Any) -> list[dict[str, Any]] | None:
        """Drop a malformed entry instead of failing the whole call.

        Not a list at all -> None. Within a list, an entry with a non-int index
        or an unrecognised reason_code is dropped rather than raised — the same
        reasoning as supporting_indices: this is read by a log line, and three
        retries over a field nobody stores would turn a good sentence into a
        `[ต้องทบทวน]` fallback.
        """
        if isinstance(value, NotCovered):
            return [value.model_dump()]
        if not isinstance(value, list):
            return None
        kept: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, NotCovered):
                kept.append(item.model_dump())
                continue
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if isinstance(index, bool):
                continue
            if isinstance(index, float) and index.is_integer():
                index = int(index)
            if not isinstance(index, int):
                continue
            reason_code = item.get("reason_code")
            if reason_code not in NOT_COVERED_REASONS:
                continue
            note_th = item.get("note_th", "")
            if not isinstance(note_th, str):
                note_th = ""
            kept.append({"index": index, "reason_code": reason_code, "note_th": note_th})
        return kept

    @field_validator("designer_input_used", mode="before")
    @classmethod
    def _never_fail_on_designer_input_used(cls, value: Any) -> dict[str, Any] | None:
        """A malformed answer loses the whole field rather than failing the call.

        Unlike not_covered_indices this is a single object, not a list, so there
        is no per-entry salvage to do: either it names a real bool `used` or the
        field becomes None, the same way a non-list supporting_indices does.
        """
        if isinstance(value, DesignerInputUse):
            return value.model_dump()
        if not isinstance(value, dict):
            return None
        used = value.get("used")
        if not isinstance(used, bool):
            return None
        detail_th = value.get("detail_th", "")
        if not isinstance(detail_th, str):
            detail_th = ""
        return {"used": used, "detail_th": detail_th}

    @field_validator("rationale_th")
    @classmethod
    def _reject_an_empty_reason(cls, rationale: str) -> str:
        """A reason that says nothing is worse than no reason at all.

        It renders beside the sentence it explains and will be read as the
        justification for that Need, so "เป็นทักษะที่เกี่ยวข้องกัน" is not a weak
        answer — it is a claim with nothing behind it in the place a reader looks
        for one. The vagueness scan is the one `statement_th` already uses, since
        the failure is the same failure and two vocabularies for it is how they
        come to disagree.

        The upper bound is not cosmetic either: this field rides on every Need
        row and inside a card, and it is the one place in the response where a
        model can spend arbitrary tokens without any rule pushing back.
        """
        trimmed = rationale.strip()
        if len(trimmed) < MIN_RATIONALE_CHARS:
            raise ValueError(
                f"rationale_th สั้นเกินไป ({len(trimmed)} ตัวอักษร) ต้องยาวอย่างน้อย "
                f"{MIN_RATIONALE_CHARS} ตัวอักษร และบอกว่าทักษะกลุ่มนี้ใช้ทำหน้าที่หรืองานร่วมอะไร"
            )
        if len(trimmed) > MAX_RATIONALE_CHARS:
            raise ValueError(
                f"rationale_th ยาวเกินไป ({len(trimmed)} ตัวอักษร) ต้องไม่เกิน "
                f"{MAX_RATIONALE_CHARS} ตัวอักษร ให้สรุปเหตุผลให้สั้นลง"
            )
        vague = find_vague_phrase(trimmed)
        if vague:
            raise ValueError(
                f"rationale_th กว้างเกินไปจนไม่ได้บอกเหตุผล: '{vague}' "
                "ให้ระบุหน้าที่หรืองานร่วมที่ทักษะในกลุ่มนี้ใช้ทำแทน"
            )
        return rationale

    @field_validator("statement_th")
    @classmethod
    def _reject_code_tokens(cls, statement: str) -> str:
        """Bounce a sentence carrying a code identifier back to the model.

        A small model tokenising Thai byte-by-byte occasionally emits a token
        from its code training instead of the Thai it was asked for — one stored
        Need read "...เป็นผู้ประกอบการ หน.getDefault รับฟังผู้บริหาร...", built
        from two clean skill names. Raising here is what makes Instructor retry
        with the failure quoted back, the same shape as the SMART retry loop.
        """
        found = find_code_identifier(statement)
        if found:
            raise ValueError(
                f"statement_th ต้องเป็นภาษาไทยล้วน พบข้อความที่เป็นโค้ด: '{found}' "
                "ห้ามใส่ชื่อฟังก์ชัน ชื่อตัวแปร หรือโค้ดในประโยค"
            )
        return statement

    @field_validator("statement_th")
    @classmethod
    def _require_plo_ready(cls, statement: str) -> str:
        """Reject the two shapes a Need cannot become a PLO from.

        plo_synthesis drafts exactly one PLO per Need and is handed nothing but
        this sentence. A placeholder ("ทักษะที่จำเป็นต่อการทำงาน") or a joined
        skill list therefore does not merely weaken the PLO — it makes the
        synthesis model invent the capability, with no evidence behind what it
        invents. Raising here sends the group back through Instructor with the
        reason quoted, the same shape as the code-token guard above.
        """
        trimmed = statement.strip()
        if len(trimmed) < MIN_STATEMENT_CHARS:
            raise ValueError(
                f"statement_th สั้นเกินไป ({len(trimmed)} ตัวอักษร) ต้องยาวอย่างน้อย "
                f"{MIN_STATEMENT_CHARS} ตัวอักษร และระบุความสามารถ วัตถุของงาน "
                "และบริบทการทำงานให้ครบ"
            )
        if looks_like_a_skill_list(trimmed):
            raise ValueError(
                "statement_th เป็นการนำชื่อทักษะมาต่อกัน (ด้วยจุลภาค หรือด้วยการเว้นวรรคแล้วปิดท้ายด้วย 'และ') "
                "ให้เขียนเป็นประโยคความต้องการหนึ่งประโยคที่ระบุความสามารถเดียว"
            )
        vague = find_vague_phrase(trimmed)
        if vague:
            raise ValueError(
                f"statement_th มีคำกว้างที่ไม่บอกเนื้อหา: '{vague}' ให้ระบุความสามารถและวัตถุของงานที่เจาะจงแทน"
            )
        return statement
