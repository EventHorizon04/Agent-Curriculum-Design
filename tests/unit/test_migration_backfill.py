"""The migration's data rules, tested as pure functions.

The SQL runs against Postgres in CI; what matters here is that the mapping from
old values to new is total. A stakeholder_type left unmapped is not a cosmetic
problem: Need.stakeholder_coverage is typed dict[StakeholderType, int], so a
surviving row with a deleted value raises ValidationError inside
repositories.list_by_program and breaks GET /evidence/ for the whole program.
"""

from __future__ import annotations

# Imported from the migration module by file path — Alembic revisions are not
# importable as a package.
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from curriculum_agent.models import StakeholderType


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    path = next(Path("migrations/versions").glob("*_stakeholder_classification_redesign.py"))
    spec = importlib.util.spec_from_file_location("redesign_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_deleted_stakeholder_type_is_remapped(migration: ModuleType) -> None:
    assert set(migration.STAKEHOLDER_TYPE_BACKFILL) == {
        "accreditation_body",
        "university",
        "subject_benchmark",
        "peer_program",
    }


def test_every_remap_target_exists_in_the_new_enum(migration: ModuleType) -> None:
    valid = {t.value for t in StakeholderType}
    assert set(migration.STAKEHOLDER_TYPE_BACKFILL.values()) <= valid


def test_ksec_backfill_maps_both_removed_tags_to_s(migration: ModuleType) -> None:
    assert migration.KSEC_BACKFILL == {"SS": "S", "GS": "S"}


def test_stakeholder_coverage_remap_is_total_over_deleted_keys(migration: ModuleType) -> None:
    # Every deleted key, alone in a coverage dict, must remap to a surviving key.
    coverage = {old: 1 for old in migration.STAKEHOLDER_TYPE_BACKFILL}
    remapped = migration._remap_stakeholder_coverage(coverage)
    assert not set(remapped) & set(migration.STAKEHOLDER_TYPE_BACKFILL)
    assert set(remapped) <= {t.value for t in StakeholderType}


def test_stakeholder_coverage_remap_sums_on_collision(migration: ModuleType) -> None:
    # A row can already hold both a deleted key and its replacement; the
    # counts must sum, not overwrite one another.
    coverage = {"accreditation_body": 3, "professional_council": 2, "expert": 1}
    remapped = migration._remap_stakeholder_coverage(coverage)
    assert remapped == {"professional_council": 5, "expert": 1}


def test_stakeholder_coverage_remap_leaves_untouched_keys_alone(migration: ModuleType) -> None:
    coverage = {"employer": 4, "faculty": 2}
    remapped = migration._remap_stakeholder_coverage(coverage)
    assert remapped == coverage
