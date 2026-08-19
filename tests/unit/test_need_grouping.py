from __future__ import annotations

from unittest.mock import patch

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory, StakeholderType
from curriculum_agent.stages.need_grouping import (
    bucket_by_ksec,
    dedupe_with_bloom_max,
    find_code_identifier,
    find_vague_phrase,
    looks_like_a_skill_list,
    merge_bloom,
)


def _skill(
    name: str,
    ksec: KSECCategory = KSECCategory.S,
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
        source_stakeholder_type=StakeholderType.EMPLOYER,
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


def test_bucket_by_ksec_never_mixes_tags():
    skills = [
        _skill("เขียนโปรแกรม", KSECCategory.S, skill_id="S1"),
        _skill("ทำงานเป็นทีม", KSECCategory.K, skill_id="S2"),
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, skill_id="S3"),
        _skill("โครงสร้างข้อมูล", KSECCategory.K, skill_id="S4"),
    ]
    buckets = bucket_by_ksec(skills)
    for ksec, members in buckets.items():
        member_tags = {m.ksec_category for m in members}
        if ksec == KSECCategory.EC:
            assert member_tags <= {KSECCategory.E, KSECCategory.C}
        else:
            assert member_tags == {ksec}
    assert sum(len(v) for v in buckets.values()) == len(skills)


def test_bucket_by_ksec_omits_empty_buckets():
    buckets = bucket_by_ksec([_skill("เขียนโปรแกรม", KSECCategory.S)])
    assert set(buckets) == {KSECCategory.S}


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


def test_ethics_and_character_share_one_ec_bucket():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import bucket_by_ksec

    skills = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, skill_id="S1"),
        _skill("ความรับผิดชอบต่อหน้าที่", KSECCategory.C, skill_id="S2"),
        _skill("เขียนโปรแกรม", KSECCategory.S, skill_id="S3"),
    ]
    buckets = bucket_by_ksec(skills)
    assert set(buckets) == {KSECCategory.EC, KSECCategory.S}
    assert len(buckets[KSECCategory.EC]) == 2


def test_need_tag_is_e_when_every_member_is_e():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import resolve_need_ksec

    members = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, skill_id="S1"),
        _skill("ความซื่อสัตย์ในวิชาชีพ", KSECCategory.E, skill_id="S2"),
    ]
    assert resolve_need_ksec(members) is KSECCategory.E


def test_need_tag_is_c_when_every_member_is_c():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import resolve_need_ksec

    members = [_skill("ความรับผิดชอบต่อหน้าที่", KSECCategory.C, skill_id="S1")]
    assert resolve_need_ksec(members) is KSECCategory.C


def test_need_tag_is_ec_when_members_mix_ethics_and_character():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import resolve_need_ksec

    members = [
        _skill("จรรยาบรรณวิชาชีพ", KSECCategory.E, skill_id="S1"),
        _skill("ความรับผิดชอบต่อหน้าที่", KSECCategory.C, skill_id="S2"),
    ]
    assert resolve_need_ksec(members) is KSECCategory.EC


def test_need_tag_of_a_non_ec_bucket_is_the_member_tag():
    from curriculum_agent.models import KSECCategory
    from curriculum_agent.stages.need_grouping import resolve_need_ksec

    members = [_skill("เขียนโปรแกรม", KSECCategory.S, skill_id="S1")]
    assert resolve_need_ksec(members) is KSECCategory.S


# --- code-token guard on the generated Need sentence -----------------------


@pytest.mark.parametrize(
    "statement",
    [
        # The one that shipped: a Thai abbreviation fused to a Java method name.
        "ตลาดแรงงานต้องการบุคคลที่สามารถเป็นผู้ประกอบการ หน.getDefault รับฟังผู้บริหาร",
        "ตลาดแรงงานต้องการผู้ที่ใช้ get_default ในการทำงาน",
        "ตลาดแรงงานต้องการผู้ที่เรียกใช้ calculate() ได้",
        "ตลาดแรงงานต้องการผู้ที่เข้าใจ obj.getValue อย่างลึกซึ้ง",
    ],
)
def test_code_identifiers_are_detected(statement: str) -> None:
    assert find_code_identifier(statement) is not None


@pytest.mark.parametrize(
    "statement",
    [
        # Every one of these is ordinary Thai curriculum language. A guard that
        # rejects them is worse than the bug: it would retry good sentences and
        # fall back to a comma-joined skill list.
        "ตลาดแรงงานต้องการผู้ที่ประยุกต์ AI และ Data Science กับงานธุรกิจได้",
        "ตลาดแรงงานต้องการผู้ที่เข้าใจหลัก ESG และความยั่งยืนขององค์กร",
        "ตลาดแรงงานต้องการผู้ที่ให้คำปรึกษา SME ด้านการเงินได้",
        "ตลาดแรงงานต้องการผู้ที่พัฒนาเว็บด้วย JavaScript และ TypeScript",
        "ตลาดแรงงานต้องการผู้ที่ใช้ IoT ในงานอุตสาหกรรม",
        "ตลาดแรงงานต้องการผู้ที่ใช้เครื่องมือ Power BI วิเคราะห์ข้อมูลยอดขาย",
        "ตลาดแรงงานต้องการบุคคลที่สื่อสารและทำงานเป็นทีมได้อย่างมีประสิทธิภาพ",
    ],
)
def test_ordinary_thai_and_english_terms_pass(statement: str) -> None:
    assert find_code_identifier(statement) is None


def test_the_detector_reports_what_it_found() -> None:
    """The retry prompt names the offending token, so the detector has to return
    it rather than a bare bool."""
    found = find_code_identifier("ตลาดแรงงานต้องการ หน.getDefault ในงาน")
    assert found is not None
    assert "getDefault" in found


@pytest.mark.parametrize(
    "statement",
    [
        # Both shipped in the same regeneration that the first guard passed.
        "ตลาดแรงงานต้องการผู้ที่คิดวิเคราะห์เชิงกลยุทธ์chant และนวัตกรรม",
        "ตลาดต้องการผู้LEANที่มีประสบการณ์สามารถสร้างความแตกต่าง",
        # Latin leading into Thai is the same defect mirrored.
        "ตลาดแรงงานต้องการผู้ที่ใช้ AIระบบ ในการทำงาน",
    ],
)
def test_thai_fused_to_latin_without_a_space_is_detected(statement: str) -> None:
    assert find_code_identifier(statement) is not None


@pytest.mark.parametrize(
    "statement",
    [
        # A space is all that separates a leak from correct Thai typography.
        "ตลาดแรงงานต้องการผู้ที่ประยุกต์ AI และ Data Science กับงานธุรกิจได้",
        "ตลาดแรงงานต้องการผู้ที่บริหารงานแบบ Lean ได้อย่างมีประสิทธิภาพ",
        # Digits fused to Thai are ordinary: years, counts, มคอ. numbers.
        "ตลาดแรงงานต้องการผู้ที่เข้าใจแผนพัฒนาฉบับที่ 13 พ.ศ.2566",
    ],
)
def test_spaced_english_and_fused_digits_still_pass(statement: str) -> None:
    assert find_code_identifier(statement) is None


# --- the sentence has to be specific enough to draft a PLO from ------------


@pytest.mark.parametrize(
    "statement",
    [
        # A generic head noun with an empty modifier names no capability, so a PLO
        # drafted from it would have to be invented rather than derived.
        "ตลาดแรงงานต้องการผู้ที่มีทักษะที่จำเป็นต่อการทำงาน",
        "ตลาดแรงงานต้องการผู้ที่มีความรู้ที่เกี่ยวข้องกับอุตสาหกรรม",
        "ตลาดแรงงานต้องการผู้ที่มีสมรรถนะด้านต่างๆ",
        "ตลาดแรงงานต้องการผู้ที่มีความสามารถที่หลากหลาย",
        # Restating the question instead of answering it.
        "ตลาดแรงงานต้องการบุคลากรที่มีคุณสมบัติตามที่ตลาดต้องการ",
        "ตลาดแรงงานต้องการผู้ที่ทำงานได้ตามความต้องการของตลาด",
    ],
)
def test_content_free_phrases_are_detected(statement: str) -> None:
    assert find_vague_phrase(statement) is not None


@pytest.mark.parametrize(
    "statement",
    [
        # Each names a capability, an object, and a context. Over-rejecting these
        # costs a retry and, on the third failure, a Need the designer must write
        # by hand — the same trade-off the code-token guard is tuned against.
        "ตลาดแรงงานต้องการผู้ที่ออกแบบระบบฐานข้อมูลสำหรับงานธุรกิจได้",
        # "ที่จำเป็น" attached to a real object, not to a generic head noun.
        "ตลาดแรงงานต้องการผู้ที่คัดกรองข้อมูลที่จำเป็นต่อการตัดสินใจของผู้บริหารได้",
        "ตลาดแรงงานต้องการผู้ที่ประเมินความเสี่ยงด้านการเงินของลูกค้ารายย่อยได้",
        "ตลาดแรงงานต้องการผู้ที่วิเคราะห์ข้อมูลยอดขายด้วย Power BI เพื่อวางแผนการตลาด",
    ],
)
def test_specific_market_sentences_pass_the_vagueness_check(statement: str) -> None:
    assert find_vague_phrase(statement) is None


def test_the_vagueness_detector_reports_what_it_found() -> None:
    """Named in the retry prompt: a model told "ทักษะที่จำเป็น" was rejected
    replaces that phrase, while one told the sentence was invalid rewrites the
    wrong half."""
    found = find_vague_phrase("ตลาดแรงงานต้องการผู้ที่มีทักษะที่จำเป็นต่อการทำงาน")
    assert found is not None
    assert "ที่จำเป็น" in found


@pytest.mark.parametrize(
    "statement",
    [
        "เขียนโปรแกรมเว็บ, ออกแบบฐานข้อมูล, ทดสอบระบบ, เขียนเอกสาร",
        "K, S, E, C, EC",
    ],
)
def test_a_comma_joined_skill_list_is_detected(statement: str) -> None:
    assert looks_like_a_skill_list(statement) is True


@pytest.mark.parametrize(
    "statement",
    [
        # Two commas is ordinary Thai prose, which is why the floor sits above it.
        "ตลาดแรงงานต้องการผู้ที่ออกแบบ, พัฒนา และดูแลระบบสารสนเทศขององค์กรได้",
        "ตลาดแรงงานต้องการผู้ที่ออกแบบระบบฐานข้อมูลสำหรับงานธุรกิจได้",
    ],
)
def test_prose_with_a_comma_or_two_is_not_a_list(statement: str) -> None:
    assert looks_like_a_skill_list(statement) is False
