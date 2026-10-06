from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.constants import START
from loguru import logger
from sqlalchemy.exc import IntegrityError

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.program_copy import copy_program
from curriculum_agent.data.repositories import ProgramRepository, SessionRepository
from curriculum_agent.graph import discard_thread
from curriculum_agent.models import ProgramCreateRequest, ProgramMetadata, ProgramSummary
from curriculum_agent.stages.plo_synthesis import is_synthesis_running

router = APIRouter()

_MAX_ID_ATTEMPTS = 5


def _slugify(text: str) -> str:
    """Lowercase ASCII slug; non-alphanumeric runs become '-'. Empty -> 'program'."""
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "program"


async def _generate_program_id(field: str, repo: ProgramRepository) -> str:
    """Slug from the field of study, with -2, -3, ... suffix on collision.

    Intake stopped collecting a program name, so the field is what is left to
    build a readable id from. A Thai field slugs to "program" (_slugify keeps
    ASCII only) and the suffix carries the distinction — unlovely, but stable
    and collision-free, which is what the id has to be.
    """
    base = _slugify(field)
    candidate = base
    n = 2
    while await repo.exists(candidate):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


@router.post("/", response_model=ProgramMetadata, dependencies=[Depends(require_api_key)])
async def create_program(req: ProgramCreateRequest, request: Request) -> ProgramMetadata:
    repo = ProgramRepository()
    metadata: ProgramMetadata | None = None
    for _ in range(_MAX_ID_ATTEMPTS):
        program_id = await _generate_program_id(req.field, repo)
        candidate = ProgramMetadata(program_id=program_id, **req.model_dump())
        try:
            await repo.insert(candidate)
        except IntegrityError:
            # Lost a concurrent-create race; the next _generate_program_id
            # call sees the winner's row and picks the next suffix.
            logger.warning(f"program_id '{program_id}' taken concurrently, retrying")
            continue
        metadata = candidate
        break
    if metadata is None:
        raise HTTPException(status_code=409, detail="สร้างรหัสหลักสูตรไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")
    # Seed the program's own thread with its metadata. `aupdate_state`, not
    # `ainvoke`: invoking runs the graph from its entry point, so creating a
    # program walked into `stakeholder_needs`, which refuses a program with no
    # evidence — and a program being created never has any. The row was already
    # inserted by then, so every attempt left a program behind and answered 500,
    # which is how one field ends up as program, program-2, program-3. Writing
    # the state is what was wanted; running the pipeline is POST /sessions.
    graph = request.app.state.graph
    await graph.aupdate_state(
        {"configurable": {"thread_id": metadata.program_id}},
        {"program_id": metadata.program_id, "metadata": metadata.model_dump(mode="json")},
        as_node=START,
    )
    return metadata


async def _generate_copy_id(source_id: str, repo: ProgramRepository) -> str:
    """`{source}-run-{n}`, smallest n >= 1 not taken. A copy of a copy nests
    (`program-2-run-1-run-1`) — accepted, the rule stays one line."""
    n = 1
    while await repo.exists(f"{source_id}-run-{n}"):
        n += 1
    return f"{source_id}-run-{n}"


@router.post(
    "/{program_id}/copy",
    response_model=ProgramMetadata,
    dependencies=[Depends(require_api_key)],
)
async def copy_program_route(program_id: str, request: Request) -> ProgramMetadata:
    """Copy a program with everything it owns, so one run survives the next.

    Refused while the source has a synthesis run in flight: synthesis deletes
    and then inserts, so a copy taken mid-run would hold half a set.
    need_combination has no such guard, so a copy taken during it is not
    prevented.
    """
    repo = ProgramRepository()
    if not await repo.exists(program_id):
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")
    if is_synthesis_running(program_id):
        raise HTTPException(
            status_code=409,
            detail="หลักสูตรนี้กำลังสังเคราะห์ PLO อยู่ — รอให้เสร็จก่อนจึงคัดลอก",
        )

    for _ in range(_MAX_ID_ATTEMPTS):
        new_id = await _generate_copy_id(program_id, repo)
        try:
            copied = await copy_program(program_id, new_id)
        except IntegrityError:
            # Only an id collision is worth retrying under the next id; any
            # other IntegrityError (e.g. a stale FK inside the copy) would
            # just fail the same way again, and retrying it into a 409 would
            # misreport it as a name clash.
            if not await repo.exists(new_id):
                raise
            logger.warning(f"program_id '{new_id}' taken concurrently, retrying")
            continue
        if not copied:
            raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")
        metadata = await repo.get(new_id)
        if metadata is None:  # pragma: no cover - just committed
            raise HTTPException(status_code=500, detail="คัดลอกแล้วแต่อ่านกลับไม่ได้")
        # Seed the copy's own thread the way create_program does, so every path
        # that works on a new program works on a copy.
        graph = request.app.state.graph
        await graph.aupdate_state(
            {"configurable": {"thread_id": new_id}},
            {"program_id": new_id, "metadata": metadata.model_dump(mode="json")},
            as_node=START,
        )
        return metadata
    raise HTTPException(status_code=409, detail="สร้างรหัสสำเนาไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")


@router.get("/", response_model=list[ProgramSummary])
async def list_programs() -> list[ProgramSummary]:
    """Program history: all programs with their latest pipeline state."""
    repo = ProgramRepository()
    return await repo.list_all()


@router.get("/{program_id}", response_model=ProgramMetadata)
async def get_program(program_id: str) -> ProgramMetadata:
    repo = ProgramRepository()
    result = await repo.get(program_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Program not found")
    return result


@router.put(
    "/{program_id}", response_model=ProgramMetadata, dependencies=[Depends(require_api_key)]
)
async def update_program(
    program_id: str, req: ProgramCreateRequest, request: Request
) -> ProgramMetadata:
    """Replace a program's metadata, keeping its id and its creation time.

    The id never moves, even when `field` — the thing it was slugged from — does.
    Every evidence item, skill, Need and PLO carries it as a foreign key, and so
    does the LangGraph thread holding any suspended checkpoint; renaming it would
    orphan all of them to make one string read better. An id that no longer
    matches the field it came from is the smaller wrong.

    Two of these fields reach the extraction cache key (`field`, `scope_th`), so
    changing either means the program's existing skills were judged against a
    question that is no longer being asked. The route does not re-run anything —
    every stage boundary is the designer's to cross — but it says so in the
    response.
    """
    repo = ProgramRepository()
    existing = await repo.get(program_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")

    updated = ProgramMetadata(
        program_id=program_id,
        created_at=existing.created_at,
        # req is a ProgramCreateRequest — it has no copied_from field — so the
        # existing value has to be carried over explicitly or a PUT would erase
        # which program this one was copied from.
        copied_from=existing.copied_from,
        **req.model_dump(),
    )
    await repo.upsert(updated)

    if (req.field, req.scope_th) != (existing.field, existing.scope_th):
        logger.info(
            f"Program '{program_id}': field or scope changed — stored skills were "
            "extracted under the previous values; re-run skill extraction to refresh them"
        )

    # Keep the checkpoint's copy of the metadata in step with the row. A thread
    # suspended mid-pipeline carries its own snapshot of AgentState, and a stage
    # resuming from it would otherwise read the old field.
    #
    # `aupdate_state` writes that snapshot. `ainvoke` ran the graph instead, so
    # editing a field re-ran stage 1 against the stored evidence on the way to
    # the next interrupt — or, for a program with no evidence, answered 500. The
    # docstring above already said this route re-runs nothing; now it does not.
    graph = request.app.state.graph
    await graph.aupdate_state(
        {"configurable": {"thread_id": program_id}},
        {"program_id": program_id, "metadata": updated.model_dump(mode="json")},
        as_node=START,
    )
    return updated


@router.delete("/{program_id}", status_code=204, dependencies=[Depends(require_api_key)])
async def delete_program(program_id: str, request: Request) -> None:
    repo = ProgramRepository()
    # Read the thread ids before the cascade, which deletes the session rows they
    # are recorded on. A checkpoint thread nobody has the id of can never be
    # found again, and it still holds that program's evidence and outcomes.
    threads = [s.thread_id for s in await SessionRepository().list_by_program(program_id)]

    deleted = await repo.delete_cascade(program_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")

    # program_id is a thread in its own right: create_program runs the graph
    # under it, so the thread exists even for a program no session ever ran on.
    graph = request.app.state.graph
    for thread_id in dict.fromkeys([program_id, *threads]):
        await discard_thread(graph, thread_id)
