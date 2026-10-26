"""SkillGroup: the clusters agent 1 stores for agent 2.

Pure model and copy-build tests; the repository's SQL is not exercised here.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from curriculum_agent.data.orm import (
    EvidenceTable,
    ProgramTable,
    SkillGroupTable,
    SkillTable,
)
from curriculum_agent.data.program_copy import ProgramRows, build_copy
from curriculum_agent.data.repositories import ProgramRepository, _row_to_dict
from curriculum_agent.models import BloomLevel, KSECCategory, SkillGroup, StakeholderType

NOW = datetime(2026, 10, 26, 12, 0, 0)


def _group() -> SkillGroup:
    return SkillGroup(
        group_id="g-1",
        program_id="program-2",
        ksec=KSECCategory.S,
        skill_ids=["sk-1"],
        evidence_ids=["ev-1"],
        skill_names=["การสื่อสารภาษาอังกฤษ"],
        skill_frequencies=[3],
        bloom_level=BloomLevel.APPLY,
        demand_score=0.5,
        is_optional=False,
        is_graduate=True,
        classification_coverage={"want": 1},
        stakeholder_coverage={StakeholderType.EMPLOYER: 1},
        stakeholder_types=[StakeholderType.EMPLOYER],
        in_field_skill_count=1,
        graduate_capability_skill_count=1,
    )


def test_skill_group_round_trips_through_json() -> None:
    group = _group()
    restored = SkillGroup.model_validate(json.loads(group.model_dump_json()))
    assert restored == group
    assert restored.stakeholder_coverage == {StakeholderType.EMPLOYER: 1}


def _source() -> ProgramRows:
    program = ProgramTable(
        program_id="program-2",
        name_th="",
        name_en="",
        field="การท่องเที่ยว",
        degree_level="bachelor",
        duration_years=4,
        faculty="คณะ",
        university="มหาวิทยาลัย",
        scope_th="",
        program_goals_th=[],
        program_objectives_th=[],
        created_at=datetime(2026, 9, 1),
        copied_from=None,
    )
    evidence = [
        EvidenceTable(
            evidence_id="ev-1",
            program_id="program-2",
            stakeholder_type="employer",
            source_name="โรงแรม",
            raw_text_th="ต้องการพนักงานที่สื่อสารภาษาอังกฤษได้",
            collected_at=datetime(2026, 9, 1),
            classification="general",
            extra_metadata={},
        )
    ]
    skills = [
        SkillTable(
            skill_id="sk-1",
            program_id="program-2",
            skill_name_th="การสื่อสารภาษาอังกฤษ",
            ksec_category="S",
            bloom_level="apply",
            evidence_span_th="สื่อสารภาษาอังกฤษได้",
            source_evidence_id="ev-1",
            source_stakeholder_type="employer",
            classification="want",
            is_field_relevant=True,
            is_graduate_capability=True,
            extraction_method="llm",
            confidence=0.9,
            importance_score=0.5,
        )
    ]
    row = SkillGroupTable(
        ordinal=0,
        **_group().model_dump(mode="json"),
    )
    return ProgramRows(
        program=program,
        evidence=evidence,
        skills=skills,
        needs=[],
        plos=[],
        review=None,
        skill_groups=[row],
    )


def test_copy_build_remaps_skill_group_ids() -> None:
    counter = itertools.count(1)
    copy = build_copy(
        _source(), "program-2-run-1", now=NOW, new_uuid=lambda: f"new-{next(counter)}"
    )
    (group,) = copy.skill_groups
    assert group.program_id == "program-2-run-1"
    assert group.group_id != "g-1"
    assert group.skill_ids == [copy.skills[0].skill_id]
    assert group.evidence_ids == [copy.evidence[0].evidence_id]
    assert group.ordinal == 0
    assert "g-1" not in json.dumps([_row_to_dict(r) for r in copy.skill_groups], default=str)


async def test_delete_cascade_lists_skill_groups_before_skills() -> None:
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[MagicMock(rowcount=1) for _ in range(10)])
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("curriculum_agent.data.repositories.AsyncSessionLocal", return_value=mock_ctx):
        await ProgramRepository().delete_cascade("cs")
    sql = [str(c.args[0]) for c in mock_session.execute.call_args_list]
    assert sql.index(next(s for s in sql if s.startswith("DELETE FROM skill_groups"))) < sql.index(
        next(s for s in sql if s.startswith("DELETE FROM skills"))
    )
