from __future__ import annotations

import pytest

from curriculum_agent.models import BloomLevel
from curriculum_agent.prompts import plo_feedback as notes
from curriculum_agent.smart_vocabulary import forbidden_words_in, mask_forbidden_words

_BAD = "อธิบายและเข้าใจหลักการ ความรู้ทั่วไป"
_LONG = "ก" * 600


def test_mask_forbidden_words_masks_words_but_not_allowed_compounds() -> None:
    masked = mask_forbidden_words(_BAD)
    assert "เข้าใจ" not in masked and "…" in masked
    assert "ความรู้" in masked  # allowed compound survives
    assert forbidden_words_in(masked) == []
    assert mask_forbidden_words("ออกแบบระบบ") == "ออกแบบระบบ"


def test_redundancy_note_has_both_old_statements_and_review() -> None:
    note = notes.build_redundancy_redraft_note_th("ซ้ำกัน", "รวมเป็นข้อเดียว", ["ร่าง ก", "ร่าง ข"])
    assert "ร่างเดิมที่ผู้ตรวจติ:" in note
    assert '"ร่าง ก"' in note and '"ร่าง ข"' in note
    assert "ซ้ำกัน" in note and "รวมเป็นข้อเดียว" in note


def test_alignment_note_renders() -> None:
    note = notes.build_alignment_redraft_note_th("ไม่ตรง Need", "เน้นการปฏิบัติ", "ร่างเดิม")
    assert "ร่างเดิมที่ผู้ตรวจติ:" in note and '"ร่างเดิม"' in note
    assert "ไม่ตรง Need" in note and "เน้นการปฏิบัติ" in note


def test_bloom_note_level_verb_and_old_statement() -> None:
    note = notes.build_bloom_redraft_note_th(
        BloomLevel.APPLY,
        "ต่ำไป",
        suggested_verb_th="ประยุกต์",
        suggestion_th="ใช้กริยาปฏิบัติ",
        old_statement_th="ร่างเดิม",
    )
    assert "Apply" in note and "ประยุกต์" in note and "ใช้กริยาปฏิบัติ" in note
    assert '"ร่างเดิม"' in note


def test_bloom_note_verb_only_names_no_level() -> None:
    note = notes.build_bloom_redraft_note_th(None, "", suggested_verb_th="วิเคราะห์")
    assert "วิเคราะห์" in note and "Bloom:" not in note


def test_unused_note_carries_reason() -> None:
    note = notes.build_unused_redraft_note_th("ความต้องการสูง")
    assert "ยังไม่มี PLO" in note and "ความต้องการสูง" in note


def test_ksec_gap_note_names_category() -> None:
    assert "หมวด E" in notes.build_ksec_gap_note_th("E")


def test_notes_never_carry_forbidden_words() -> None:
    built = [
        notes.build_redundancy_redraft_note_th(_BAD, _BAD, [_BAD, _BAD]),
        notes.build_alignment_redraft_note_th(_BAD, _BAD, _BAD),
        notes.build_bloom_redraft_note_th(
            BloomLevel.REMEMBER,
            _BAD,
            suggested_verb_th="เข้าใจ",
            suggestion_th=_BAD,
            old_statement_th=_BAD,
        ),
        notes.build_bloom_redraft_note_th(None, _BAD, suggested_verb_th="เข้าใจ"),
        notes.build_unused_redraft_note_th(_BAD),
        notes.build_ksec_gap_note_th("K"),
    ]
    for note in built:
        assert forbidden_words_in(note) == [], note


@pytest.mark.parametrize("n_old", [1, 2, 5])
def test_notes_stay_within_900_chars(n_old: int) -> None:
    old = [_LONG] * n_old
    assert len(notes.build_redundancy_redraft_note_th(_LONG, _LONG, old)) <= 900
    assert len(notes.build_alignment_redraft_note_th(_LONG, _LONG, _LONG)) <= 900
    bloom = notes.build_bloom_redraft_note_th(
        BloomLevel.CREATE,
        _LONG,
        suggested_verb_th="ก" * 100,
        suggestion_th=_LONG,
        old_statement_th=_LONG,
    )
    assert len(bloom) <= 900
    assert len(notes.build_unused_redraft_note_th(_LONG)) <= 900
