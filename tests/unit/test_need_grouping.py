from __future__ import annotations

from unittest.mock import patch

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory
from curriculum_agent.stages.need_grouping import (
    bucket_by_ksec,
    dedupe_with_bloom_max,
    merge_bloom,
)


def _skill(
    name: str,
    ksec: KSECCategory = KSECCategory.SS,
    bloom: BloomLevel = BloomLevel.APPLY,
    skill_id: str = "S1",
) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=skill_id,
        program_id="cs-test",
        skill_name_th=name,
        ksec_category=ksec,
        bloom_level=bloom,
        evidence_span_th=name,
        source_evidence_id="E1",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


def test_bucket_by_ksec_never_mixes_tags():
    skills = [
        _skill("เขียนโปรแกรม", KSECCategory.SS, skill_id="S1"),
        _skill("ทำงานเป็นทีม", KSECCategory.GS, skill_id="S2"),
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, skill_id="S3"),
        _skill("โครงสร้างข้อมูล", KSECCategory.K, skill_id="S4"),
    ]
    buckets = bucket_by_ksec(skills)
    for ksec, members in buckets.items():
        assert {m.ksec_category for m in members} == {ksec}
    assert sum(len(v) for v in buckets.values()) == len(skills)


def test_bucket_by_ksec_omits_empty_buckets():
    buckets = bucket_by_ksec([_skill("เขียนโปรแกรม", KSECCategory.SS)])
    assert set(buckets) == {KSECCategory.SS}


def test_merge_bloom_takes_the_higher_level():
    # The user's example: Recognition < Analysis.
    assert merge_bloom([BloomLevel.REMEMBER, BloomLevel.ANALYZE]) is BloomLevel.ANALYZE
    assert merge_bloom([BloomLevel.CREATE, BloomLevel.APPLY]) is BloomLevel.CREATE


def test_merge_bloom_single_level_is_itself():
    assert merge_bloom([BloomLevel.EVALUATE]) is BloomLevel.EVALUATE


def test_merge_bloom_rejects_empty():
    with pytest.raises(ValueError):
        merge_bloom([])


def test_dedupe_collapses_same_name_and_keeps_max_bloom():
    skills = [
        _skill("วิเคราะห์ข้อมูล", bloom=BloomLevel.REMEMBER, skill_id="S1"),
        _skill("  วิเคราะห์ข้อมูล  ", bloom=BloomLevel.ANALYZE, skill_id="S2"),
        _skill("เขียนรายงาน", bloom=BloomLevel.APPLY, skill_id="S3"),
    ]
    names, groups, bloom_by_name = dedupe_with_bloom_max(skills)

    assert len(names) == 2
    analysed = next(n for n in names if "วิเคราะห์" in n)
    assert bloom_by_name[analysed] is BloomLevel.ANALYZE
    assert sorted(len(g) for g in groups) == [1, 2]


def test_dedupe_with_blank_name_reports_skip():
    """Verify that whitespace-only skill names are skipped with a warning."""
    skills = [
        _skill("วิเคราะห์ข้อมูล", skill_id="S1"),
        _skill("   ", skill_id="S2"),  # whitespace-only
        _skill("\t\n", skill_id="S3"),  # other whitespace
        _skill("เขียนรายงาน", skill_id="S4"),
    ]

    with patch("curriculum_agent.stages.need_grouping.logger") as mock_logger:
        names, groups, bloom_by_name = dedupe_with_bloom_max(skills)

        # Two valid names, two skipped
        assert len(names) == 2
        assert len(groups) == 2
        assert all(name.strip() for name in names)  # no blank names in output

        # logger.warning must be called with the skip count
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0][0]
        assert call_args == "dedupe_with_bloom_max: skipped 2 blank/whitespace-only name(s)"
