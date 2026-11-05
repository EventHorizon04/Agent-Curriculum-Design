"""Draft one PLO from designer-chosen Needs and swap it in for the ones it replaces.

The core of `POST /plos/from-needs`, lifted out of the route so a second caller
(the review send-back) runs the very same checks, bounds and replace. It takes no
lock — see `redraft_from_needs` — and imports nothing from `api`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from loguru import logger

from curriculum_agent.data.repositories import (
    NeedRepository,
    PLOChangedDuringRedraft,
    PLORepository,
)
from curriculum_agent.models import PLO, FeedbackAction, Need, ProgramMetadata

REASON_CHANGED_DURING_REDRAFT = "PLO นี้ถูกแก้ระหว่างร่างใหม่ — ไม่เขียนทับ"


class RedraftRefused(Exception):
    """The request cannot be honoured; nothing was written. `status` is 422, or 409
    when a PLO it would replace was changed while the draft was being written."""

    def __init__(self, status: int, detail_th: str) -> None:
        super().__init__(detail_th)
        self.status = status
        self.detail_th = detail_th


class RedraftFailed(Exception):
    """The draft came back empty; nothing was written."""


def _need_refusal(all_needs: Sequence[Need], need_ids: Sequence[str]) -> str | None:
    """The checks on the selected Needs alone, which need no PLO read."""
    from curriculum_agent.stages.need_grouping import is_unwritten_need  # noqa: PLC0415

    by_id = {n.need_id: n for n in all_needs}
    missing = [nid for nid in need_ids if nid not in by_id]
    if missing:
        return f"ไม่พบ Need: {', '.join(missing)}"

    selected = [by_id[nid] for nid in need_ids]

    # A Need folded into a merged one is represented by that Need; picking the
    # original would put one demand behind two outcomes. Checked after the
    # unknown-id test so a merged-away id answers this text, not "not found".
    if any(n.merged_into is not None for n in selected):
        return "Need นี้ถูกรวมเข้ากับ Need อื่นแล้ว — เลือก Need ที่รวมแล้วแทน"

    # An excluded Need was taken out of the working set by the designer; it comes
    # back through restore, not by being picked here.
    if any(n.excluded_at is not None for n in selected):
        return "Need นี้ถูกตัดออกแล้ว — คืน Need ก่อนนำมารวมเป็น PLO"

    # A fallback Need's statement is a marker plus a comma-joined skill list, not
    # a requirement — there is no PLO to draft it into, merged or otherwise. The
    # scope guard is a designer override (selecting an out-of-scope Need is a
    # decision, logged but allowed); this is not, because rewording cannot
    # supply a requirement nobody wrote, and a human has to write the sentence
    # (or re-run need_combination) before this Need can become anyone's PLO.
    # Checked before any LLM call and before anything is written.
    unwritten = [n for n in selected if is_unwritten_need(n)]
    if unwritten:
        return (
            "ยังไม่ได้เขียนประโยคสำหรับ Need: "
            f"{', '.join(n.need_id for n in unwritten)} — ผู้ออกแบบหลักสูตรต้องเขียนประโยคเอง "
            "หรือรันขั้นรวมทักษะเป็น Need ใหม่ ก่อนนำมารวมเป็น PLO"
        )
    return None


def check_redraft(
    existing: Sequence[PLO], all_needs: Sequence[Need], need_ids: Sequence[str]
) -> str | None:
    """Every check `redraft_from_needs` makes before the draft, as pure code.

    Returns the Thai refusal text (each one a 422 there) or None. Same texts and
    order as the route always had; send-back's dry run calls it against the set
    it projects, so a plan is refused where the real action would be.
    """
    from curriculum_agent.stages.need_grouping import (  # noqa: PLC0415
        MAX_CORE_PLOS,
        MIN_CORE_AFTER_MERGE,
    )
    from curriculum_agent.stages.plo_synthesis import plos_citing  # noqa: PLC0415

    refusal = _need_refusal(all_needs, need_ids)
    if refusal is not None:
        return refusal
    by_id = {n.need_id: n for n in all_needs}
    selected = [by_id[nid] for nid in need_ids]

    # A merged outcome is supplementary only when every Need feeding it is.
    is_optional = all(n.is_optional for n in selected)

    # One outcome per Need. Every PLO citing any selected Need is replaced by this
    # merge rather than left standing beside it: this endpoint used to append, so a
    # Need ended up behind both its own outcome and the merged one, and two PLOs
    # claiming the same evidence read as two independent market demands in the
    # มคอ.2 matrix when they are one. Replacing is also what a designer means by
    # "merge" — the outcomes the merge supersedes are exactly the ones it covers.
    superseded_ids = {p.plo_id for p in plos_citing(existing, need_ids)}
    surviving = [p for p in existing if p.plo_id not in superseded_ids]

    current_core = sum(1 for p in existing if not p.is_optional)
    projected_core = sum(1 for p in surviving if not p.is_optional) + (0 if is_optional else 1)

    # The 6-10 policy is a property of the stored set, not of one stage's output,
    # and a replacing merge moves the count in both directions: folding several
    # outcomes into one lowers it, merging Needs nothing cites yet raises it.
    # Both bounds are therefore checked here — the ceiling at MAX_CORE_PLOS, the
    # floor at MIN_CORE_AFTER_MERGE below. Optional PLOs are outside the count,
    # for the same reason they are in synthesis.
    if projected_core > MAX_CORE_PLOS:
        return (
            f"การรวมนี้จะทำให้มี PLO หลัก {projected_core} ข้อ เกินเพดาน "
            f"{MAX_CORE_PLOS} ข้อ เลือก Need ที่มี PLO อยู่แล้วเข้ามารวมด้วย "
            "เพื่อให้การรวมนี้แทนที่ PLO เดิมแทนที่จะเพิ่มข้อใหม่"
        )
    # The merge floor, not the policy floor: a merge may leave the set under the
    # 6-10 band — two PLOs that say one thing are not two outcomes, and the band's
    # own warning still tells the designer — but not under MIN_CORE_AFTER_MERGE.
    # plo_synthesis folds duplicates down to the same number, so nothing the stage
    # does on its own is refused here by hand. Only when this merge causes the
    # shortfall: a program that is already short must not have every further
    # merge refused for a shortfall it did not cause.
    if projected_core < MIN_CORE_AFTER_MERGE and projected_core < current_core:
        return (
            f"การรวมนี้จะเหลือ PLO หลัก {projected_core} ข้อ ต่ำกว่าขั้นต่ำของการรวม "
            f"{MIN_CORE_AFTER_MERGE} ข้อ รวม Need ที่ยังไม่มี PLO ขึ้นมาเป็นข้อใหม่ก่อน "
            "แล้วจึงรวมข้อที่ซ้ำซ้อนกัน"
        )
    return None


async def redraft_from_needs(
    program: ProgramMetadata,
    program_id: str,
    need_ids: list[str],
    *,
    note_th: str | None,
    cause: str,
    accept: Callable[[PLO], str | None] | None = None,
    trail: Callable[[PLO], FeedbackAction] | None = None,
) -> tuple[PLO, list[str]]:
    """Draft one PLO from `need_ids` and swap it in for every PLO citing them.

    Raises `RedraftRefused` (nothing read past the check, nothing written) or
    `RedraftFailed` (the draft came back empty; nothing written). Takes no lock:
    the caller already holds the program busy — a route through `sync_writer`, a
    review job or graph session through its own registration — and a second
    registration here would refuse against that.

    `accept`, when given, sees the finished draft before anything is written; a
    returned Thai reason raises `RedraftRefused(422, reason)`. The designer's route
    passes none.

    `trail`, when given, builds the `plo_feedback_actions` row for the accepted
    draft; `replace` writes it in the transaction that swaps the PLOs, so the
    change and its trail row cannot be separated by a cancellation. Send-back
    passes it; the designer's route does not.
    """
    from curriculum_agent.stages.need_grouping import is_in_scope  # noqa: PLC0415
    from curriculum_agent.stages.plo_synthesis import (  # noqa: PLC0415
        SiblingSummary,
        cited_need_ids,
        next_plo_id,
        plos_citing,
        synthesize_from_needs,
    )

    all_needs = await NeedRepository().list_by_program(program_id)
    # The Need checks first, so a request naming a bad Need costs no PLO read.
    refusal = _need_refusal(all_needs, need_ids)
    if refusal is not None:
        raise RedraftRefused(422, refusal)
    existing = await PLORepository().list_by_program(program_id)
    refusal = check_redraft(existing, all_needs, need_ids)
    if refusal is not None:
        raise RedraftRefused(422, refusal)

    by_id = {n.need_id: n for n in all_needs}
    selected = [by_id[nid] for nid in need_ids]
    # The draft takes the next free number in its series — a PLO's identity is
    # (program_id, plo_id) and the repository upserts on it, so reusing a plo_id
    # within this program would overwrite an existing outcome.
    is_optional = all(n.is_optional for n in selected)
    superseded = plos_citing(existing, need_ids)
    superseded_ids = {p.plo_id for p in superseded}
    surviving = [p for p in existing if p.plo_id not in superseded_ids]

    # A Need cited only by an outcome this merge supersedes loses its PLO and
    # returns to the pool. That is the correct outcome — it is no longer behind
    # anything — but it is not something the designer asked for, so it is named
    # rather than left to be noticed on the report page.
    # Deliberately not filtered here, and deliberately not a 422 either: picking
    # these Needs is a person's decision, and this endpoint is the only way to
    # override the guard — which is why no separate override control exists. The
    # line is here so an out-of-scope PLO can be traced back to the moment someone
    # asked for it.
    out_of_scope = [n for n in selected if not is_in_scope(n)]
    if out_of_scope:
        logger.warning(
            f"Merge includes {len(out_of_scope)} out-of-scope Need(s): "
            f"{', '.join(n.need_id for n in out_of_scope)} — designer's choice, not filtered"
        )

    released = sorted(cited_need_ids(superseded) - set(need_ids))
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
        note_th=note_th,
        # The superseded outcomes are about to be deleted, so they are not
        # siblings: warning "this duplicates PLO3" when PLO3 is being replaced
        # by this very call is a false finding.
        siblings=[SiblingSummary.from_plo(p) for p in surviving],
    )
    if plo is None:
        # Nothing has been deleted yet: the supersede and the insert happen
        # together below, so a failed synthesis leaves the set exactly as it was.
        raise RedraftFailed
    if accept is not None:
        refusal = accept(plo)
        if refusal is not None:
            raise RedraftRefused(422, refusal)

    # `expect` is the set as read above, before a draft that can take minutes: a
    # hand edit that landed meanwhile refuses the replace instead of being deleted.
    extra: dict[str, FeedbackAction] = {} if trail is None else {"trail_row": trail(plo)}
    try:
        removed = await PLORepository().replace(
            program_id,
            sorted(superseded_ids),
            [plo],
            cause=cause,
            expect={p.plo_id: p.statement_th for p in superseded},
            **extra,
        )
    except PLOChangedDuringRedraft as exc:
        logger.warning(
            f"Redraft into {plo.plo_id} refused: {exc.plo_id} changed while it was drafted"
        )
        raise RedraftRefused(409, REASON_CHANGED_DURING_REDRAFT) from exc
    if removed:
        logger.info(f"Merge into {plo.plo_id} replaced {removed} PLO row(s)")
    return plo, sorted(superseded_ids)
