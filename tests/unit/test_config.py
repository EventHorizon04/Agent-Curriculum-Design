from __future__ import annotations

from curriculum_agent.config import Settings


def test_postgres_dsn_sync_strips_asyncpg_driver():
    s = Settings(
        postgres_dsn="postgresql+asyncpg://user:pass@localhost:5432/mydb"
    )
    assert s.postgres_dsn_sync == "postgresql://user:pass@localhost:5432/mydb"


def test_postgres_dsn_sync_unchanged_when_no_asyncpg():
    s = Settings(postgres_dsn="postgresql://user:pass@localhost:5432/mydb")
    assert s.postgres_dsn_sync == "postgresql://user:pass@localhost:5432/mydb"
