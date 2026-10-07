from __future__ import annotations

from fastapi import APIRouter, HTTPException

from curriculum_agent.api import jobs
from curriculum_agent.models import JobInfo

router = APIRouter()


@router.get("/", response_model=list[JobInfo])
async def list_jobs(program_id: str, active: bool = False) -> list[JobInfo]:
    """Newest first, the latest 20. `active=true`: only running jobs."""
    rows = await jobs.JobRepository().list_by_program(program_id, active_only=active)
    return [jobs.with_label(j) for j in rows]


@router.get("/{job_id}", response_model=JobInfo)
async def get_job(program_id: str, job_id: str) -> JobInfo:
    job = await jobs.JobRepository().get(job_id)
    if job is None or job.program_id != program_id:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้")
    return jobs.with_label(job)
