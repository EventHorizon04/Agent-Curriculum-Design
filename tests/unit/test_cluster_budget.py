"""Clustering is sized against the PLO ceiling before it runs.

Each KSEC bucket used to be asked for "typically 4–12 groups" with no notion of
how many buckets there were. Three buckets therefore produced 12–36 Needs
against a ceiling of ten, so how many Needs a program got was decided by how
splitty the model felt, and plo_synthesis routinely dropped most of what
need_combination had written and stored.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory, StakeholderType
from curriculum_agent.prompts.cluster_skills import (
    build_cluster_skills_prompt,
    build_merge_clusters_prompt,
)
from curriculum_agent.stages import need_combination as nc
from curriculum_agent.stages import skill_grouping as sg
from curriculum_agent.stages.need_grouping import MAX_CORE_PLOS, allocate_cluster_targets
from tests.support.needs import RATIONALE_TH, run_need_pipeline_from_skills

K, S, EC = KSECCategory.K, KSECCategory.S, KSECCategory.EC


# --- the allocation -------------------------------------------------------


def test_the_budget_adds_up_to_the_ceiling():
    targets = allocate_cluster_targets({K: 40, S: 50, EC: 10})
    assert sum(targets.values()) == MAX_CORE_PLOS


def test_shares_follow_how_many_skills_each_domain_holds():
    targets = allocate_cluster_targets({K: 40, S: 50, EC: 10})
    assert targets[S] > targets[K] > targets[EC]


def test_a_thin_domain_still_gets_one_group():
    """K, S and EC are different competency domains — trimming a program's whole
    ethics dimension to hit a count is not a trade the arithmetic gets to make."""
    targets = allocate_cluster_targets({K: 1, S: 1, EC: 200})
    assert targets[K] == targets[S] == 1
    assert sum(targets.values()) == MAX_CORE_PLOS


def test_a_bucket_is_never_asked_for_more_groups_than_it_has_names():
    sizes = {K: 2, S: 3, EC: 1}
    targets = allocate_cluster_targets(sizes)
    assert all(targets[ksec] <= sizes[ksec] for ksec in sizes)
    # The ceiling cannot be reached here, and that is the honest answer rather
    # than an inflated one.
    assert sum(targets.values()) == 6


def test_empty_buckets_are_dropped_not_given_a_group():
    """A domain with no skills gets no share — and the surviving domain is still
    capped by how many names it has to split."""
    assert allocate_cluster_targets({K: 0, S: 5}) == {S: 5}
    assert allocate_cluster_targets({K: 0, S: 50}) == {S: MAX_CORE_PLOS}


def test_no_buckets_means_no_budget():
    assert allocate_cluster_targets({}) == {}


def test_the_floor_of_one_per_bucket_wins_over_a_smaller_ceiling():
    """Asked for fewer groups than there are domains, every domain still gets
    one — a Need count below the domain count is not a shortlist, it is a gap."""
    targets = allocate_cluster_targets({K: 5, S: 5, EC: 5}, total=2)
    assert targets == {K: 1, S: 1, EC: 1}


@pytest.mark.parametrize(
    "sizes",
    [
        {K: 40, S: 50, EC: 10},
        {K: 1, S: 1, EC: 100},
        {S: 100},
        {K: 3, S: 3, EC: 3},
        {K: 7, S: 200, EC: 2},
    ],
)
def test_every_allocation_is_at_least_one_and_within_its_bucket(sizes):
    targets = allocate_cluster_targets(sizes)
    assert set(targets) == set(sizes)
    for ksec, n in targets.items():
        assert 1 <= n <= sizes[ksec]
    assert sum(targets.values()) <= max(MAX_CORE_PLOS, len(sizes))


# --- the prompt -----------------------------------------------------------


def test_the_target_reaches_the_clustering_prompt():
    system = build_cluster_skills_prompt(["a", "b"], 4)[0]["content"]
    assert "about 4 groups" in system
    assert "4–12" not in system


def test_without_a_target_the_prompt_keeps_its_generic_rule():
    """The contract fingerprint calls this with names alone, so the un-targeted
    form has to stay valid."""
    system = build_cluster_skills_prompt(["a", "b"])[0]["content"]
    assert "4–12" in system


def test_the_merge_step_carries_the_target_for_batched_clustering():
    system = build_merge_clusters_prompt(["ก", "ข"], 6)[0]["content"]
    assert "about 6 groups" in system
    assert "about" not in build_merge_clusters_prompt(["ก", "ข"])[0]["content"]


# --- the wiring -----------------------------------------------------------


def _skill(name: str, ksec: KSECCategory, sid: str, eid: str) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="cs-test",
        skill_name_th=name,
        ksec_category=ksec,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=f"หลักฐานที่กล่าวถึง{name}",
        source_evidence_id=eid,
        source_stakeholder_type=StakeholderType.EMPLOYER,
        classification="need",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
    )


async def test_each_bucket_is_clustered_against_its_own_share(monkeypatch):
    skills = (
        [_skill(f"ทักษะปฏิบัติ{i}", S, f"S{i}", f"E{i % 4}") for i in range(20)]
        + [_skill(f"ความรู้{i}", K, f"K{i}", f"E{i % 4}") for i in range(10)]
        + [_skill(f"จรรยาบรรณ{i}", EC, f"C{i}", f"E{i % 4}") for i in range(5)]
    )

    seen: dict[int, int | None] = {}

    async def recording_cluster(
        names: list[str],
        target: int | None = None,
        program_context: str | None = None,
        ksec: object = None,
    ):
        seen[len(names)] = target
        return [list(range(len(names)))]

    async def fake_summarize(model, messages, **kw):  # noqa: ANN001, ANN003
        return nc._NeedStatement(
            statement_th="ตลาดแรงงานต้องการผู้ที่ออกแบบและดูแลระบบสารสนเทศขององค์กรให้ใช้งานได้จริง",
            statement_en="The market needs people who maintain corporate information systems",
            rationale_th=RATIONALE_TH,
        )

    monkeypatch.setattr(sg, "cluster_skill_names", recording_cluster)
    monkeypatch.setattr(nc, "complete_need_combination", fake_summarize)
    monkeypatch.setattr(nc.NeedRepository, "delete_by_program", AsyncMock())
    monkeypatch.setattr(nc.NeedRepository, "bulk_insert", AsyncMock())

    await run_need_pipeline_from_skills(
        {
            "program_id": "cs-test",
            "extracted_skills": [s.model_dump(mode="json") for s in skills],
        }
    )

    # One call per non-empty bucket, each carrying a target rather than None.
    assert set(seen) == {20, 10, 5}
    assert all(target is not None for target in seen.values())
    assert sum(seen.values()) == MAX_CORE_PLOS
    # Ordered by how many skills the domain holds.
    assert seen[20] > seen[10] > seen[5]
