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
import sqlalchemy as sa

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


# --------------------------- PLO scope guard ---------------------------
#
# Same importlib approach, different revision. What matters here is not a
# mapping but an ordering: the columns land nullable, the backfill runs, and only
# then does NOT NULL arrive. Running upgrade() against a recorder is what makes
# that ordering assertable without a database.


class _RecordedOps:
    """Stands in for alembic's `op` so upgrade() can be run and read back."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def add_column(self, table: str, column: sa.Column) -> None:
        self.calls.append(("add_column", table, column))

    def execute(self, statement: str) -> None:
        self.calls.append(("execute", statement))

    def alter_column(self, table: str, column: str, **kwargs: object) -> None:
        self.calls.append(("alter_column", table, column, kwargs))

    def drop_column(self, table: str, column: str) -> None:
        self.calls.append(("drop_column", table, column))


@pytest.fixture(scope="module")
def scope_guard() -> ModuleType:
    path = Path("migrations/versions/a3f8d61e04c7_plo_scope_guard.py")
    spec = importlib.util.spec_from_file_location("scope_guard_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def upgraded(scope_guard: ModuleType, monkeypatch: pytest.MonkeyPatch) -> _RecordedOps:
    recorder = _RecordedOps()
    monkeypatch.setattr(scope_guard, "op", recorder)
    scope_guard.upgrade()
    return recorder


def test_the_need_counters_are_backfilled_from_the_member_list_not_from_zero(
    scope_guard: ModuleType,
) -> None:
    """A server_default of 0 would read as "not one member of this Need is in
    field" for every Need already stored, and the any rule would then filter every
    existing program's entire Need set out of PLO synthesis on the first run after
    deploy, with nobody having asked for it."""
    sql = scope_guard.BACKFILL_NEED_COUNTS

    assert sql.count("jsonb_array_length(member_skill_ids)") == 2
    for column in ("in_field_skill_count", "graduate_capability_skill_count"):
        assert f"{column} = jsonb_array_length(member_skill_ids)" in sql
        assert f"{column} = 0" not in sql


def test_the_backfill_runs_after_the_columns_exist_and_before_they_are_required(
    upgraded: _RecordedOps,
) -> None:
    """Order, not just presence. NOT NULL before the UPDATE fails outright; the
    UPDATE before the columns exist fails too."""
    kinds = [(call[0], call[1] if call[0] != "execute" else "sql") for call in upgraded.calls]
    backfill_at = kinds.index(("execute", "sql"))
    needs_adds = [i for i, k in enumerate(kinds) if k == ("add_column", "needs")]
    alters = [i for i, k in enumerate(kinds) if k[0] == "alter_column"]

    assert needs_adds and alters
    assert max(needs_adds) < backfill_at < min(alters)


def test_the_new_need_columns_arrive_nullable_and_leave_required(
    upgraded: _RecordedOps,
) -> None:
    added = {c[2].name: c[2] for c in upgraded.calls if c[0] == "add_column" and c[1] == "needs"}
    altered = {c[2]: c[3] for c in upgraded.calls if c[0] == "alter_column"}

    assert set(added) == {"in_field_skill_count", "graduate_capability_skill_count"}
    assert all(column.nullable for column in added.values())
    assert set(altered) == set(added)
    assert all(kwargs["nullable"] is False for kwargs in altered.values())


def test_the_graduate_capability_column_defaults_to_true_for_rows_that_predate_it(
    upgraded: _RecordedOps,
) -> None:
    """Matching is_field_relevant: a skill extracted before the flag existed was
    never judged against it, and the pipeline has to read it the way it read it
    yesterday. A default of false would mark every stored skill an institutional
    activity."""
    (column,) = [c[2] for c in upgraded.calls if c[0] == "add_column" and c[1] == "skills"]

    assert column.name == "is_graduate_capability"
    assert column.nullable is False
    assert str(column.server_default.arg) == "true"


def test_the_program_scope_column_is_allowed_to_be_empty(upgraded: _RecordedOps) -> None:
    """Not writing one is the common case, and the guard turns into a no-op on
    its own when nobody does."""
    (column,) = [c[2] for c in upgraded.calls if c[0] == "add_column" and c[1] == "programs"]

    assert column.name == "scope_th"
    assert column.nullable is True


def test_all_three_tables_change_in_one_revision(upgraded: _RecordedOps) -> None:
    """The new schema field moves _EXTRACTION_CONTRACT, so shipping this makes
    every cached extraction unreachable and the corpus is re-read once. Split
    across revisions, that price is paid twice for no reduction in risk."""
    tables = {call[1] for call in upgraded.calls if call[0] == "add_column"}

    assert tables == {"programs", "skills", "needs"}


def test_the_scope_guard_revision_follows_the_llm_cache_columns(
    scope_guard: ModuleType,
) -> None:
    assert scope_guard.revision == "a3f8d61e04c7"
    assert scope_guard.down_revision == "f3a91c02b7de"


def test_the_downgrade_removes_every_column_the_upgrade_added(
    scope_guard: ModuleType, upgraded: _RecordedOps, monkeypatch: pytest.MonkeyPatch
) -> None:
    added = {(call[1], call[2].name) for call in upgraded.calls if call[0] == "add_column"}

    recorder = _RecordedOps()
    monkeypatch.setattr(scope_guard, "op", recorder)
    scope_guard.downgrade()

    assert {(call[1], call[2]) for call in recorder.calls if call[0] == "drop_column"} == added
