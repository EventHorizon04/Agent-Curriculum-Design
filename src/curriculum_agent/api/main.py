from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from loguru import logger

from curriculum_agent.api.routes import evidence, needs, plos, programs, sessions
from curriculum_agent.config import settings
from curriculum_agent.graph import build_graph

# psycopg3 (AsyncPostgresSaver) requires SelectorEventLoop on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting up — initialising Postgres checkpointer")

    async with await psycopg.AsyncConnection.connect(
        settings.postgres_dsn_sync, autocommit=True
    ) as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
        logger.info("Ensured 'langgraph' schema exists")

    async with AsyncPostgresSaver.from_conn_string(settings.postgres_dsn_langgraph) as saver:
        await saver.setup()
        app.state.graph = build_graph(checkpointer=saver)
        logger.info("Graph compiled with AsyncPostgresSaver")

        from curriculum_agent.llm import warmup_models

        try:
            await warmup_models()
        except Exception as exc:
            logger.warning(f"Startup warm-up failed: {exc}")
        logger.info("Model pre-warm complete")

        yield

    logger.info("Shutting down")


app = FastAPI(title="Curriculum Design Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(programs.router, prefix="/programs", tags=["programs"])
app.include_router(evidence.router, prefix="/programs/{program_id}/evidence", tags=["evidence"])
app.include_router(needs.router, prefix="/programs/{program_id}/needs", tags=["needs"])
app.include_router(plos.router, prefix="/programs/{program_id}/plos", tags=["plos"])
app.include_router(sessions.router, prefix="/programs/{program_id}/sessions", tags=["sessions"])


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
