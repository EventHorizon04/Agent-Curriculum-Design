"""The extraction cache must not replay a payload shaped for an older contract.

The cache is keyed on the evidence text and the model. When `evidence_span_th`
was added to the extraction schema, 18 already-cached rows still carried the
pre-change fields, every cache hit replayed one into the new schema, and the
stage died on a ValidationError. These tests pin both halves of the fix: the key
changes when the contract changes, and a surviving incompatible entry is treated
as a miss instead of taking the stage down.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from curriculum_agent.stages import skill_extraction as se

# Shaped exactly like the rows found in the live cache after the schema change:
# skill_type and is_subject_specific present, evidence_span_th absent.
_OLD_CONTRACT_PAYLOAD = json.dumps(
    {
        "skills": [
            {
                "skill_name_th": "การวิเคราะห์ข้อมูลขนาดใหญ่",
                "skill_name_en": "Data Analysis",
                "skill_type": "knowledge",
                "is_subject_specific": False,
                "ksec_category": "K",
                "bloom_level": "analyze",
                "confidence": 0.75,
            }
        ]
    }
)

_EVIDENCE = {
    "evidence_id": "E1",
    "program_id": "cs-test",
    "stakeholder_type": "employer",
    "source_name": "ประกาศรับสมัครงาน",
    "raw_text_th": "ผู้สมัครต้องวิเคราะห์ข้อมูลขนาดใหญ่เพื่อสนับสนุนการตัดสินใจทางธุรกิจได้",
    "classification": "requirement",
}


def test_contract_fingerprint_is_stable_across_calls():
    assert se._extraction_contract_fingerprint() == se._extraction_contract_fingerprint()


def test_contract_fingerprint_changes_when_the_response_schema_changes(
    monkeypatch: pytest.MonkeyPatch,
):
    before = se._extraction_contract_fingerprint()

    class _Widened(se._ExtractedSkillsResponse):
        extra_field: str | None = None

    monkeypatch.setattr(se, "_ExtractedSkillsResponse", _Widened)
    assert se._extraction_contract_fingerprint() != before


def test_contract_fingerprint_changes_when_the_prompt_changes(
    monkeypatch: pytest.MonkeyPatch,
):
    before = se._extraction_contract_fingerprint()

    def _reworded(evidence_text: str, classification: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": "different instructions entirely"},
            {"role": "user", "content": evidence_text},
        ]

    monkeypatch.setattr(se, "build_extract_skills_prompt", _reworded)
    assert se._extraction_contract_fingerprint() != before


async def test_cache_key_actually_incorporates_the_contract(monkeypatch: pytest.MonkeyPatch):
    """The fingerprint must be *used* in the key, not merely computed.

    Testing `_extraction_contract_fingerprint()` on its own says nothing about
    whether `run` mixes it into the lookup key — drop it from the key and those
    tests still pass while stale entries start matching again. This captures the
    key `run` actually asks the cache for, under two different contracts.
    """
    seen: list[str] = []

    async def capture(self, key: str):  # noqa: ANN001, ANN202
        seen.append(key)
        return None

    monkeypatch.setattr(se.LLMCacheRepository, "get", capture)
    monkeypatch.setattr(se.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(se.SkillRepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(se, "complete_extraction", AsyncMock(side_effect=RuntimeError("no LLM")))

    monkeypatch.setattr(se, "_EXTRACTION_CONTRACT", "contract-one")
    await se.run({"program_id": "cs-test", "classified_evidence": [_EVIDENCE]})
    monkeypatch.setattr(se, "_EXTRACTION_CONTRACT", "contract-two")
    await se.run({"program_id": "cs-test", "classified_evidence": [_EVIDENCE]})

    assert len(seen) == 2
    assert seen[0] != seen[1], "cache key ignores the contract fingerprint"


async def test_cache_key_incorporates_program_metadata(monkeypatch: pytest.MonkeyPatch):
    """Two programs in different fields ingesting the same source text must not
    share a cache entry.

    `field_th`/`program_name_th` go into the *user* message per call (Task 8), but
    `_EXTRACTION_CONTRACT` deliberately hashes only the system message — it does
    not vary per program, so it cannot carry this. Without the metadata in the
    key itself, two programs ingesting the same สภาวิชาชีพ standard or the same
    scraped job posting (identical first 1200 chars, identical `classification`)
    would collide, and the second program would be served the first program's
    cached skills — whose `is_field_relevant` was judged against the *other*
    field. Same metadata must still hit the same entry, or every cache-hit path
    the other tests in this module pin would break.
    """
    seen: list[str] = []

    async def capture(self, key: str):  # noqa: ANN001, ANN202
        seen.append(key)
        return None

    monkeypatch.setattr(se.LLMCacheRepository, "get", capture)
    monkeypatch.setattr(se.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(se.SkillRepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(se, "complete_extraction", AsyncMock(side_effect=RuntimeError("no LLM")))

    metadata_cs = {"field": "วิทยาการคอมพิวเตอร์", "name_th": "หลักสูตรวิทยาการคอมพิวเตอร์"}
    metadata_nursing = {"field": "พยาบาลศาสตร์", "name_th": "หลักสูตรพยาบาลศาสตร์"}

    await se.run(
        {"program_id": "cs-test", "classified_evidence": [_EVIDENCE], "metadata": metadata_cs}
    )
    await se.run(
        {
            "program_id": "cs-test",
            "classified_evidence": [_EVIDENCE],
            "metadata": metadata_nursing,
        }
    )
    await se.run(
        {"program_id": "cs-test", "classified_evidence": [_EVIDENCE], "metadata": metadata_cs}
    )

    assert len(seen) == 3
    assert seen[0] != seen[1], "cache key ignores program metadata (field/name)"
    assert seen[0] == seen[2], "identical metadata must still hit the same cache entry"


async def test_old_contract_cache_entry_is_re_extracted_not_raised(
    monkeypatch: pytest.MonkeyPatch,
):
    """A stale entry must degrade to a fresh LLM call, not kill the stage.

    Without the try/except this raises ValidationError out of `run`; without the
    fall-through it silently yields zero skills for the evidence item.
    """
    monkeypatch.setattr(
        se.LLMCacheRepository, "get", AsyncMock(return_value=("stub-model", _OLD_CONTRACT_PAYLOAD))
    )
    monkeypatch.setattr(se.LLMCacheRepository, "set", AsyncMock())
    # This is the only test here that reaches the persistence tail of `run`, so
    # it is the only one that needs the replace-then-insert pair stubbed out.
    monkeypatch.setattr(se.SkillRepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(se.SkillRepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(se.settings, "extraction_model", "stub-model")

    fresh = se._ExtractedSkillsResponse(
        skills=[
            se._SkillItem(
                skill_name_th="วิเคราะห์ข้อมูลขนาดใหญ่",
                skill_name_en="Data Analysis",
                ksec_category="S",
                bloom_level="analyze",
                evidence_span_th="วิเคราะห์ข้อมูลขนาดใหญ่เพื่อสนับสนุนการตัดสินใจ",
                confidence=0.9,
            )
        ]
    )
    llm = AsyncMock(return_value=fresh)
    monkeypatch.setattr(se, "complete_extraction", llm)

    state = await se.run({"program_id": "cs-test", "classified_evidence": [_EVIDENCE]})

    llm.assert_awaited_once()
    assert len(state["extracted_skills"]) == 1
    assert state["extracted_skills"][0]["evidence_span_th"]


def test_the_fingerprint_hashes_a_prompt_that_carries_no_scope_statement():
    """The fingerprint is a promise about the *shape* of a stored payload, and a
    shape does not vary per program.

    A scope statement inside it would give every program its own contract value.
    prune_cache judges a row stale by comparing the contract it was written under
    against the current one, so it would then report `stale-contract` for the
    entire table — the one signal that tool exists to give would stop meaning
    anything on the day this shipped.
    """
    hashed_system_prompt = se.build_extract_skills_prompt("", "")[0]["content"]

    assert "ขอบเขตของหลักสูตรนี้" not in hashed_system_prompt


async def test_two_programs_with_different_scopes_store_the_same_contract(
    monkeypatch: pytest.MonkeyPatch,
):
    """Same claim as above, taken from the other end: what actually lands in the
    `contract` column for two programs whose scope statements differ.

    Asserting on the fingerprint function alone would not catch a `run` that
    computed a per-program contract of its own on the way to the cache write.
    """
    writes: list[str] = []

    async def capture_set(self, key, model, payload, *, kind, contract):  # noqa: ANN001, ANN202
        writes.append(contract)

    monkeypatch.setattr(se.LLMCacheRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(se.LLMCacheRepository, "set", capture_set)
    monkeypatch.setattr(se.SkillRepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(se.SkillRepository, "bulk_insert", AsyncMock())

    fresh = se._ExtractedSkillsResponse(
        skills=[
            se._SkillItem(
                skill_name_th="วิเคราะห์ข้อมูลขนาดใหญ่",
                skill_name_en="Data Analysis",
                ksec_category="S",
                bloom_level="analyze",
                evidence_span_th="วิเคราะห์ข้อมูลขนาดใหญ่เพื่อสนับสนุนการตัดสินใจ",
                confidence=0.9,
            )
        ]
    )
    monkeypatch.setattr(se, "complete_extraction", AsyncMock(return_value=fresh))

    for scope in ("หลักสูตรนี้ครอบคลุมการพัฒนาซอฟต์แวร์และการวิเคราะห์ข้อมูล", "หลักสูตรนี้ครอบคลุมการแปลและการล่าม"):
        await se.run(
            {
                "program_id": "cs-test",
                "classified_evidence": [_EVIDENCE],
                "metadata": {"scope_th": scope},
            }
        )

    assert writes == [se._EXTRACTION_CONTRACT, se._EXTRACTION_CONTRACT]


def test_the_graduate_capability_flag_is_inside_what_the_fingerprint_hashes():
    """The one-off re-extraction this ships with is deliberate, and it happens
    because the new response field moves the fingerprint. If the flag were absent
    from the hashed schema, every pre-existing cache row would still be a hit and
    would replay skills that were never judged on either axis."""
    schema = json.dumps(se._ExtractedSkillsResponse.model_json_schema(), sort_keys=True)

    assert "is_graduate_capability" in schema
