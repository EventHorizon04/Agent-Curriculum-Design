from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from curriculum_agent.api.jobs import start_job_or_409, sync_writer
from curriculum_agent.data.repositories import (
    EvidenceRepository,
    NeedRepository,
    PLORepository,
    ProgramRepository,
    SkillRepository,
)
from curriculum_agent.graph import AgentState
from curriculum_agent.models import (
    DesignerNoteRequest,
    ExtractedSkill,
    JobInfo,
    Need,
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

    Refused in the order 404 / 422 / 409 (a PLO cites it) / 409 (busy). The write
    runs as a registered writer so a job or session starting mid-split answers 409.
    """
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
            detail="Need นี้ถูกใช้สร้าง PLO แล้ว — แยกก่อนสร้าง PLO หรือรันสังเคราะห์ PLO ใหม่หลังแยก",
        )
    async with sync_writer(program_id, "หลักสูตรนี้กำลังแยก Need อยู่ — รอให้เสร็จก่อน"):
        try:
            return await _repo.split(program_id, need_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ไม่พบ Need นี้") from exc


@router.get("/skills", response_model=list[ExtractedSkill])
async def list_skills(program_id: str) -> list[ExtractedSkill]:
    return await SkillRepository().list_by_program(program_id)


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


@router.post("/run", response_model=JobInfo, status_code=202)
async def run_need_pipeline(program_id: str, body: DesignerNoteRequest | None = None) -> JobInfo:
    """Both stages back to back — the first run of a program, where there are no
    skills to combine yet. Re-running one stage alone goes through the two routes
    below. Answers 202; the result (a `NeedRunResult`) arrives through
    `GET /jobs`."""
    from curriculum_agent.stages.need_combination import run as run_needs  # noqa: PLC0415
    from curriculum_agent.stages.skill_extraction import run as run_skills  # noqa: PLC0415
    from curriculum_agent.stages.skill_grouping import run as run_grouping  # noqa: PLC0415

    state = await _build_stage_state(program_id, body)

    async def work() -> NeedRunResult:
        done = await asyncio.wait_for(run_skills(state), timeout=300)
        done = await asyncio.wait_for(run_grouping(done), timeout=300)
        done = await asyncio.wait_for(run_needs(done), timeout=300)
        return NeedRunResult(
            needs=[Need.model_validate(n) for n in done.get("needs", [])],
            dropped_ungrounded_count=done.get("dropped_ungrounded_count", 0),
        )

    return await start_job_or_409(
        program_id, "needs_pipeline", {"note_th": body.note_th if body else None}, work
    )


@router.post("/skills/run", response_model=JobInfo, status_code=202)
async def run_skill_extraction(program_id: str, body: DesignerNoteRequest | None = None) -> JobInfo:
    """Re-extract skills and stop. Answers 202; the result (a `SkillRunResult`)
    arrives through `GET /jobs`.

    The stored Needs are left untouched on purpose. They will point at skill ids
    this run just replaced, which the UI surfaces as a stale banner — a designer
    who reworded evidence usually wants to read the new skills before deciding
    whether the Needs should be redrawn.
    """
    from curriculum_agent.stages.skill_extraction import run as run_skills  # noqa: PLC0415
    from curriculum_agent.stages.skill_grouping import run as run_grouping  # noqa: PLC0415

    state = await _build_stage_state(program_id, body)

    async def work() -> SkillRunResult:
        done = await asyncio.wait_for(run_skills(state), timeout=300)
        done = await asyncio.wait_for(run_grouping(done), timeout=300)
        return SkillRunResult(
            skills=[ExtractedSkill.model_validate(s) for s in done.get("extracted_skills", [])],
            dropped_ungrounded_count=done.get("dropped_ungrounded_count", 0),
        )

    return await start_job_or_409(
        program_id, "skill_extraction", {"note_th": body.note_th if body else None}, work
    )


@router.post("/combine/run", response_model=JobInfo, status_code=202)
async def run_need_combination(program_id: str, body: DesignerNoteRequest | None = None) -> JobInfo:
    """Re-cluster the skills already on record into Needs. Answers 202; the
    result (a `NeedRunResult`) arrives through `GET /jobs`.

    Reads the skill rows back from the repository instead of re-extracting: the
    expensive per-evidence LLM pass is exactly what a designer re-running this
    stage does not want repeated. The evidence corpus is not loaded at all — the
    stage groups and writes from the skills alone.
    """
    from curriculum_agent.stages.need_combination import run as run_needs  # noqa: PLC0415

    state = await _base_state(program_id, body)
    skills = await SkillRepository().list_by_program(program_id)
    if not skills:
        raise HTTPException(
            status_code=422,
            detail="ยังไม่มีทักษะที่สกัดไว้ กรุณารัน Skill Extraction ก่อน",
        )
    # No skill_groups key: need_combination loads the stored groups itself.

    async def work() -> NeedRunResult:
        done = await asyncio.wait_for(run_needs(state), timeout=300)
        return NeedRunResult(
            needs=[Need.model_validate(n) for n in done.get("needs", [])],
            dropped_ungrounded_count=done.get("dropped_ungrounded_count", 0),
        )

    return await start_job_or_409(
        program_id, "need_combination", {"note_th": body.note_th if body else None}, work
    )
