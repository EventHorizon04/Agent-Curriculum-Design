from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from curriculum_agent.api.deps import require_api_key
from curriculum_agent.data.repositories import (
    EvidenceRepository,
    NeedRepository,
    PLORepository,
    ProgramRepository,
)
from curriculum_agent.exporters.excel_matrix import export_matrix_xlsx
from curriculum_agent.graph import AgentState
from curriculum_agent.models import PLO, DesignerNoteRequest, Need, StakeholderEvidence

router = APIRouter()
_repo = PLORepository()


class PLOTrace(BaseModel):
    plo: PLO
    clusters: list[Need]
    evidence: list[StakeholderEvidence]


class PLOReportResponse(BaseModel):
    """The assembled checkpoint payload from plo_report.run's `state["report"]`.

    A typed model rather than `list[PLO]` so `counts` and `needs_by_id` — the
    two fields plo_report.py assembles for the drill-down view — actually leave
    the graph through the route, instead of being computed and then discarded.
    """

    plos: list[PLO]
    counts: dict[str, int]
    needs_by_id: dict[str, Need]


@router.get("/", response_model=list[PLO])
async def list_plos(program_id: str) -> list[PLO]:
    return await _repo.list_by_program(program_id)


# Declared before the `/{plo_id}/...` routes so the literal path wins the match
# and no request for an export is read as a PLO id.
@router.get("/export/matrix.xlsx")
async def export_plo_matrix(program_id: str) -> Response:
    """Download the PLO set as an Excel workbook.

    The Needs are loaded alongside the PLOs because the competency domain lives on
    the Need — a PLO carries no KSEC tag of its own.
    """
    plos = await _repo.list_by_program(program_id)
    if not plos:
        raise HTTPException(
            status_code=422,
            detail="ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน",
        )

    needs = await NeedRepository().list_by_program(program_id)
    payload = export_matrix_xlsx(plos, {n.need_id: n for n in needs})

    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="plo-matrix-{program_id}.xlsx"'},
    )


@router.get("/export/checo")
async def export_plo_checo(program_id: str) -> dict[str, Any]:
    """CHECO 1.6 export — not implemented yet.

    `exporters/checo.py` is a stub that raises NotImplementedError, so this
    answers 501 rather than letting that surface as a 500 the designer cannot act
    on. The route exists now so the UI and the contract are settled; filling in
    the template population is separate work.
    """
    raise HTTPException(
        status_code=501,
        detail="ส่งออก CHECO ยังไม่พร้อมใช้งาน — อยู่ระหว่างพัฒนา",
    )


@router.get("/export/mko2")
async def export_plo_mko2(program_id: str) -> dict[str, Any]:
    """มคอ.2 export — not implemented yet. Same reasoning as the CHECO route."""
    raise HTTPException(
        status_code=501,
        detail="ส่งออก มคอ.2 ยังไม่พร้อมใช้งาน — อยู่ระหว่างพัฒนา",
    )


@router.get("/{plo_id}/trace", response_model=PLOTrace)
async def get_plo_trace(program_id: str, plo_id: str) -> PLOTrace:
    plos = await _repo.list_by_program(program_id)
    plo = next((p for p in plos if p.plo_id == plo_id), None)
    if plo is None:
        raise HTTPException(status_code=404, detail="PLO not found")

    need_ids = set(plo.source_need_ids)
    evidence_ids = set(plo.source_evidence_ids)

    all_needs = await NeedRepository().list_by_program(program_id)
    all_evidence = await EvidenceRepository().list_by_program(program_id)

    return PLOTrace(
        plo=plo,
        clusters=[n for n in all_needs if n.need_id in need_ids],
        evidence=[e for e in all_evidence if e.evidence_id in evidence_ids],
    )


@router.post("/run", response_model=list[PLO])
async def run_plo_synthesis(program_id: str, body: DesignerNoteRequest | None = None) -> list[PLO]:
    from curriculum_agent.stages.plo_synthesis import run  # noqa: PLC0415

    metadata = await ProgramRepository().get(program_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Program not found")

    needs = await NeedRepository().list_by_program(program_id)
    if not needs:
        raise HTTPException(
            status_code=422,
            detail="ไม่มี Needs สำหรับโปรแกรมนี้ กรุณารัน Need Combination ก่อน",
        )

    state: AgentState = {
        "program_id": program_id,
        "metadata": metadata.model_dump(mode="json"),
        "needs": [n.model_dump(mode="json") for n in needs],
    }
    if body is not None and body.note_th:
        state["designer_note"] = body.note_th

    result_state = await run(state)
    return [PLO.model_validate(p) for p in result_state.get("plos", [])]


@router.post("/report/run", response_model=PLOReportResponse)
async def run_plo_report(program_id: str) -> PLOReportResponse:
    from curriculum_agent.stages.plo_report import run  # noqa: PLC0415

    plos = await _repo.list_by_program(program_id)
    if not plos:
        raise HTTPException(
            status_code=422,
            detail="ยังไม่มี PLO สำหรับโปรแกรมนี้ กรุณารัน PLO Synthesis ก่อน",
        )

    state: AgentState = {
        "program_id": program_id,
        "plos": [p.model_dump(mode="json") for p in plos],
    }
    result_state = await run(state)
    report = result_state["report"]
    return PLOReportResponse(
        plos=[PLO.model_validate(p) for p in report["plos"]],
        counts=report["counts"],
        needs_by_id={k: Need.model_validate(v) for k, v in report["needs_by_id"].items()},
    )


class MergeNeedsRequest(DesignerNoteRequest):
    """Designer-selected Needs to fuse into one PLO, plus the optional note.

    Inherits `note_th` and its normalisation rather than restating them, so the
    500-character limit and the blank-is-absent rule cannot drift between
    endpoints.
    """

    need_ids: list[str] = Field(min_length=2)


@router.post("/from-needs", response_model=PLO)
async def create_plo_from_needs(program_id: str, body: MergeNeedsRequest) -> PLO:
    """Synthesize one PLO covering several designer-selected Needs.

    Program is looked up first: a missing program is a 404, not a 422 blaming
    the Needs. Need ids are validated only after the program exists.
    """
    from curriculum_agent.stages.plo_synthesis import (  # noqa: PLC0415
        next_plo_id,
        synthesize_from_needs,
    )

    program = await ProgramRepository().get(program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="ไม่พบหลักสูตรนี้")

    all_needs = await NeedRepository().list_by_program(program_id)
    by_id = {n.need_id: n for n in all_needs}
    missing = [nid for nid in body.need_ids if nid not in by_id]
    if missing:
        raise HTTPException(status_code=422, detail=f"ไม่พบ Need: {', '.join(missing)}")

    selected = [by_id[nid] for nid in body.need_ids]
    # A merged outcome is supplementary only when every Need feeding it is, and it
    # takes the next free number in that series — plo_id is the primary key and the
    # repository upserts, so reusing one would overwrite an existing outcome.
    is_optional = all(n.is_optional for n in selected)
    existing_ids = [p.plo_id for p in await _repo.list_by_program(program_id)]
    plo = await synthesize_from_needs(
        program,
        selected,
        program_id,
        {n.need_id for n in all_needs},
        next_plo_id(existing_ids, is_optional=is_optional),
        note_th=body.note_th,
    )
    if plo is None:
        raise HTTPException(status_code=502, detail="สร้าง PLO ไม่สำเร็จ กรุณาลองใหม่")

    await PLORepository().bulk_insert([plo])
    return plo


@router.put("/{plo_id}", response_model=PLO, dependencies=[Depends(require_api_key)])
async def update_plo(program_id: str, plo_id: str, plo: PLO) -> PLO:
    existing = await _repo.list_by_program(program_id)
    match = next((p for p in existing if p.plo_id == plo_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="PLO not found")

    update_fields: dict[str, object] = {"version": match.version + 1, "program_id": program_id}
    updated = plo.model_copy(update=update_fields)
    await _repo.bulk_insert([updated])
    return updated
