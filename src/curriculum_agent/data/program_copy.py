"""Copy a program: every row it owns, under fresh ids, in one transaction.

A copy exists so one synthesis run's results survive the next (the run
comparison spec, docs/superpowers/specs/2026-10-06-run-comparison-design.md).

evidence_id, skill_id, need_id and group_id (skill groups) are single-column,
global primary keys, so a copy cannot reuse them; plo_id is per program since
migration e4b6d19a3f72 and is kept. One old->new map covers every id kind. `_clone`
runs `remap_ids` only over the named reference columns (`source_evidence_id`,
`member_skill_ids`, `source_evidence_ids`, `source_need_ids`) and over every
JSONB column — not over every column — because a client-supplied id like
`evidence_id` carries no format check and can coincidentally equal a plain
column's value (a stakeholder_type of "employer", say): remapping every
column would silently rewrite that column too. A JSONB column that starts
carrying an id later is still covered without a change here; a new plain
column is not, and does not need to be, since a plain column never held an id
in the first place. Free text that merely contains an id is left alone. Each
row's own primary key (evidence_id / skill_id / need_id) is set explicitly via
an override at the call site rather than through this column scan.

Rows are cloned column by column from the table definition, so a column added
later is copied by default rather than silently dropped.

Not copied: sessions, checkpoints and LangGraph threads (a copy has no
suspended run to resume), and llm_cache (shared by key already).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypeVar

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from curriculum_agent.data.orm import (
    Base,
    EvidenceTable,
    NeedTable,
    PLOReviewTable,
    PLOTable,
    ProgramTable,
    SkillGroupTable,
    SkillTable,
)
from curriculum_agent.data.postgres import AsyncSessionLocal
from curriculum_agent.data.repositories import _row_to_dict
from curriculum_agent.models import PLO
from curriculum_agent.stages.plo_review_facts import plo_fingerprint

_Row = TypeVar("_Row", bound=Base)

# "evidence_only" copies the program row and its evidence and nothing derived
# from it: the way to change evidence after extraction, since an evidence edit
# is refused once skills or Needs exist (api/routes/evidence.py).
CopyMode = Literal["full", "evidence_only"]


@dataclass(frozen=True)
class ProgramRows:
    program: ProgramTable
    evidence: list[EvidenceTable]
    skills: list[SkillTable]
    needs: list[NeedTable]
    plos: list[PLOTable]
    review: PLOReviewTable | None
    skill_groups: list[SkillGroupTable] = field(default_factory=list)


def _uuid4() -> str:
    return str(uuid.uuid4())


def remap_ids(value: Any, id_map: Mapping[str, str]) -> Any:
    """Rewrite every string exactly equal to an old id, at any depth.

    Dict keys too: a JSONB map keyed by an id must follow the id. Only an exact
    match is replaced — an id inside free text stays as written.
    """
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, list):
        return [remap_ids(v, id_map) for v in value]
    if isinstance(value, tuple):
        return tuple(remap_ids(v, id_map) for v in value)
    if isinstance(value, dict):
        return {remap_ids(k, id_map): remap_ids(v, id_map) for k, v in value.items()}
    return value


# The columns that carry an old->new id reference wherever they occur. Every
# JSONB column is remapped too (detected from the table definition, not listed
# by name here); every other column is copied verbatim — see the module
# docstring for why a plain column must not go through remap_ids.
_REFERENCE_COLUMNS = frozenset(
    {
        "source_evidence_id",
        "member_skill_ids",
        "source_evidence_ids",
        "source_need_ids",
        "merged_into",
        "merged_from",
    }
)


def _remappable_columns(table_cls: type[_Row]) -> frozenset[str]:
    return frozenset(
        c.key
        for c in table_cls.__table__.columns
        if c.key in _REFERENCE_COLUMNS or isinstance(c.type, JSONB)
    )


def _clone(row: _Row, id_map: Mapping[str, str], **overrides: Any) -> _Row:
    remappable = _remappable_columns(type(row))
    data = {
        k: (remap_ids(v, id_map) if k in remappable else v) for k, v in _row_to_dict(row).items()
    }
    data.update(overrides)
    return type(row)(**data)


def _fingerprint(plo_rows: list[PLOTable], need_rows: list[NeedTable]) -> str | None:
    """The review fingerprint of a program's rows, or None if a PLO row won't parse.

    Over active Needs only, as `plo_review` fingerprints them: hashing a
    merged-away or excluded Need too would never match the stored review, so a
    current review would read as stale on every copy of a program that has one.
    """
    try:
        return plo_fingerprint(
            [PLO.model_validate(_row_to_dict(r)) for r in plo_rows],
            {
                r.need_id: r.demand_score
                for r in need_rows
                if r.merged_into is None and r.excluded_at is None
            },
        )
    except Exception as exc:  # noqa: BLE001 - a legacy row only costs freshness
        logger.warning(f"program copy: PLO rows did not parse for the fingerprint: {exc}")
        return None


def build_copy(
    src: ProgramRows,
    new_id: str,
    *,
    now: datetime,
    new_uuid: Callable[[], str] = _uuid4,
    mode: CopyMode = "full",
) -> ProgramRows:
    """New ORM rows for `new_id`, every evidence/skill/Need id fresh and rewired.

    Pure: reads `src`, mutates nothing, touches no session. In `evidence_only`
    mode the derived rows (skills, groups, Needs, PLOs, review) are left out, so
    nothing is re-keyed or re-fingerprinted for them.
    """
    if mode == "evidence_only":
        src = ProgramRows(
            program=src.program,
            evidence=src.evidence,
            skills=[],
            needs=[],
            plos=[],
            review=None,
            skill_groups=[],
        )
    id_map: dict[str, str] = {}
    for e in src.evidence:
        id_map[e.evidence_id] = new_uuid()
    for s in src.skills:
        id_map[s.skill_id] = new_uuid()
    for n in src.needs:
        id_map[n.need_id] = new_uuid()
    for g in src.skill_groups:
        id_map[g.group_id] = new_uuid()

    program = _clone(
        src.program,
        id_map,
        program_id=new_id,
        created_at=now,
        copied_from=src.program.program_id,
    )
    # Each row's own primary key is an id in `id_map` too, but it is not one of
    # the remapped columns (it is neither a named reference column nor JSONB —
    # see _clone), so it is set explicitly here rather than relying on the
    # column scan to catch it.
    evidence = [
        _clone(e, id_map, program_id=new_id, evidence_id=id_map[e.evidence_id])
        for e in src.evidence
    ]
    skills = [_clone(s, id_map, program_id=new_id, skill_id=id_map[s.skill_id]) for s in src.skills]
    needs = [_clone(n, id_map, program_id=new_id, need_id=id_map[n.need_id]) for n in src.needs]
    skill_groups = [
        _clone(g, id_map, program_id=new_id, group_id=id_map[g.group_id]) for g in src.skill_groups
    ]
    plos = [_clone(p, id_map, program_id=new_id) for p in src.plos]

    review: PLOReviewTable | None = None
    if src.review is not None:
        # The fingerprint hashes source_need_ids, which just changed. A review
        # that was current for the source is recomputed so it stays current for
        # the copy; a stale one keeps its old fingerprint and so stays stale.
        source_fp = _fingerprint(src.plos, src.needs)
        copied_fp = _fingerprint(plos, needs)
        fingerprint = src.review.plo_fingerprint
        if source_fp is not None and copied_fp is not None and fingerprint == source_fp:
            fingerprint = copied_fp
        review = _clone(src.review, id_map, program_id=new_id, plo_fingerprint=fingerprint)

    return ProgramRows(
        program=program,
        evidence=evidence,
        skills=skills,
        needs=needs,
        plos=plos,
        review=review,
        skill_groups=skill_groups,
    )


async def load_rows(session: AsyncSession, program_id: str) -> ProgramRows | None:
    program = await session.get(ProgramTable, program_id)
    if program is None:
        return None

    async def _all(table: type[_Row], column: Any) -> list[_Row]:
        return list(
            (await session.execute(select(table).where(column == program_id))).scalars().all()
        )

    return ProgramRows(
        program=program,
        evidence=await _all(EvidenceTable, EvidenceTable.program_id),
        skills=await _all(SkillTable, SkillTable.program_id),
        needs=await _all(NeedTable, NeedTable.program_id),
        plos=await _all(PLOTable, PLOTable.program_id),
        review=await session.get(PLOReviewTable, program_id),
        skill_groups=await _all(SkillGroupTable, SkillGroupTable.program_id),
    )


async def copy_program(
    source_id: str, new_id: str, *, now: datetime | None = None, mode: CopyMode = "full"
) -> bool:
    """Copy `source_id` to `new_id` in one session. False if the source is gone.

    One commit at the end, so a failure anywhere leaves nothing behind. A flush
    after each group puts the parent rows in before the rows whose foreign keys
    point at them; the ORM declares no relationships to order them otherwise.
    An IntegrityError on the program row (id taken concurrently) propagates for
    the route to retry under the next id.
    """
    async with AsyncSessionLocal() as session:
        # need_combination deletes then inserts in two separate commits, so the
        # five SELECTs in load_rows under READ COMMITTED could land between
        # them and copy an inconsistent set. REPEATABLE READ pins the whole
        # read to one snapshot.
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        src = await load_rows(session, source_id)
        if src is None:
            return False
        copy = build_copy(src, new_id, now=now or datetime.utcnow(), mode=mode)
        session.add(copy.program)
        await session.flush()
        for group in (copy.evidence, copy.skills, copy.skill_groups, copy.needs, copy.plos):
            session.add_all(group)
            await session.flush()
        if copy.review is not None:
            session.add(copy.review)
        await session.commit()
    logger.info(
        f"program copy ({mode}): {source_id} -> {new_id} ({len(copy.evidence)} evidence, "
        f"{len(copy.skills)} skills, {len(copy.skill_groups)} skill groups, "
        f"{len(copy.needs)} Needs, {len(copy.plos)} PLOs, "
        f"review={'yes' if copy.review is not None else 'no'})"
    )
    return True
