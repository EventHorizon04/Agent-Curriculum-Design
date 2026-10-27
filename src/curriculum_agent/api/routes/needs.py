from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from curriculum_agent.api.jobs import JobConflict, start_job, start_job_or_409, sync_writer
from curriculum_agent.data.repositories import (
    EvidenceRepository,
    NeedRepository,
    PLORepository,
    ProgramRepository,
    SkillGroupRepository,
    SkillRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.models import (
    DesignerNoteRequest,
    ExtractedSkill,
    JobInfo,
    Need,
    SkillGroup,
    StakeholderEvidence,
)

router = APIRouter()
_repo = NeedRepository()


class NeedTrace(BaseModel):
    need: Need
    skills: list[ExtractedSkill]
    evidence: list[StakeholderEvidence]


class NeedRunResult(BaseModel):
    """The `result` of a needs_pipeline or need_combination job.

    The count is a property of the run, not of any stored row, so it travels in
    the result rather than being re-derivable from the database later.
    """

    needs: list[Need]
    dropped_ungrounded_count: int


class SkillRunResult(BaseModel):
    """The `result` of a skill_extraction job.

    Skills rather than Needs, because this route deliberately stops before
    need_combination: the stored Needs are left exactly as they were.
    """

    skills: list[ExtractedSkill]
    dropped_ungrounded_count: int


@router.get("/", response_model=list[Need])
async def list_needs(program_id: str, active_only: bool = False) -> list[Need]:
    """Every stored Need, or with `active_only` just the ones downstream stages
    read (the merged Needs and the never-merged ones, not the folded originals)."""
    if active_only:
        return await _repo.list_active_by_program(program_id)
    return await _repo.list_by_program(program_id)


@router.post("/{need_id}/split", response_model=list[Need])
async def split_need(program_id: str, need_id: str) -> list[Need]:
    """Undo a merge at the Need checkpoint: drop the merged Need, free its originals.

    Refused in the order 409 (busy, from `sync_writer`) / 404 / 422 / 409 (a PLO
    cites it). Every read runs inside the writer, so what was checked is what is
    split; the registration lets a job or session starting mid-split answer 409.
    """
    async with sync_writer(program_id, "หลักสูตรนี้กำลังแยก Need อยู่ — รอให้เสร็จก่อน"):
        needs = await _repo.list_by_program(program_id)
        need = next((n for n in needs if n.need_id == need_id), None)
        if need is None:
            raise HTTPException(status_code=404, detail="ไม่พบ Need นี้")
        if not need.is_merged:
            raise HTTPException(status_code=422, detail="Need นี้ไม่ได้มาจากการรวม จึงแยกไม่ได้")
        plos = await PLORepository().list_by_program(program_id)
        if any(need_id in p.source_need_ids for p in plos):
            raise HTTPException(
                status_code=409,
                detail=("Need นี้ถูกใช้สร้าง PLO แล้ว — แยกก่อนสร้าง PLO หรือรันสังเคราะห์ PLO ใหม่หลังแยก"),
            )
        try:
            return await _repo.split(program_id, need_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ไม่พบ Need นี้") from exc


@router.get("/skills", response_model=list[ExtractedSkill])
async def list_skills(program_id: str) -> list[ExtractedSkill]:
    return await SkillRepository().list_by_program(program_id)


@router.get("/skill-groups", response_model=list[SkillGroup])
async def list_skill_groups(program_id: str) -> list[SkillGroup]:
    """Agent 1's output as stored: the KSEC-bucketed skill groups Agent 2 reads."""
    return await SkillGroupRepository().list_by_program(program_id)


@router.get("/{need_id}/trace", response_model=NeedTrace)
async def get_need_trace(program_id: str, need_id: str) -> NeedTrace:
    needs = await _repo.list_by_program(program_id)
    need = next((n for n in needs if n.need_id == need_id), None)
    if need is None:
        raise HTTPException(status_code=404, detail="Need not found")

    all_evidence, need_skills = await asyncio.gather(
        EvidenceRepository().list_by_program(program_id),
        SkillRepository().list_by_ids(need.member_skill_ids),
    )

    evidence_ids = set(need.source_evidence_ids)
    need_evidence = [e for e in all_evidence if e.evidence_id in evidence_ids]

    return NeedTrace(
        need=need,
        skills=need_skills,
        evidence=need_evidence,
    )


async def _base_state(program_id: str, body: DesignerNoteRequest | None) -> AgentState:
    """Program metadata plus the designer's note — what every run entry point needs.

    Both stages accept the note: skill_extraction uses it while extracting,
    need_combination while writing each Need's sentence.
    """
    metadata = await ProgramRepository().get(program_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Program not found")

    state: AgentState = {
        "program_id": program_id,
        "metadata": metadata.model_dump(mode="json"),
    }
    # Set only when there is a note: AgentState is total=False, so an absent key
    # reads as None through .get and no empty string is stored.
    if body is not None and body.note_th:
        state["designer_note"] = body.note_th
    return state


async def _build_stage_state(program_id: str, body: DesignerNoteRequest | None) -> AgentState:
    """Base state plus the evidence corpus, for the routes that extract skills.

    need_combination no longer takes this path: it reads nothing but the skills,
    so requiring evidence there would be a precondition the stage does not have.
    """
    state = await _base_state(program_id, body)

    evidence_items = await EvidenceRepository().list_by_program(program_id)
    if not evidence_items:
        raise HTTPException(
            status_code=422,
            detail="ไม่มี evidence สำหรับโปรแกรมนี้ กรุณาเพิ่ม evidence ก่อน",
        )
    state["classified_evidence"] = [e.model_dump(mode="json") for e in evidence_items]
    return state


def _skill_work(state: AgentState) -> Callable[[], Awaitable[SkillRunResult]]:
    """Agent 1: extraction, then grouping, each under its own 300 s budget."""
    from curriculum_agent.stages.skill_extraction import run as run_skills  # noqa: PLC0415
    from curriculum_agent.stages.skill_grouping import run as run_grouping  # noqa: PLC0415

    async def work() -> SkillRunResult:
        done = await asyncio.wait_for(run_skills(state), timeout=300)
        done = await asyncio.wait_for(run_grouping(done), timeout=300)
        return SkillRunResult(
            skills=[ExtractedSkill.model_validate(s) for s in done.get("extracted_skills", [])],
            dropped_ungrounded_count=done.get("dropped_ungrounded_count", 0),
        )

    return work


async def _start_need_job(
    program_id: str,
    body: DesignerNoteRequest | None,
    *,
    or_409: bool,
    state: AgentState | None = None,
) -> JobInfo:
    """Agent 2 as its own job. Its state is built from storage when the job
    starts (or handed in by a caller that already built it for its own 404): it is
    the same job a `/combine/run` re-run would be, not a continuation of Agent 1's
    in-memory state."""
    from curriculum_agent.stages.need_combination import run as run_needs  # noqa: PLC0415

    if state is None:
        state = await _base_state(program_id, body)
    job_state = state

    async def work() -> NeedRunResult:
        done = await asyncio.wait_for(run_needs(job_state), timeout=300)
        # The stage returns the originals too, marked `merged_into`; the result is
        # the Needs downstream stages read, or a client's count is inflated.
        active = [
            n
            for n in (Need.model_validate(raw) for raw in done.get("needs", []))
            if n.merged_into is None
        ]
        return NeedRunResult(
            needs=active,
            dropped_ungrounded_count=done.get("dropped_ungrounded_count", 0),
        )

    params = {"note_th": body.note_th if body else None}
    starter = start_job_or_409 if or_409 else start_job
    return await starter(program_id, "need_combination", params, work)


@router.post("/run", response_model=JobInfo, status_code=202)
async def run_need_pipeline(program_id: str, body: DesignerNoteRequest | None = None) -> JobInfo:
    """Agent 1 then Agent 2, as two chained jobs: the first run of a program.

    Answers 202 with the `skill_extraction` job (result: `SkillRunResult`). When
    it succeeds, the `need_combination` job (`NeedRunResult`) starts by itself; if
    another writer slipped in between, that start is logged and the skill job
    stays succeeded. Re-running one stage alone goes through the two routes below.
    """
    state = await _build_stage_state(program_id, body)

    async def chain() -> None:
        try:
            await _start_need_job(program_id, body, or_409=False)
        except JobConflict as exc:
            logger.warning(f"need_combination not chained for {program_id}: {exc.detail_th}")

    return await start_job_or_409(
        program_id,
        "skill_extraction",
        {"note_th": body.note_th if body else None},
        _skill_work(state),
        on_success=chain,
    )


@router.post("/skills/run", response_model=JobInfo, status_code=202)
async def run_skill_extraction(program_id: str, body: DesignerNoteRequest | None = None) -> JobInfo:
    """Agent 1 alone: extract skills, group them, and stop. Answers 202; the
    result (a `SkillRunResult`) arrives through `GET /jobs`.

    The stored Needs are left untouched on purpose. They will point at skill ids
    this run just replaced, which the UI surfaces as a stale banner — a designer
    who reworded evidence usually wants to read the new skills before deciding
    whether the Needs should be redrawn.
    """
    state = await _build_stage_state(program_id, body)
    return await start_job_or_409(
        program_id,
        "skill_extraction",
        {"note_th": body.note_th if body else None},
        _skill_work(state),
    )


@router.post("/combine/run", response_model=JobInfo, status_code=202)
async def run_need_combination(program_id: str, body: DesignerNoteRequest | None = None) -> JobInfo:
    """Agent 2 alone: turn the stored skill groups into Needs. Answers 202; the
    result (a `NeedRunResult`) arrives through `GET /jobs`.

    Reads the stored skills and groups instead of re-extracting: the expensive
    per-evidence LLM pass is exactly what a designer re-running this stage does
    not want repeated. The evidence corpus is not loaded at all.
    """
    state = await _base_state(program_id, body)  # 404 for an unknown program
    if not await SkillRepository().list_by_program(program_id):
        raise HTTPException(
            status_code=422,
            detail="ยังไม่มีทักษะที่สกัดไว้ กรุณารัน Skill Extraction ก่อน",
        )
    if not await SkillGroupRepository().list_by_program(program_id):
        raise HTTPException(status_code=422, detail="ยังไม่มีกลุ่มทักษะ กรุณารันสกัดทักษะใหม่ก่อน")
    return await _start_need_job(program_id, body, or_409=True, state=state)
