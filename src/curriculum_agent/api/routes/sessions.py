from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from loguru import logger

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import (
    EvidenceRepository,
    ProgramRepository,
    SessionRepository,
)
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
        # The reason goes on the row, not only into the log. A stage refusing to
        # run for want of evidence, skills or Needs is a message the designer can
        # act on — it is the same precondition the stage pages answer 422 with —
        # and a bare "failed" sent them to an engineer to read the log instead.
        logger.error(f"Graph run failed for session {session_id}: {exc}")
        await repo.set_status(session_id, "failed", message=str(exc))


@router.post("/", response_model=SessionInfo)
async def create_session(
    program_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> SessionInfo:
    program = await ProgramRepository().get(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Program not found")

    # Checked before the session exists, not after. `stakeholder_needs` raises on
    # an empty corpus — deliberately, so the run dies at the stage that is
    # actually missing something rather than three stages later — but starting
    # the graph to find that out costs a session row recording a failure the
    # caller could have been told about, and a checkpoint thread that then has to
    # be cleaned up. The per-stage REST routes answer 422 on the same condition;
    # this is the graph path agreeing with them.
    if not await EvidenceRepository().list_by_program(program_id):
        raise HTTPException(
            status_code=422,
            detail="ยังไม่มี evidence สำหรับหลักสูตรนี้ — เพิ่มหลักฐานที่ขั้น Stakeholder Needs ก่อนเริ่มรัน",
        )

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


@router.delete("/{session_id}", status_code=204, dependencies=[Depends(require_api_key)])
async def delete_session(program_id: str, session_id: str, request: Request) -> None:
    """Remove one run from the program's history.

    The checkpoint thread goes with it. Nothing else can drop it afterwards: the
    thread id is recorded on this row and on nothing else, and LangGraph's
    checkpoints sit in their own schema with no foreign key back here, so a row
    deleted on its own leaves a thread holding a full copy of that run's
    evidence, skills, Needs and PLOs that no one can name any more. Dropped
    before the row for the same reason `DELETE /programs` reads its thread ids
    before the cascade.

    A `running` session is refused. Its graph task is still executing in the
    background and still writing — stage output to the repositories, status back
    to this row — so deleting it does not stop the run, it only removes the
    record that would have shown it happening and the message it would have
    failed with.
    """
    repo = SessionRepository()
    session = await repo.get(session_id)
    if session is None or session.program_id != program_id:
        raise HTTPException(status_code=404, detail="ไม่พบ session นี้")
    if session.status == "running":
        raise HTTPException(
            status_code=409,
            detail="session นี้กำลังทำงานอยู่ — รอให้จบหรือกด reject ที่ checkpoint ก่อนลบ",
        )

    await discard_thread(request.app.state.graph, session.thread_id)
    if not await repo.delete(program_id, session_id):
        # Gone between the read and the delete. The thread is dropped either way,
        # which is the part nothing else would have cleaned up.
        raise HTTPException(status_code=404, detail="ไม่พบ session นี้")
