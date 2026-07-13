from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from langgraph.types import Command
from loguru import logger

from curriculum_agent.data.repositories import ProgramRepository, SessionRepository
from curriculum_agent.graph import AgentState
from curriculum_agent.models import SessionInfo

router = APIRouter()

_STAGE_ORDER = [
    "intake",
    "stakeholder_needs",
    "skill_extraction",
    "plo_synthesis",
    "plo_report",
]

_NODE_TO_STAGE: dict[str, str] = {
    "review_evidence": "stakeholder_needs",
    "review_clusters": "skill_extraction",
    "review_plos_node": "plo_synthesis",
    "review_plo_report": "plo_report",
}


async def _run_graph(graph, config: dict, input_, session_id: str) -> None:
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
            stage = _NODE_TO_STAGE.get(raw_node, raw_node)
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
    config = {"configurable": {"thread_id": thread_id}}
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

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": session.thread_id}}
    cmd = Command(resume={"checkpoint_status": "approved"})
    background_tasks.add_task(_run_graph, graph, config, cmd, session_id)
    return session


@router.post("/{session_id}/reject", response_model=SessionInfo)
async def reject_session(program_id: str, session_id: str) -> SessionInfo:
    repo = SessionRepository()
    session = await repo.get(session_id)
    if session is None or session.program_id != program_id:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "suspended":
        raise HTTPException(status_code=409, detail=f"Session is '{session.status}', not suspended")

    await repo.set_status(session_id, "rejected")
    # The LangGraph checkpoint thread remains suspended in the checkpointer.
    # A rejected session is terminal — start a new session (new thread_id) to retry.
    return await repo.get(session_id)
