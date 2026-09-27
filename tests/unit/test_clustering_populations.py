"""`_build_groups` clusters each KSEC bucket as two populations.

Why, measured rather than argued, is in ticket 16 and in `_build_groups`'s own
docstring: rows extraction flagged `is_graduate_capability=False` belong to no
competency the other names form, the model leaves them unassigned, and
`validate_assignments` turns each one into a singleton Need that then becomes a
PLO. Holding them into their own clustering call is what stops that.

These tests pin the two halves that are easy to undo by accident — that the
populations never mix, and that nothing is dropped to achieve it.
"""

from __future__ import annotations

import pytest

from curriculum_agent.models import BloomLevel, ExtractedSkill, KSECCategory, StakeholderType
from curriculum_agent.stages import need_combination as nc
from curriculum_agent.stages.need_grouping import MAX_CORE_PLOS


def _skill(name: str, sid: str, eid: str, *, graduate: bool = True) -> ExtractedSkill:
    return ExtractedSkill(
        skill_id=sid,
        program_id="p",
        skill_name_th=name,
        ksec_category=KSECCategory.S,
        bloom_level=BloomLevel.APPLY,
        evidence_span_th=name,
        source_evidence_id=eid,
        source_stakeholder_type=StakeholderType.EMPLOYER,
        classification="need",
        extraction_method="llm",
        confidence=0.9,
        importance_score=0.5,
        is_graduate_capability=graduate,
    )


GRADUATE = ["การแปลเอกสารกฎหมาย", "การล่ามเจรจา", "การปรับสำนวน"]
INSTITUTIONAL = ["การออกแบบหลักสูตร", "การประเมินผลลัพธ์การเรียนรู้"]


@pytest.fixture
def mixed() -> list[ExtractedSkill]:
    rows = [_skill(n, f"G{i}", f"E{i}") for i, n in enumerate(GRADUATE)]
    rows += [_skill(n, f"I{i}", f"E{i}", graduate=False) for i, n in enumerate(INSTITUTIONAL)]
    return rows


def _record_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], int | None]]:
    """Capture what each clustering call is handed; group everything into one."""
    seen: list[tuple[list[str], int | None]] = []

    async def fake_cluster(
        names: list[str], target: int | None = None, program_context: str | None = None
    ) -> list[list[int]]:
        seen.append((list(names), target))
        return [list(range(len(names)))]

    monkeypatch.setattr(nc, "cluster_skill_names", fake_cluster)
    return seen


async def test_a_group_never_mixes_the_two_populations(
    mixed: list[ExtractedSkill], monkeypatch: pytest.MonkeyPatch
):
    """The observable property, and the one worth pinning.

    `graduate_capability_skill_count` is 0 or every member — never in between.
    A single shared clustering call would produce a group holding both, and the
    scope guard's ratio would then have to adjudicate a mixture that should
    never have been formed.
    """
    _record_calls(monkeypatch)

    groups = await nc._build_groups(mixed, {f"E{i}": "employer" for i in range(3)})

    assert groups
    for g in groups:
        members = len(g.skill_ids)
        assert g.graduate_capability_skill_count in (0, members)


async def test_neither_call_sees_the_other_populations_names(
    mixed: list[ExtractedSkill], monkeypatch: pytest.MonkeyPatch
):
    seen = _record_calls(monkeypatch)

    await nc._build_groups(mixed, {f"E{i}": "employer" for i in range(3)})

    assert len(seen) == 2, "one clustering call per population in the bucket"
    by_names = {frozenset(names) for names, _ in seen}
    assert by_names == {frozenset(GRADUATE), frozenset(INSTITUTIONAL)}


async def test_the_institutional_names_do_not_spend_the_plo_budget(
    mixed: list[ExtractedSkill], monkeypatch: pytest.MonkeyPatch
):
    """`MAX_CORE_PLOS` bounds outcomes, and only a graduate capability becomes
    one. Sizing the graduate call against the combined name count is what let
    eleven institutional names eat the S bucket's eight slots."""
    seen = _record_calls(monkeypatch)

    await nc._build_groups(mixed, {f"E{i}": "employer" for i in range(3)})

    target_by_names = {frozenset(names): target for names, target in seen}
    graduate_target = target_by_names[frozenset(GRADUATE)]
    # One bucket, one population: it gets the whole ceiling, capped at how many
    # names it actually has. The combined list would have capped at 5 instead.
    assert graduate_target == min(MAX_CORE_PLOS, len(GRADUATE))


async def test_every_skill_still_lands_in_exactly_one_group(
    mixed: list[ExtractedSkill], monkeypatch: pytest.MonkeyPatch
):
    """Splitting the populations must not become dropping one of them.

    The institutional rows stay in the pipeline as Needs that trace to their
    evidence; `is_in_scope` decides at plo_synthesis whether an outcome may be
    drafted from them. That is a different thing from never recording them.
    """
    _record_calls(monkeypatch)

    groups = await nc._build_groups(mixed, {f"E{i}": "employer" for i in range(3)})

    landed = [sid for g in groups for sid in g.skill_ids]
    assert sorted(landed) == sorted(s.skill_id for s in mixed)
    assert len(landed) == len(set(landed)), "no skill in two groups"


async def test_a_bucket_of_one_population_makes_one_call(
    monkeypatch: pytest.MonkeyPatch,
):
    """The empty half is skipped rather than clustered as an empty list."""
    seen = _record_calls(monkeypatch)
    rows = [_skill(n, f"G{i}", f"E{i}") for i, n in enumerate(GRADUATE)]

    await nc._build_groups(rows, {f"E{i}": "employer" for i in range(3)})

    assert len(seen) == 1


async def test_a_name_flagged_both_ways_lands_on_the_graduate_side(
    monkeypatch: pytest.MonkeyPatch,
):
    """One extraction call calling a name institutional does not outvote another
    that did not — the same direction `classify_skills` reads `is_field_relevant`.

    A name must end up in exactly one population whatever the rows disagree
    about, or dedupe emits it once per side and the skill is in two groups.
    """
    seen = _record_calls(monkeypatch)
    rows = [
        _skill("การแปลเอกสารกฎหมาย", "A", "E1", graduate=True),
        _skill("การแปลเอกสารกฎหมาย", "B", "E2", graduate=False),
        _skill("การออกแบบหลักสูตร", "C", "E3", graduate=False),
    ]

    groups = await nc._build_groups(rows, {"E1": "employer", "E2": "faculty", "E3": "faculty"})

    by_names = {frozenset(names) for names, _ in seen}
    assert by_names == {frozenset({"การแปลเอกสารกฎหมาย"}), frozenset({"การออกแบบหลักสูตร"})}
    landed = [sid for g in groups for sid in g.skill_ids]
    assert sorted(landed) == ["A", "B", "C"]
    assert len(landed) == len(set(landed))


async def test_the_institutional_side_is_clustered_to_the_same_granularity(
    monkeypatch: pytest.MonkeyPatch,
):
    """It gets a number, but not a budget.

    The first version handed it MAX_CORE_PLOS as well, so fourteen
    institutional names were asked for nine groups: no PLO slot was spent, but
    the prompt was told to fragment — the very thing this split exists to stop,
    moved to the other population. Nothing downstream counts these groups, so
    the number only has to serve the designer reading them, and it follows the
    names-per-group the graduate side is being asked for.
    """
    seen = _record_calls(monkeypatch)
    graduate = [_skill(f"ทักษะบัณฑิต{i}", f"G{i}", f"E{i % 3}") for i in range(40)]
    institutional = [
        _skill(f"ภารกิจสถาบัน{i}", f"I{i}", f"E{i % 3}", graduate=False) for i in range(12)
    ]

    await nc._build_groups(graduate + institutional, {f"E{i}": "employer" for i in range(3)})

    by_size = {len(names): target for names, target in seen}
    graduate_target = by_size[40]
    institutional_target = by_size[12]

    assert graduate_target == MAX_CORE_PLOS, "the graduate side spends the whole ceiling"
    # 40 names over 10 groups is 4 a group; 12 institutional names at that
    # granularity is 3 — not another 10.
    assert institutional_target == round(12 / (40 / graduate_target))
    assert institutional_target < graduate_target
