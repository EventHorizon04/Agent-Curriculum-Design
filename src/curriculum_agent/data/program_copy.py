"""Copy a program: every row it owns, under fresh ids, in one transaction.

A copy exists so one synthesis run's results survive the next (the run
comparison spec, docs/superpowers/specs/2026-10-06-run-comparison-design.md).

evidence_id, skill_id and need_id are single-column, global primary keys, so a
copy cannot reuse them; plo_id is per program since migration e4b6d19a3f72 and
is kept. One old->new map covers the three id kinds, and `remap_ids` rewrites
every value in every column that exactly equals an old id — the named
reference columns and the JSONB blobs alike, so a column that starts carrying
an id later is covered without a change here. Free text that merely contains
an id is left alone.

Rows are cloned column by column from the table definition, so a column added
later is copied by default rather than silently dropped.

Not copied: sessions, checkpoints and LangGraph threads (a copy has no
suspended run to resume), and llm_cache (shared by key already).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from loguru import logger

from curriculum_agent.data.orm import (
    Base,
    EvidenceTable,
    NeedTable,
    PLOReviewTable,
    PLOTable,
    ProgramTable,
    SkillTable,
)
from curriculum_agent.data.repositories import _row_to_dict
from curriculum_agent.models import PLO
from curriculum_agent.stages.plo_review import plo_fingerprint

_Row = TypeVar("_Row", bound=Base)


@dataclass(frozen=True)
class ProgramRows:
    program: ProgramTable
    evidence: list[EvidenceTable]
    skills: list[SkillTable]
    needs: list[NeedTable]
    plos: list[PLOTable]
    review: PLOReviewTable | None


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


def _clone(row: _Row, id_map: Mapping[str, str], **overrides: Any) -> _Row:
    data = {k: remap_ids(v, id_map) for k, v in _row_to_dict(row).items()}
    data.update(overrides)
    return type(row)(**data)


def _fingerprint(rows: list[PLOTable]) -> str | None:
    """The review fingerprint of a PLO row set, or None if a row won't parse."""
    try:
        return plo_fingerprint([PLO.model_validate(_row_to_dict(r)) for r in rows])
    except Exception as exc:  # noqa: BLE001 - a legacy row only costs freshness
        logger.warning(f"program copy: PLO rows did not parse for the fingerprint: {exc}")
        return None


def build_copy(
    src: ProgramRows,
    new_id: str,
    *,
    now: datetime,
    new_uuid: Callable[[], str] = _uuid4,
) -> ProgramRows:
    """New ORM rows for `new_id`, every evidence/skill/Need id fresh and rewired.

    Pure: reads `src`, mutates nothing, touches no session.
    """
    id_map: dict[str, str] = {}
    for e in src.evidence:
        id_map[e.evidence_id] = new_uuid()
    for s in src.skills:
        id_map[s.skill_id] = new_uuid()
    for n in src.needs:
        id_map[n.need_id] = new_uuid()

    program = _clone(
        src.program,
        id_map,
        program_id=new_id,
        created_at=now,
        copied_from=src.program.program_id,
    )
    evidence = [_clone(e, id_map, program_id=new_id) for e in src.evidence]
    skills = [_clone(s, id_map, program_id=new_id) for s in src.skills]
    needs = [_clone(n, id_map, program_id=new_id) for n in src.needs]
    plos = [_clone(p, id_map, program_id=new_id) for p in src.plos]

    review: PLOReviewTable | None = None
    if src.review is not None:
        # The fingerprint hashes source_need_ids, which just changed. A review
        # that was current for the source is recomputed so it stays current for
        # the copy; a stale one keeps its old fingerprint and so stays stale.
        source_fp = _fingerprint(src.plos)
        copied_fp = _fingerprint(plos)
        fingerprint = src.review.plo_fingerprint
        if source_fp is not None and copied_fp is not None and fingerprint == source_fp:
            fingerprint = copied_fp
        review = _clone(src.review, id_map, program_id=new_id, plo_fingerprint=fingerprint)

    return ProgramRows(
        program=program, evidence=evidence, skills=skills, needs=needs, plos=plos, review=review
    )
