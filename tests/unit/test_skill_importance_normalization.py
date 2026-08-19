from __future__ import annotations

from unittest.mock import AsyncMock, patch

from curriculum_agent.stages import skill_extraction as se


def _evidence(evidence_id: str, text: str, stakeholder_type: str, classification: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "program_id": "prog-1",
        "stakeholder_type": stakeholder_type,
        "source_name": f"src-{evidence_id}",
        "raw_text_th": text,
        "collected_at": "2026-01-01T00:00:00",
        "classification": classification,
        "metadata": {},
    }


def _skill_item(name: str, span: str) -> dict:
    return {
        "skill_name_th": name,
        "skill_name_en": "Python",
        "ksec_category": "S",
        "bloom_level": "apply",
        "evidence_span_th": span,
        "confidence": 0.9,
    }


async def test_two_spellings_of_one_skill_get_the_same_importance_score():
    """_compute_skill_importance must group by the same normalised name that
    need_grouping.dedupe_with_bloom_max later collapses duplicates by.

    Two evidence items mention the same skill under different spellings
    ("Python" vs " python" — case and leading-whitespace differences that
    normalize_need_name collapses but a raw skill_name_th comparison would
    not). If importance were grouped by the raw name, each spelling would
    only see its own evidence item's single stakeholder, giving each a
    *different* score — even though need_grouping merges them into one Need
    with combined evidence. This test asserts the scores are identical AND
    reflect the merged (both-stakeholder) coverage, not just "both non-zero".
    """
    span1 = "ต้องการผู้เชี่ยวชาญด้าน Python สำหรับพัฒนาระบบวิเคราะห์ข้อมูล"
    span2 = "หลักสูตรควรปูพื้นฐาน python ให้นักศึกษาก่อนขึ้นปีสาม"
    evidence_dicts = [
        _evidence("E1", span1, "employer", "general"),
        _evidence("E2", span2, "faculty", "general"),
    ]

    async def fake_extract_skills(response_model, messages, **kw):  # noqa: ANN001, ANN003
        text = messages[-1]["content"]
        if span1 in text:
            return response_model(skills=[_skill_item("Python", span1)])
        assert span2 in text
        # _SkillItem strips (but does not lowercase) skill_name_th before
        # validation, so the stored name is "python" — differing from "Python"
        # by case only, which is exactly what normalize_need_name must collapse.
        return response_model(skills=[_skill_item(" python", span2)])

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()

    with (
        patch.object(se, "LLMCacheRepository", return_value=cache),
        patch.object(se, "complete_light", fake_extract_skills),
        # run() clears the program's previous skill rows before inserting the new
        # set, so stubbing only bulk_insert leaves the delete hitting a real DB.
        patch.object(se.SkillRepository, "delete_by_program", AsyncMock()),
        patch.object(se.SkillRepository, "bulk_insert", AsyncMock()),
    ):
        result = await se.run(
            {
                "program_id": "prog-1",
                "classified_evidence": evidence_dicts,
            }
        )

    skills = result["extracted_skills"]
    assert len(skills) == 2
    by_name = {s["skill_name_th"]: s["importance_score"] for s in skills}
    assert set(by_name) == {"Python", "python"}
    assert by_name["Python"] == by_name["python"]

    # And the shared score must reflect BOTH stakeholders (employer + faculty),
    # not just whichever spelling's evidence happened to be grouped alone —
    # proof the two really merged into one group rather than coincidentally
    # landing on equal-but-independent scores.
    from curriculum_agent.stages.demand import compute_demand_score

    stakeholder_type_by_evidence = {"E1": "employer", "E2": "faculty"}
    expected_score = compute_demand_score(["E1", "E2"], stakeholder_type_by_evidence)
    assert by_name["Python"] == expected_score
    assert expected_score > 0

    # classify_skills's contract states every raw skill whose name normalises the
    # same receives the same class. Both evidence items here are "general" and
    # there are 2 distinct evidence ids naming the skill, so both spellings must
    # come back "need" — not just the one matching classify_skills's internal
    # first-spelling-seen key verbatim (a bug caught here: a run()-level lookup
    # keyed on the raw stripped name rather than the normalised name would find
    # the "Python" entry and miss "python", silently defaulting it to
    # "unclassified").
    classification_by_name = {s["skill_name_th"]: s["classification"] for s in skills}
    assert classification_by_name["Python"] == classification_by_name["python"] == "need"
