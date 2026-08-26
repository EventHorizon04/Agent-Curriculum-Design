"""Find and drop checkpoint threads nothing will ever resume.

`graph.discard_thread` keeps new threads from leaking, but it only runs from the
moment a program is deleted or a session rejected. Rows written before it existed
— and any thread whose delete failed and was logged rather than raised — are
still there, each holding a full AgentState: evidence text, skills, Needs, PLOs.
This is the sweep for those.

    uv run python -m curriculum_agent.data.prune_threads            # report only
    uv run python -m curriculum_agent.data.prune_threads --delete

Reporting is the default because the report is the review step: a thread listed
here is deleted with no undo, and the classification depends on the application
tables being intact. Read the list, then pass --delete.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterable

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from loguru import logger
from sqlalchemy import select

from curriculum_agent.config import settings
from curriculum_agent.data.orm import ProgramTable, SessionTable
from curriculum_agent.data.postgres import AsyncSessionLocal

# Qualified rather than relying on search_path: the application has its own
# `checkpoints` table in the public schema, and an unqualified name here would
# read the wrong one on any connection whose search_path is not what we assume.
_STORED_THREADS_SQL = "SELECT DISTINCT thread_id FROM langgraph.checkpoints ORDER BY thread_id"

LIVE = "live"
ORPHANED = "orphaned"
REJECTED = "rejected"


def classify_threads(
    stored: Iterable[str],
    program_ids: set[str],
    session_status_by_thread: dict[str, str],
) -> dict[str, list[str]]:
    """Sort stored thread ids into live, orphaned, and rejected.

    Three kinds of thread exist. A session thread is named `{program}:{session}`
    and is live while its session row is; a program thread is named for the
    program itself (create_program runs the graph under it) and is live while
    that program exists. Anything else lost its owner — the row it belonged to
    was deleted and took the id with it.

    `rejected` is not orphaned: the session row is still there. It is listed
    separately because a rejected session is terminal by design — retrying means
    a new session under a new thread_id — so the checkpoint has no reader left
    either. Newer runs drop it at the moment of rejection; these are the ones
    that predate that.
    """
    result: dict[str, list[str]] = {LIVE: [], ORPHANED: [], REJECTED: []}
    for thread_id in stored:
        status = session_status_by_thread.get(thread_id)
        if status is not None:
            result[REJECTED if status == "rejected" else LIVE].append(thread_id)
        elif thread_id in program_ids:
            result[LIVE].append(thread_id)
        else:
            result[ORPHANED].append(thread_id)
    return result


async def stored_thread_ids() -> list[str]:
    """Every thread the checkpointer holds rows for.

    A database that has never run the graph has no such table; that is an empty
    result, not a failure.
    """
    async with await psycopg.AsyncConnection.connect(
        settings.postgres_dsn_sync, autocommit=True
    ) as conn:
        exists = await (
            await conn.execute("SELECT to_regclass('langgraph.checkpoints') IS NOT NULL")
        ).fetchone()
        if not exists or not exists[0]:
            logger.info("No langgraph.checkpoints table — nothing has been checkpointed yet")
            return []
        rows = await (await conn.execute(_STORED_THREADS_SQL)).fetchall()
    return [r[0] for r in rows]


async def application_state() -> tuple[set[str], dict[str, str]]:
    """The program ids and session threads the application still knows about."""
    async with AsyncSessionLocal() as session:
        programs = (await session.execute(select(ProgramTable.program_id))).scalars().all()
        sessions = (
            await session.execute(select(SessionTable.thread_id, SessionTable.status))
        ).all()
    return set(programs), {thread_id: status for thread_id, status in sessions}


async def prune(delete: bool) -> dict[str, list[str]]:
    """Classify every stored thread, and drop the unreachable ones when asked."""
    stored = await stored_thread_ids()
    program_ids, session_status = await application_state()
    grouped = classify_threads(stored, program_ids, session_status)

    logger.info(
        f"{len(stored)} checkpoint thread(s): {len(grouped[LIVE])} live, "
        f"{len(grouped[ORPHANED])} orphaned, {len(grouped[REJECTED])} rejected"
    )
    for label in (ORPHANED, REJECTED):
        for thread_id in grouped[label]:
            logger.info(f"  {label}: {thread_id}")

    doomed = grouped[ORPHANED] + grouped[REJECTED]
    if not doomed:
        logger.info("Nothing to prune")
        return grouped
    if not delete:
        logger.warning(f"{len(doomed)} thread(s) would be deleted — re-run with --delete")
        return grouped

    # Through the saver rather than a hand-written DELETE: the checkpointer owns
    # more than one table and knows which, and this is the same call the routes
    # make. Failures are not swallowed here the way they are in the request path
    # — a maintenance sweep that half-worked must say so.
    async with AsyncPostgresSaver.from_conn_string(settings.postgres_dsn_langgraph) as saver:
        for thread_id in doomed:
            await saver.adelete_thread(thread_id)
            logger.info(f"Deleted thread '{thread_id}'")
    logger.info(f"Pruned {len(doomed)} thread(s)")
    return grouped


def main() -> None:
    # psycopg refuses a ProactorEventLoop, which is what asyncio.run builds on
    # Windows by default. Same reason api/__main__.py names its loop factory.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(prune(delete="--delete" in sys.argv[1:]))


if __name__ == "__main__":
    main()
