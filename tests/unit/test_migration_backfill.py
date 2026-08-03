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

from curriculum_agent.models import StakeholderType


def _load_migration():
    path = next(Path("migrations/versions").glob("*_stakeholder_classification_redesign.py"))
    spec = importlib.util.spec_from_file_location("redesign_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_deleted_stakeholder_type_is_remapped():
    module = _load_migration()
    assert set(module.STAKEHOLDER_TYPE_BACKFILL) == {
        "accreditation_body",
        "university",
        "subject_benchmark",
        "peer_program",
    }


def test_every_remap_target_exists_in_the_new_enum():
    module = _load_migration()
    valid = {t.value for t in StakeholderType}
    assert set(module.STAKEHOLDER_TYPE_BACKFILL.values()) <= valid


def test_ksec_backfill_maps_both_removed_tags_to_s():
    module = _load_migration()
    assert module.KSEC_BACKFILL == {"SS": "S", "GS": "S"}
