from __future__ import annotations

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory
from curriculum_agent.stages.need_grouping import (
    MAX_NEEDS,
    allocate_quota,
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


def test_quota_passthrough_when_already_within_cap():
    counts = {KSECCategory.SS: 4, KSECCategory.GS: 3}
    quota = allocate_quota(counts, {KSECCategory.SS: 0.8, KSECCategory.GS: 0.4})
    assert quota == counts


def test_quota_caps_total_at_max_needs():
    counts = {KSECCategory.SS: 12, KSECCategory.GS: 6, KSECCategory.K: 4}
    demand = {KSECCategory.SS: 0.9, KSECCategory.GS: 0.5, KSECCategory.K: 0.2}
    quota = allocate_quota(counts, demand)
    assert sum(quota.values()) == MAX_NEEDS


def test_quota_keeps_every_non_empty_bucket_alive():
    # One dominant bucket must not squeeze the others out — the generic/specific
    # balance the programme needs depends on every bucket surviving.
    counts = {
        KSECCategory.SS: 30,
        KSECCategory.GS: 1,
        KSECCategory.K: 1,
        KSECCategory.C: 1,
        KSECCategory.E: 1,
    }
    demand = {
        KSECCategory.SS: 0.95,
        KSECCategory.GS: 0.1,
        KSECCategory.K: 0.1,
        KSECCategory.C: 0.05,
        KSECCategory.E: 0.05,
    }
    quota = allocate_quota(counts, demand)
    assert sum(quota.values()) == MAX_NEEDS
    assert all(v >= 1 for v in quota.values())


def test_quota_never_exceeds_available_groups_in_a_bucket():
    counts = {KSECCategory.SS: 11, KSECCategory.GS: 2}
    demand = {KSECCategory.SS: 0.2, KSECCategory.GS: 0.9}
    quota = allocate_quota(counts, demand)
    assert quota[KSECCategory.GS] <= 2
    assert sum(quota.values()) == MAX_NEEDS


def test_quota_shrink_loop_caps_initial_excess():
    # Initial max(1, ...) allocation can exceed cap with unbalanced bucket sizes.
    # This test ensures the shrink loop corrects it.
    counts = {
        KSECCategory.SS: 1,
        KSECCategory.GS: 1,
        KSECCategory.K: 1,
        KSECCategory.C: 1,
        KSECCategory.E: 56,  # Dominates; initial alloc would be 1+1+1+1+9=13
    }
    demand = {
        KSECCategory.SS: 0.1,
        KSECCategory.GS: 0.1,
        KSECCategory.K: 0.1,
        KSECCategory.C: 0.1,
        KSECCategory.E: 0.9,
    }
    quota = allocate_quota(counts, demand)
    assert sum(quota.values()) == MAX_NEEDS
    assert all(v >= 1 for v in quota.values())


def test_quota_ignores_empty_buckets():
    counts = {KSECCategory.SS: 12, KSECCategory.GS: 0}
    quota = allocate_quota(counts, {KSECCategory.SS: 0.9, KSECCategory.GS: 0.0})
    assert KSECCategory.GS not in quota
