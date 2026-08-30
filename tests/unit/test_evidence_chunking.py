"""Long evidence is read past its first paragraph, and says so when it isn't.

The stage used to hand the model `raw_text_th[:1200]` and log nothing about the
rest. A twenty-page สภาวิชาชีพ standard — the heaviest source a corpus has —
was read down to its opening paragraph and could yield fewer skills than a
short job posting, with nothing on screen or in the log to say why.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from curriculum_agent.stages import skill_extraction as se
from curriculum_agent.stages.skill_extraction import (
    _CHUNK_CHARS,
    _CHUNK_OVERLAP,
    _MAX_CHUNKS,
    chunk_evidence_text,
)

# --- the pure chunker -----------------------------------------------------


def test_text_that_fits_is_one_window():
    chunks, unread = chunk_evidence_text("x" * _CHUNK_CHARS)
    assert chunks == ["x" * _CHUNK_CHARS]
    assert unread == 0


def test_blank_evidence_yields_nothing_to_call_the_model_with():
    assert chunk_evidence_text("   \n  ") == ([], 0)


def test_windows_cover_the_whole_text():
    text = "x" * (_CHUNK_CHARS * 3)
    chunks, unread = chunk_evidence_text(text)
    assert unread == 0
    # Reassembling by advance (window length minus the overlap it shares with
    # the next) must account for every character.
    assert len(chunks) > 1
    covered = len(chunks[0]) + sum(len(c) - _CHUNK_OVERLAP for c in chunks[1:])
    assert covered == len(text)


def test_windows_overlap_so_a_phrase_on_a_boundary_is_still_quotable():
    text = "x" * (_CHUNK_CHARS * 2)
    chunks, _ = chunk_evidence_text(text)
    assert len(chunks) >= 2
    assert chunks[0][-_CHUNK_OVERLAP:] == chunks[1][:_CHUNK_OVERLAP]


def test_a_window_is_cut_at_a_word_boundary():
    """evidence_span_th has to be copied verbatim, so a window ending mid-word
    is a span the model cannot quote."""
    text = " ".join(["คำ"] * 2000)
    chunks, _ = chunk_evidence_text(text)
    assert len(chunks) > 1
    assert not chunks[0].endswith(" ")
    assert text.startswith(chunks[0])
    # The cut landed on a boundary, not inside a token.
    assert text[len(chunks[0])] == " "


def test_a_tail_shorter_than_the_overlap_is_absorbed_not_given_its_own_call():
    """A window that is almost entirely re-read text still costs a provider
    call, so the previous window takes the remainder instead."""
    text = "x" * (_CHUNK_CHARS + _CHUNK_OVERLAP - 1)
    chunks, unread = chunk_evidence_text(text)
    assert len(chunks) == 1
    assert unread == 0


def test_a_document_past_the_window_cap_reports_what_it_left():
    """No silent cap: the caller logs this against the evidence id."""
    text = "x" * (_CHUNK_CHARS * (_MAX_CHUNKS + 5))
    chunks, unread = chunk_evidence_text(text)
    assert len(chunks) == _MAX_CHUNKS
    assert unread > 0
    read = len(chunks[0]) + sum(len(c) - _CHUNK_OVERLAP for c in chunks[1:])
    assert read + unread == len(text)


# --- the stage ------------------------------------------------------------

_LATE_SPAN = "ต้องการผู้ที่ประเมินความเสี่ยงด้านความปลอดภัยไซเบอร์ขององค์กรได้"
_LATE_SKILL = "ประเมินความเสี่ยงด้านความปลอดภัยไซเบอร์"
# Padding with spaces so the windows cut on boundaries, as real prose does.
_LONG_TEXT = " ".join(["ข้อความประกอบ"] * 200) + " " + _LATE_SPAN + " " + " ".join(["ท้ายเรื่อง"] * 20)


def _evidence() -> dict:
    return {
        "evidence_id": "E1",
        "program_id": "prog-1",
        "stakeholder_type": "employer",
        "source_name": "long-standard",
        "raw_text_th": _LONG_TEXT,
        "collected_at": "2026-01-01T00:00:00",
        "classification": "general",
        "metadata": {},
    }


async def test_a_skill_stated_past_the_first_window_is_still_extracted():
    """The regression: _LATE_SPAN sits well beyond character 1200, so under the
    old single-slice read the model never saw the sentence it comes from."""
    assert _LONG_TEXT.index(_LATE_SPAN) > _CHUNK_CHARS

    calls: list[str] = []

    async def fake_extract(response_model, messages, **kw):  # noqa: ANN001, ANN003
        window = messages[-1]["content"]
        calls.append(window)
        if _LATE_SPAN not in window:
            return response_model(skills=[])
        return response_model(
            skills=[
                {
                    "skill_name_th": _LATE_SKILL,
                    "skill_name_en": "Cybersecurity Risk Assessment",
                    "ksec_category": "S",
                    "bloom_level": "evaluate",
                    "evidence_span_th": _LATE_SPAN,
                    "confidence": 0.9,
                }
            ]
        )

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    with (
        patch.object(se, "LLMCacheRepository", return_value=cache),
        patch.object(se, "complete_extraction", fake_extract),
        patch.object(se.SkillRepository, "delete_by_program", AsyncMock()),
        patch.object(se.SkillRepository, "bulk_insert", AsyncMock()),
    ):
        state = await se.run({"program_id": "prog-1", "classified_evidence": [_evidence()]})

    assert len(calls) > 1, "one call means the item was still read as a single slice"
    skills = state["extracted_skills"]
    assert [s["skill_name_th"] for s in skills] == [_LATE_SKILL]


async def test_the_same_skill_seen_in_two_windows_is_one_skill():
    """Windows overlap on purpose, so a phrase near a boundary is extracted
    twice — the per-evidence dedupe is what makes that free."""

    async def fake_extract(response_model, messages, **kw):  # noqa: ANN001, ANN003
        # Answers for every window, so the overlap really does produce repeats.
        return response_model(
            skills=[
                {
                    "skill_name_th": _LATE_SKILL,
                    "skill_name_en": "Cybersecurity Risk Assessment",
                    "ksec_category": "S",
                    "bloom_level": "apply",
                    "evidence_span_th": _LATE_SPAN,
                    "confidence": 0.9,
                }
            ]
        )

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    with (
        patch.object(se, "LLMCacheRepository", return_value=cache),
        patch.object(se, "complete_extraction", fake_extract),
        patch.object(se.SkillRepository, "delete_by_program", AsyncMock()),
        patch.object(se.SkillRepository, "bulk_insert", AsyncMock()),
    ):
        state = await se.run({"program_id": "prog-1", "classified_evidence": [_evidence()]})

    assert len(state["extracted_skills"]) == 1
