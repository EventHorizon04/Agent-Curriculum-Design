"""The scope predicate and the two counters it reads.

`is_in_scope` is the single switch behind the whole guard: it is called from one
place in plo_synthesis and one in the merge route, and turning the guard off is
supposed to mean deleting those two calls. That only holds while the predicate
itself has no opinions of its own, so its truth table is pinned here rather than
inferred from the stages that use it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import BloomLevel, KSECCategory, Need
from curriculum_agent.stages.need_grouping import is_in_scope


def _need(**overrides: object) -> Need:
    data: dict[str, object] = {
        "need_id": "N1",
        "program_id": "cs-test",
        "statement_th": "ต้องการบัณฑิตที่ออกแบบและดูแลระบบสารสนเทศขององค์กรให้ใช้งานได้จริง",
        "ksec_category": KSECCategory.S,
        "bloom_level": BloomLevel.ANALYZE,
        "member_skill_ids": ["S1", "S2", "S3"],
        "source_evidence_ids": ["E1"],
        "freq": 2,
        "demand_score": 0.7,
    }
    data.update(overrides)
    return Need.model_validate(data)


@pytest.mark.parametrize(
    ("in_field", "graduate", "expected"),
    [
        (2, 3, True),
        (0, 3, False),
        (2, 0, False),
        (0, 0, False),
    ],
)
def test_a_need_is_in_scope_only_when_both_axes_clear_the_threshold(
    in_field: int, graduate: int, expected: bool
) -> None:
    """`and`, not `or`.

    The two axes were measured to overlap almost completely, so the data cannot
    choose between them — the policy does, and the policy is that failing either
    one disqualifies a Need. A Need that is not a graduate capability cannot be
    written as a PLO at all, not merely written about the wrong field.
    """
    need = _need(in_field_skill_count=in_field, graduate_capability_skill_count=graduate)
    assert is_in_scope(need) is expected


def test_the_model_reports_shares_and_the_threshold_lives_in_one_place() -> None:
    """The Need reports what was measured; where the cut falls is policy, and
    policy for which Needs become PLOs is written once in need_grouping.

    A share rather than a flag is what makes the cut movable at all — the flag it
    replaces hard-coded "more than zero" into the model, where the eval could not
    reach it."""
    need = _need(in_field_skill_count=1, graduate_capability_skill_count=2)
    assert len(need.member_skill_ids) == 3
    assert need.in_field_ratio == pytest.approx(1 / 3)
    assert need.graduate_capability_ratio == pytest.approx(2 / 3)


def test_a_need_flagged_on_most_of_its_members_no_longer_survives() -> None:
    """The case that forced the threshold, taken from a full pipeline run.

    Six of this Need's seven members were flagged off-field and five of seven as
    institutional activity, and under the old "one qualifying member is enough"
    rule it still became the second-highest-demand core PLO — an outcome about
    what the institution does, not about what a graduate can do."""
    need = _need(
        member_skill_ids=[f"s{i}" for i in range(7)],
        in_field_skill_count=1,
        graduate_capability_skill_count=2,
    )
    assert is_in_scope(need) is False


def test_a_need_flagged_on_a_minority_of_its_members_still_survives() -> None:
    """The other half of the same trade. One or two flags among many members is
    the extractor being unsure, not the Need being out of scope — and a Need
    filtered by mistake is a PLO that vanishes with nobody told."""
    need = _need(
        member_skill_ids=[f"s{i}" for i in range(6)],
        in_field_skill_count=4,
        graduate_capability_skill_count=6,
    )
    assert is_in_scope(need) is True


def test_a_need_that_never_carried_the_counters_reads_as_fully_in_scope() -> None:
    """Absent is not zero.

    Zero means the extractor judged every member out of scope and the Need is
    disqualified; absent means nobody ever asked, which has to leave behaviour
    exactly as it was. Rows already in Postgres are backfilled by the migration,
    but a Need also arrives as a plain dict — a LangGraph checkpoint suspended
    across the deploy holds a whole AgentState, Needs included, and it never
    touches the migration. Defaulting those to 0 would filter every Need out of a
    resumed run with nobody having asked for it.
    """
    resumed_from_checkpoint = {
        "need_id": "N1",
        "program_id": "cs-test",
        "statement_th": "ต้องการบัณฑิตที่ออกแบบและดูแลระบบสารสนเทศขององค์กรให้ใช้งานได้จริง",
        "ksec_category": "S",
        "bloom_level": "analyze",
        "member_skill_ids": ["S1", "S2", "S3"],
        "source_evidence_ids": ["E1"],
        "freq": 2,
        "demand_score": 0.7,
    }

    need = Need.model_validate(resumed_from_checkpoint)

    assert need.in_field_skill_count == 3
    assert need.graduate_capability_skill_count == 3
    assert is_in_scope(need) is True


def test_a_need_constructed_without_the_counters_is_in_scope_too() -> None:
    """The no-op case the guard depends on: a program whose designer wrote no
    scope statement gets flags of True on every skill row, counters equal to the
    member count, and a predicate that passes everything. That is why there is no
    "does this program have a scope statement?" branch anywhere in the pipeline —
    the guard disables itself."""
    need = _need()

    assert need.in_field_skill_count == len(need.member_skill_ids)
    assert is_in_scope(need) is True


def test_an_explicit_zero_survives_the_default_and_disqualifies_the_need() -> None:
    """The default must not swallow a real judgement. A Need whose members were
    all judged out of field stores 0, and 0 has to stay 0 — otherwise the guard
    filters nothing at all."""
    need = _need(in_field_skill_count=0, graduate_capability_skill_count=3)

    assert need.in_field_skill_count == 0
    assert need.in_field_ratio == 0.0
    assert is_in_scope(need) is False


async def test_the_graduate_capability_flag_reaches_the_stored_skill_row_unaggregated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Written per row, like is_field_relevant beside it and unlike
    `classification`, which is ORed across every row sharing a skill name.

    The inconsistency is deliberate. need_combination counts rows, and OR-by-name
    would drive the count towards the member total whenever a name recurs across
    evidence items — the fraction a designer reads at the checkpoint would be 8/8
    every time. The `any` rule the counters feed reads the same either way; only
    the fraction differs, and the fraction is the point.
    """
    from curriculum_agent.stages import skill_extraction as se

    text = "ต้องบริหารจัดการหลักสูตรและพัฒนาแหล่งรายได้ของคณะให้เพียงพอต่อการดำเนินงาน"
    answer = se._ExtractedSkillsResponse(
        skills=[
            se._SkillItem(
                skill_name_th="การบริหารจัดการและพัฒนาแหล่งรายได้",
                skill_name_en="Revenue Development",
                ksec_category="S",
                bloom_level="apply",
                evidence_span_th="บริหารจัดการหลักสูตรและพัฒนาแหล่งรายได้",
                is_field_relevant=False,
                is_graduate_capability=False,
                confidence=0.9,
            )
        ]
    )

    monkeypatch.setattr(se.LLMCacheRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(se.LLMCacheRepository, "set", AsyncMock())
    monkeypatch.setattr(se.SkillRepository, "delete_by_program", AsyncMock(return_value=0))
    monkeypatch.setattr(se.SkillRepository, "bulk_insert", AsyncMock())
    monkeypatch.setattr(se, "complete_extraction", AsyncMock(return_value=answer))

    state = await se.run(
        {
            "program_id": "cs-test",
            "classified_evidence": [
                {
                    "evidence_id": "E1",
                    "program_id": "cs-test",
                    "stakeholder_type": "institutional_direction",
                    "source_name": "วิสัยทัศน์คณะ",
                    "raw_text_th": text,
                    "classification": "requirement",
                }
            ],
        }
    )

    (skill,) = state["extracted_skills"]
    assert skill["is_graduate_capability"] is False
    assert skill["is_field_relevant"] is False
    # Requirement still wins on classification — the flags do not leak into it.
    assert skill["classification"] == "requirement"
