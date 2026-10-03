"""A PLO's identity is (program_id, plo_id), not plo_id alone.

`plo_id` (PLO1..PLOn, OPT1..OPTn) is a per-program label, the same strings in
every program. With plo_id alone as the table's primary key,
`PLORepository.bulk_insert` and `.replace` resolved an upsert target with
`session.get(PLOTable, plo.plo_id)` — looking at plo_id only — then
`setattr`'d every column including `program_id`. A second program's PLO1
synthesis run found the *first* program's PLO1 row and overwrote it in place,
including relabelling it onto the second program's program_id. No error was
ever raised; the first program silently lost the row.

Three layers are covered here:
  - the ORM metadata actually declares a composite primary key;
  - the repository asks `session.get` for the composite identity, not plo_id
    alone (mocked session — this repo has no real-DB test fixture for
    repositories; see the other PLORepository tests for the same pattern);
  - the migration's guards and primary-key operations are what they claim to
    be, read as a module and run against a recording stand-in for `op` (same
    approach as test_migration_backfill.py's scope_guard fixture).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from curriculum_agent.data.orm import PLOTable
from curriculum_agent.data.repositories import PLORepository
from curriculum_agent.models import PLO, BloomLevel, SMARTCheck

SMART_PASS = SMARTCheck(specific=True, measurable=True, achievable=True, relevant=True, timely=True)


def _plo(program_id: str, plo_id: str = "PLO1") -> PLO:
    return PLO(
        plo_id=plo_id,
        program_id=program_id,
        statement_th="วิเคราะห์ระบบงานเพื่อเสนอแนวทางแก้ปัญหาได้",
        bloom_level=BloomLevel.ANALYZE,
        action_verb_th="วิเคราะห์",
        smart_check=SMART_PASS,
        source_need_ids=["N1"],
        source_evidence_ids=["E1"],
        rationale_th="เหตุผล",
    )


# --------------------------- ORM metadata ---------------------------


def test_plos_primary_key_is_program_id_and_plo_id() -> None:
    """Pins the fix at the schema level. Reverting PLOTable.plo_id back to a
    lone `primary_key=True` column must fail this test."""
    pk_columns = {c.name for c in PLOTable.__table__.primary_key.columns}
    assert pk_columns == {"program_id", "plo_id"}


# --------------------------- repository identity ---------------------------


def _fake_session_ctx(get_mock: AsyncMock) -> MagicMock:
    session = AsyncMock()
    session.get = get_mock
    session.add = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def test_bulk_insert_looks_up_the_composite_identity() -> None:
    """Reverting this session.get back to `plo.plo_id` alone must fail here:
    the recorded identity would then be a bare string with no program_id in
    it at all."""
    get_mock = AsyncMock(return_value=None)
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_fake_session_ctx(get_mock),
    ):
        await PLORepository().bulk_insert([_plo("program-a", "PLO1")])

    get_mock.assert_awaited_once()
    (table_arg, identity_arg) = get_mock.await_args.args
    assert table_arg is PLOTable
    assert identity_arg == {"program_id": "program-a", "plo_id": "PLO1"}


async def test_replace_looks_up_the_composite_identity() -> None:
    get_mock = AsyncMock(return_value=None)
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_fake_session_ctx(get_mock),
    ):
        await PLORepository().replace("program-b", [], [_plo("program-b", "PLO1")])

    get_mock.assert_awaited_once()
    (table_arg, identity_arg) = get_mock.await_args.args
    assert table_arg is PLOTable
    assert identity_arg == {"program_id": "program-b", "plo_id": "PLO1"}


async def test_two_programs_sharing_a_plo_id_are_two_distinct_lookups() -> None:
    """The scenario the bug produced: two programs each writing their own
    PLO1. The identity passed to session.get must differ between them, or a
    mocked `get` returning "found" for one would be mistaken for the other."""
    get_mock = AsyncMock(return_value=None)
    with patch(
        "curriculum_agent.data.repositories.AsyncSessionLocal",
        return_value=_fake_session_ctx(get_mock),
    ):
        await PLORepository().bulk_insert([_plo("program-a", "PLO1")])
        await PLORepository().bulk_insert([_plo("program-b", "PLO1")])

    identities = [call.args[1] for call in get_mock.await_args_list]
    assert identities == [
        {"program_id": "program-a", "plo_id": "PLO1"},
        {"program_id": "program-b", "plo_id": "PLO1"},
    ]
    assert identities[0] != identities[1]


# --------------------------- migration ---------------------------


class _RecordedOps:
    """Stands in for alembic's `op` so upgrade()/downgrade() can run and be
    read back without a database — same shape as test_migration_backfill.py's
    _RecordedOps, extended with the constraint calls this migration makes."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def execute(self, statement: str) -> None:
        self.calls.append(("execute", statement))

    def alter_column(self, table: str, column: str, **kwargs: object) -> None:
        self.calls.append(("alter_column", table, column, kwargs))

    def drop_constraint(self, name: str, table_name: str, **kwargs: object) -> None:
        self.calls.append(("drop_constraint", name, table_name, kwargs))

    def create_primary_key(self, name: str, table_name: str, columns: list[str]) -> None:
        self.calls.append(("create_primary_key", name, table_name, columns))


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    path = next(Path("migrations/versions").glob("*_plos_composite_primary_key.py"))
    spec = importlib.util.spec_from_file_location("plo_pk_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_follows_the_current_head(migration: ModuleType) -> None:
    assert migration.down_revision == "c5a82f3e6b19"


def test_upgrade_creates_the_composite_key_on_program_id_then_plo_id(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RecordedOps()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()

    creates = [c for c in recorder.calls if c[0] == "create_primary_key"]
    assert len(creates) == 1
    _, name, table, columns = creates[0]
    assert table == "plos"
    assert columns == ["program_id", "plo_id"]


def test_upgrade_drops_the_old_single_column_key_by_its_real_name(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """aa1e44fd1a46 gave the original PrimaryKeyConstraint no explicit name, so
    Postgres assigned the default `<table>_pkey`."""
    recorder = _RecordedOps()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()

    drops = [c for c in recorder.calls if c[0] == "drop_constraint"]
    assert len(drops) == 1
    _, name, table, kwargs = drops[0]
    assert name == "plos_pkey"
    assert table == "plos"
    assert kwargs.get("type_") == "primary"


def test_upgrade_order_is_guard_then_not_null_then_drop_then_create(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping the PK before the NOT NULL guard has run would let a NULL
    program_id through into a primary key column."""
    recorder = _RecordedOps()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()

    kinds = [c[0] for c in recorder.calls]
    assert kinds == ["execute", "alter_column", "drop_constraint", "create_primary_key"]


def test_upgrade_guard_refuses_on_a_null_program_id_not_on_a_count_of_zero(
    migration: ModuleType,
) -> None:
    sql = migration.REFUSE_NULL_PROGRAM_ID
    assert "program_id IS NULL" in sql
    assert "RAISE EXCEPTION" in sql
    assert "bad_count > 0" in sql


def test_downgrade_guard_refuses_on_a_plo_id_shared_by_two_programs(
    migration: ModuleType,
) -> None:
    sql = migration.REFUSE_SHARED_PLO_ID
    assert "GROUP BY plo_id" in sql
    assert "count(DISTINCT program_id) > 1" in sql
    assert "RAISE EXCEPTION" in sql


def test_downgrade_restores_the_single_column_key(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RecordedOps()
    monkeypatch.setattr(migration, "op", recorder)
    migration.downgrade()

    kinds = [c[0] for c in recorder.calls]
    assert kinds == ["execute", "drop_constraint", "create_primary_key"]
    _, name, table, columns = recorder.calls[-1]
    assert table == "plos"
    assert columns == ["plo_id"]


def test_downgrade_never_deletes_a_row(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither guard SQL nor either op call in downgrade may contain a DELETE —
    the fix is "refuse", not "pick a survivor"."""
    recorder = _RecordedOps()
    monkeypatch.setattr(migration, "op", recorder)
    migration.downgrade()

    for call in recorder.calls:
        if call[0] == "execute":
            assert "DELETE" not in call[1].upper()
