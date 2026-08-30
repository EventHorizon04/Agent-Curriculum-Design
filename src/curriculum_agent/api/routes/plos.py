from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from loguru import logger
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
    # Ids the PLO cites that no longer resolve. An empty `clusters` list on its
    # own is ambiguous — it reads as "built from no Needs", which the model
    # forbids — so name the missing ids rather than letting the UI show a
    # confident zero. Non-empty means the row outlived the Needs behind it.
    missing_need_ids: list[str] = []
    missing_evidence_ids: list[str] = []


class PLOReportResponse(BaseModel):
    """The assembled checkpoint payload from plo_report.run's `state["report"]`.

    A typed model rather than `list[PLO]` so `counts` and `needs_by_id` — the
    two fields plo_report.py assembles for the drill-down view — actually leave
    the graph through the route, instead of being computed and then discarded.
    """

    plos: list[PLO]
    counts: dict[str, int]
    needs_by_id: dict[str, Need]
    # Need ids no PLO cites: those below the MAX_CORE_PLOS cut, plus any whose
    # synthesis failed. Carried through for the same reason as `counts` — computing
    # it in the stage and dropping it at the route would hide the cap.
    needs_not_synthesized: list[str] = []


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

    clusters = [n for n in all_needs if n.need_id in need_ids]
    evidence = [e for e in all_evidence if e.evidence_id in evidence_ids]

    missing_needs = sorted(need_ids - {n.need_id for n in clusters})
    missing_evidence = sorted(evidence_ids - {e.evidence_id for e in evidence})
    if missing_needs or missing_evidence:
        logger.warning(
            f"{plo_id} cites rows that no longer exist: "
            f"{len(missing_needs)} Need(s), {len(missing_evidence)} evidence item(s) — "
            "re-run PLO synthesis to rebuild the set against the current Needs"
        )

    return PLOTrace(
        plo=plo,
        clusters=clusters,
        evidence=evidence,
        missing_need_ids=missing_needs,
        missing_evidence_ids=missing_evidence,
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
        needs_not_synthesized=report["needs_not_synthesized"],
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
    from curriculum_agent.stages.need_grouping import (  # noqa: PLC0415
        MAX_CORE_PLOS,
        MIN_NEEDS,
    )
    from curriculum_agent.stages.plo_synthesis import (  # noqa: PLC0415
        cited_need_ids,
        next_plo_id,
        plos_citing,
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
    existing = await _repo.list_by_program(program_id)

    # One outcome per Need. Every PLO citing any selected Need is replaced by this
    # merge rather than left standing beside it: this endpoint used to append, so a
    # Need ended up behind both its own outcome and the merged one, and two PLOs
    # claiming the same evidence read as two independent market demands in the
    # มคอ.2 matrix when they are one. Replacing is also what a designer means by
    # "merge" — the outcomes the merge supersedes are exactly the ones it covers.
    superseded = plos_citing(existing, body.need_ids)
    superseded_ids = {p.plo_id for p in superseded}
    surviving = [p for p in existing if p.plo_id not in superseded_ids]

    current_core = sum(1 for p in existing if not p.is_optional)
    projected_core = sum(1 for p in surviving if not p.is_optional) + (0 if is_optional else 1)

    # The 6-10 policy is a property of the stored set, not of one stage's output,
    # and a replacing merge moves the count in both directions: folding several
    # outcomes into one lowers it, merging Needs nothing cites yet raises it. Both
    # bounds are therefore checked here. Optional PLOs are outside the count, for
    # the same reason they are in synthesis.
    if projected_core > MAX_CORE_PLOS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"การรวมนี้จะทำให้มี PLO หลัก {projected_core} ข้อ เกินเพดาน "
                f"{MAX_CORE_PLOS} ข้อ เลือก Need ที่มี PLO อยู่แล้วเข้ามารวมด้วย "
                "เพื่อให้การรวมนี้แทนที่ PLO เดิมแทนที่จะเพิ่มข้อใหม่"
            ),
        )
    # Only when this merge is what takes the count below the floor. A program that
    # is already short of six — too few Needs to begin with — must not have every
    # further merge refused for a shortfall it did not cause.
    if projected_core < MIN_NEEDS and projected_core < current_core:
        raise HTTPException(
            status_code=422,
            detail=(
                f"การรวมนี้จะเหลือ PLO หลัก {projected_core} ข้อ ต่ำกว่านโยบายขั้นต่ำ "
                f"{MIN_NEEDS} ข้อ รวม Need ที่ยังไม่มี PLO ขึ้นมาเป็นข้อใหม่ก่อน "
                "แล้วจึงรวมข้อที่ซ้ำซ้อนกัน"
            ),
        )

    # A Need cited only by an outcome this merge supersedes loses its PLO and
    # returns to the pool. That is the correct outcome — it is no longer behind
    # anything — but it is not something the designer asked for, so it is named
    # rather than left to be noticed on the report page.
    released = sorted(cited_need_ids(superseded) - set(body.need_ids))
    if released:
        logger.warning(
            f"Merging {len(selected)} Need(s) supersedes {sorted(superseded_ids)}, which "
            f"leaves Need(s) {released} without an outcome — they return to the pool"
        )

    plo = await synthesize_from_needs(
        program,
        selected,
        program_id,
        {n.need_id for n in all_needs},
        # Numbered from what survives, so the merge reuses the lowest slot it is
        # about to empty instead of counting past ids that are being deleted.
        next_plo_id([p.plo_id for p in surviving], is_optional=is_optional),
        note_th=body.note_th,
    )
    if plo is None:
        # Nothing has been deleted yet: the supersede and the insert happen
        # together below, so a failed synthesis leaves the set exactly as it was.
        raise HTTPException(status_code=502, detail="สร้าง PLO ไม่สำเร็จ กรุณาลองใหม่")

    removed = await PLORepository().replace(program_id, sorted(superseded_ids), [plo])
    if removed:
        logger.info(f"Merge into {plo.plo_id} replaced {removed} PLO row(s)")
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
