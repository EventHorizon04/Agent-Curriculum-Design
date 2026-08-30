from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from loguru import logger

from curriculum_agent.data.repositories import ProgramRepository, SessionRepository
from curriculum_agent.graph import REVIEW_NODE_STAGE, AgentState, discard_thread
from curriculum_agent.models import SessionInfo

router = APIRouter()


async def _run_graph(
    graph: CompiledStateGraph[AgentState, None, AgentState, AgentState],
    config: RunnableConfig,
    input_: AgentState | Command[Any],
    session_id: str,
) -> None:
    """Run (or resume) the graph in a BackgroundTask.

    Opens its own DB session — never shares the request-scoped session.
    Detects interrupt vs completion via graph.aget_state().next.
    """
    repo = SessionRepository()
    try:
        await graph.ainvoke(input_, config)
        snap = await graph.aget_state(config)
        if snap.next:
            msg = "Review required"
            for task in snap.tasks:
                for intr in task.interrupts:
                    msg = str(intr.value)
                    break
            raw_node = snap.next[0] if snap.next else "unknown"
            stage = REVIEW_NODE_STAGE.get(raw_node)
            if stage is None:
                # Stored anyway — a suspended run that records no stage at all is
                # worse than one recording a name only an engineer recognises —
                # but said out loud, because the designer's rail cannot place it.
                logger.warning(
                    f"Session {session_id} suspended at node '{raw_node}', which maps to no "
                    "designer stage — add it to REVIEW_NODE_STAGE in graph.py"
                )
                stage = raw_node
            await repo.set_suspended(session_id, stage, msg)
        else:
            await repo.set_status(session_id, "completed")
    except Exception as exc:
        logger.error(f"Graph run failed for session {session_id}: {exc}")
        await repo.set_status(session_id, "failed")


@router.post("/", response_model=SessionInfo)
async def create_session(
    program_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> SessionInfo:
    program = await ProgramRepository().get(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")

    session_id = str(uuid.uuid4())
    thread_id = f"{program_id}:{session_id}"
    now = datetime.utcnow()
    session = SessionInfo(
        session_id=session_id,
        program_id=program_id,
        thread_id=thread_id,
        status="running",
        created_at=now,
        updated_at=now,
    )
    await SessionRepository().create(session)

    graph = request.app.state.graph
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    initial_state: AgentState = {
        "program_id": program_id,
        "metadata": program.model_dump(mode="json"),
    }
    background_tasks.add_task(_run_graph, graph, config, initial_state, session_id)
    return session


@router.get("/", response_model=list[SessionInfo])
async def list_sessions(program_id: str) -> list[SessionInfo]:
    return await SessionRepository().list_by_program(program_id)


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(program_id: str, session_id: str) -> SessionInfo:
    session = await SessionRepository().get(session_id)
    if session is None or session.program_id != program_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/{session_id}/approve", response_model=SessionInfo)
async def approve_session(
    program_id: str,
    session_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> SessionInfo:
    repo = SessionRepository()
    session = await repo.get(session_id)
    if session is None or session.program_id != program_id:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "suspended":
        raise HTTPException(status_code=409, detail=f"Session is '{session.status}', not suspended")

    await repo.set_status(session_id, "running")
    session = await repo.get(session_id)
    if session is None:
        # Session vanished between the status update and the re-read.
        raise HTTPException(status_code=404, detail="Session not found")

    graph = request.app.state.graph
    config: RunnableConfig = {"configurable": {"thread_id": session.thread_id}}
    cmd: Command[Any] = Command(resume={"checkpoint_status": "approved"})
    background_tasks.add_task(_run_graph, graph, config, cmd, session_id)
    return session


@router.post("/{session_id}/reject", response_model=SessionInfo)
async def reject_session(program_id: str, session_id: str, request: Request) -> SessionInfo:
    repo = SessionRepository()
    session = await repo.get(session_id)
    if session is None or session.program_id != program_id:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "suspended":
        raise HTTPException(status_code=409, detail=f"Session is '{session.status}', not suspended")

    await repo.set_status(session_id, "rejected")
    # A rejected session is terminal — retrying means a new session with a new
    # thread_id — so nothing will ever resume this thread. Its checkpoint is
    # dropped rather than left suspended for the life of the database: it holds a
    # full copy of the program's evidence, skills and Needs, and the session row
    # stays behind to record that the run happened and was rejected.
    await discard_thread(request.app.state.graph, session.thread_id)

    updated = await repo.get(session_id)
    if updated is None:
        # Session vanished between the status update and the re-read.
        raise HTTPException(status_code=404, detail="Session not found")
    return updated
