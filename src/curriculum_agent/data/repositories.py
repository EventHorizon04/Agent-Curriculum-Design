from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import CursorResult, case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from curriculum_agent.data.orm import (
    Base,
    CheckpointTable,
    EvidenceTable,
    JobTable,
    LLMCacheTable,
    LLMUsageTable,
    NeedTable,
    PLOFeedbackActionTable,
    PLOReportTable,
    PLOReviewTable,
    PLOTable,
    ProgramTable,
    SessionTable,
    SkillGroupTable,
    SkillTable,
    SupersededPLOTable,
)
from curriculum_agent.data.postgres import AsyncSessionLocal
from curriculum_agent.graph import stage_reached
from curriculum_agent.models import (
    PLO,
    ExtractedSkill,
    FeedbackAction,
    JobInfo,
    JobStatus,
    JobUsage,
    LLMUsage,
    Need,
    PLOReport,
    PLOSetReview,
    ProgramMetadata,
    ProgramSummary,
    SessionInfo,
    SessionUsage,
    SkillGroup,
    SlotUsage,
    StageCheckpoint,
    StakeholderEvidence,
    SupersededPLO,
    UsageSummary,
    UsageTotals,
)


async def _programs_with_rows(session: AsyncSession, column: Any) -> set[str]:
    """Which programs have at least one row in the table this column belongs to.

    One distinct-select per table rather than a count per program: the caller
    needs existence, not totals, and asking per program would be a query per row
    on the list page.
    """
    return set((await session.execute(select(column).distinct())).scalars().all())


async def _programs_with_a_current_review(program_ids: Iterable[str]) -> set[str]:
    """Programs whose stored QA review matches their current PLOs and Needs.

    A read or parse failure counts as "not current" for that program and is
    logged — the program list must never fail over advisory data.
    """
    from curriculum_agent.stages.plo_review_facts import is_stale, need_demands  # noqa: PLC0415

    current: set[str] = set()
    for pid in program_ids:
        try:
            review = await PLOReviewRepository().get(pid)
            if review is None:
                continue
            plos = await PLORepository().list_by_program(pid)
            needs = await NeedRepository().list_active_by_program(pid)
            if plos and not is_stale(review, plos, need_demands(needs)):
                current.add(pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"list_all: could not judge the QA review of {pid}: {exc!r}")
    return current


async def _programs_with_a_current_report(program_ids: Iterable[str]) -> set[str]:
    """Programs whose stored PLO report was built from their current PLOs and Needs.

    Same fingerprint as the QA review, same rule: a read or parse failure counts
    as "not current" for that program and is logged.
    """
    from curriculum_agent.stages.plo_review_facts import (  # noqa: PLC0415
        need_demands,
        plo_fingerprint,
    )

    current: set[str] = set()
    for pid in program_ids:
        try:
            stored = await PLOReportRepository().get(pid)
            if stored is None:
                continue
            plos = await PLORepository().list_by_program(pid)
            needs = await NeedRepository().list_active_by_program(pid)
            if plos and stored.plo_fingerprint == plo_fingerprint(plos, need_demands(needs)):
                current.add(pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"list_all: could not judge the PLO report of {pid}: {exc!r}")
    return current


def _row_to_dict(row: Base) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns}


def _plo_row_data(plo: PLO) -> dict[str, Any]:
    """Column values for a PLO row. `model_dump(mode="json")` renders datetimes as
    ISO strings with an offset, which the ORM DateTime column rejects, so the
    timestamp is handed over as the naive-UTC datetime the column stores."""
    data = plo.model_dump(mode="json")
    edited = plo.designer_edited_at
    if edited is not None and edited.tzinfo is not None:
        edited = edited.astimezone(UTC).replace(tzinfo=None)
    data["designer_edited_at"] = edited
    return data


def _json_safe(data: dict[str, Any]) -> dict[str, Any]:
    """A row as a JSONB snapshot: datetimes become ISO strings."""
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in data.items()}


def _fix_datetimes(data: dict[str, Any], table_cls: type[Base]) -> dict[str, Any]:
    """Parse ISO datetime strings to datetime objects for DateTime ORM columns."""
    from sqlalchemy import DateTime as _DT

    for col in table_cls.__table__.columns:
        if isinstance(col.type, _DT) and col.name in data:
            val = data[col.name]
            if isinstance(val, str) and val:
                data[col.name] = datetime.fromisoformat(val)
    return data


class ProgramRepository:
    async def upsert(self, metadata: ProgramMetadata) -> None:
        async with AsyncSessionLocal() as session:
            data = _fix_datetimes(metadata.model_dump(mode="json"), ProgramTable)
            row = await session.get(ProgramTable, metadata.program_id)
            if row is None:
                session.add(ProgramTable(**data))
            else:
                for k, v in data.items():
                    setattr(row, k, v)
            await session.commit()

    async def insert(self, metadata: ProgramMetadata) -> None:
        """Plain INSERT — raises IntegrityError if program_id already exists.

        Used by the create route so the database arbitrates concurrent id
        generation. upsert() remains for stage handlers updating an existing
        program.
        """
        async with AsyncSessionLocal() as session:
            data = _fix_datetimes(metadata.model_dump(mode="json"), ProgramTable)
            session.add(ProgramTable(**data))
            await session.commit()

    async def get(self, program_id: str) -> ProgramMetadata | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(ProgramTable, program_id)
            if row is None:
                return None
            data = _row_to_dict(row)
            # The column is nullable (rows predate the field) while the model
            # says `str = ""`. Left as None it would reach the extraction cache
            # key through str() and hash the literal "None", quietly giving every
            # pre-scope program a key of its own.
            if data.get("scope_th") is None:
                data["scope_th"] = ""
            return ProgramMetadata.model_validate(data)

    async def exists(self, program_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            row = await session.get(ProgramTable, program_id)
            return row is not None

    async def list_all(self) -> list[ProgramSummary]:
        """All programs (created_at DESC), each with how far it has got.

        Progress is derived from the rows a program owns, not read off its latest
        session — see `stage_reached`. The session is still what says whether a
        run is waiting for approval, which is a different fact and stays its own
        field.
        """
        async with AsyncSessionLocal() as session:
            prog_rows = (
                (
                    await session.execute(
                        select(ProgramTable).order_by(ProgramTable.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            sess_rows = (await session.execute(select(SessionTable))).scalars().all()
            with_evidence = await _programs_with_rows(session, EvidenceTable.program_id)
            with_skills = await _programs_with_rows(session, SkillTable.program_id)
            with_needs = await _programs_with_rows(session, NeedTable.program_id)
            with_plos = await _programs_with_rows(session, PLOTable.program_id)

        # Only a program with PLOs can have a current review.
        current = await _programs_with_a_current_review(with_plos)
        current_report = await _programs_with_a_current_report(with_plos)

        latest: dict[str, SessionTable] = {}
        for s in sess_rows:
            cur = latest.get(s.program_id)
            if cur is None or s.created_at > cur.created_at:
                latest[s.program_id] = s

        return [
            ProgramSummary(
                program_id=p.program_id,
                name_th=p.name_th,
                name_en=p.name_en,
                # Carried so the history page can label a program that has no
                # name of its own — intake identifies programs by these now.
                field=p.field,
                faculty=p.faculty,
                degree_level=p.degree_level,
                created_at=p.created_at,
                current_stage=stage_reached(
                    has_evidence=p.program_id in with_evidence,
                    has_skills=p.program_id in with_skills,
                    has_needs=p.program_id in with_needs,
                    has_plos=p.program_id in with_plos,
                    has_current_review=p.program_id in current,
                    has_current_report=p.program_id in current_report,
                ),
                session_status=(latest[p.program_id].status if p.program_id in latest else None),
                copied_from=p.copied_from,
            )
            for p in prog_rows
        ]

    async def delete_cascade(self, program_id: str) -> bool:
        """Hard-delete a program and everything under it, in one transaction.

        Deletes skill_groups before skills (their ids point at skill rows), and skills
        before evidence because SkillTable.source_evidence_id
        is a FK into EvidenceTable. Returns False (no-op) if program_id
        doesn't exist — the thirteen deletes before the program's own affect zero rows either way.
        """
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(SkillGroupTable).where(SkillGroupTable.program_id == program_id)
            )
            await session.execute(delete(SkillTable).where(SkillTable.program_id == program_id))
            await session.execute(delete(NeedTable).where(NeedTable.program_id == program_id))
            await session.execute(
                delete(SupersededPLOTable).where(SupersededPLOTable.program_id == program_id)
            )
            await session.execute(
                delete(PLOFeedbackActionTable).where(
                    PLOFeedbackActionTable.program_id == program_id
                )
            )
            await session.execute(
                delete(LLMUsageTable).where(LLMUsageTable.program_id == program_id)
            )
            await session.execute(delete(PLOTable).where(PLOTable.program_id == program_id))
            await session.execute(
                delete(PLOReviewTable).where(PLOReviewTable.program_id == program_id)
            )
            await session.execute(
                delete(PLOReportTable).where(PLOReportTable.program_id == program_id)
            )
            await session.execute(
                delete(CheckpointTable).where(CheckpointTable.program_id == program_id)
            )
            await session.execute(delete(SessionTable).where(SessionTable.program_id == program_id))
            await session.execute(delete(JobTable).where(JobTable.program_id == program_id))
            await session.execute(
                delete(EvidenceTable).where(EvidenceTable.program_id == program_id)
            )
            result = cast(
                CursorResult[Any],
                await session.execute(
                    delete(ProgramTable).where(ProgramTable.program_id == program_id)
                ),
            )
            await session.commit()
            return result.rowcount > 0


class EvidenceRepository:
    async def bulk_insert(self, items: list[StakeholderEvidence]) -> None:
        async with AsyncSessionLocal() as session:
            for item in items:
                data = _fix_datetimes(item.model_dump(mode="json"), EvidenceTable)
                extra_metadata = data.pop("metadata")
                existing = await session.get(EvidenceTable, item.evidence_id)
                if existing is None:
                    session.add(EvidenceTable(**data, extra_metadata=extra_metadata))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
                    existing.extra_metadata = extra_metadata
            await session.commit()

    async def list_by_program(self, program_id: str) -> list[StakeholderEvidence]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EvidenceTable).where(EvidenceTable.program_id == program_id)
            )
            rows = result.scalars().all()
            out = []
            for row in rows:
                d = _row_to_dict(row)
                d["metadata"] = d.pop("extra_metadata")
                out.append(StakeholderEvidence.model_validate(d))
            return out

    async def get(self, program_id: str, evidence_id: str) -> StakeholderEvidence | None:
        """One evidence item, or None when it is absent or another program's."""
        async with AsyncSessionLocal() as session:
            row = await session.get(EvidenceTable, evidence_id)
            if row is None or row.program_id != program_id:
                return None
            d = _row_to_dict(row)
            d["metadata"] = d.pop("extra_metadata")
            return StakeholderEvidence.model_validate(d)

    async def program_of(self, evidence_id: str) -> str | None:
        """The program an evidence id is stored under, or None when it is new.

        `evidence_id` is global and `bulk_insert` upserts by it alone, so a
        writer scoped to one program has to ask this before writing: an id that
        already belongs to another program would otherwise be rewritten, or
        moved, from outside that program's lock.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EvidenceTable.program_id).where(EvidenceTable.evidence_id == evidence_id)
            )
            return result.scalar_one_or_none()

    async def delete(self, program_id: str, evidence_id: str) -> bool:
        """Delete one evidence row scoped to its program. Returns False if it
        doesn't exist OR belongs to a different program_id (same 404 either way
        — don't leak whether the id exists under another program).

        Propagates sqlalchemy.exc.IntegrityError unchanged if a skill's
        source_evidence_id FK still references this row — the route maps
        that to a 409 for the caller. Confirmed empirically: SQLAlchemy
        async + asyncpg raises IntegrityError (wrapping asyncpg's
        ForeignKeyViolationError) on this exact constraint.
        """
        async with AsyncSessionLocal() as session:
            row = await session.get(EvidenceTable, evidence_id)
            if row is None or row.program_id != program_id:
                return False
            await session.delete(row)
            await session.commit()
            return True


class SkillRepository:
    async def delete_by_program(self, program_id: str) -> int:
        """Drop every skill row for a program. Returns the row count removed.

        `skill_id` is generated fresh on each extraction run while bulk_insert
        upserts by that id, so a re-run would otherwise insert a second complete
        set and the Stage 3 table would show every skill twice. Re-running a
        stage replaces its output; this is what makes that true.
        """
        async with AsyncSessionLocal() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    delete(SkillTable).where(SkillTable.program_id == program_id)
                ),
            )
            await session.commit()
            return result.rowcount

    async def has_any(self, program_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SkillTable.skill_id).where(SkillTable.program_id == program_id).limit(1)
            )
            return result.first() is not None

    async def bulk_insert(self, skills: list[ExtractedSkill]) -> None:
        async with AsyncSessionLocal() as session:
            for skill in skills:
                data = skill.model_dump(mode="json")
                existing = await session.get(SkillTable, skill.skill_id)
                if existing is None:
                    session.add(SkillTable(**data))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
            await session.commit()

    async def list_by_program(self, program_id: str) -> list[ExtractedSkill]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SkillTable).where(SkillTable.program_id == program_id)
            )
            rows = result.scalars().all()
            return [ExtractedSkill.model_validate(_row_to_dict(row)) for row in rows]

    async def list_by_ids(self, skill_ids: list[str]) -> list[ExtractedSkill]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SkillTable).where(SkillTable.skill_id.in_(skill_ids))
            )
            rows = result.scalars().all()
            return [ExtractedSkill.model_validate(_row_to_dict(row)) for row in rows]


class SkillGroupRepository:
    async def delete_by_program(self, program_id: str) -> int:
        """Drop every skill group for a program. Returns the row count removed."""
        async with AsyncSessionLocal() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    delete(SkillGroupTable).where(SkillGroupTable.program_id == program_id)
                ),
            )
            await session.commit()
            return result.rowcount

    async def bulk_insert(self, groups: list[SkillGroup]) -> None:
        """Upsert by group_id; `ordinal` records the list position."""
        async with AsyncSessionLocal() as session:
            for ordinal, group in enumerate(groups):
                data = group.model_dump(mode="json")
                existing = await session.get(SkillGroupTable, group.group_id)
                if existing is None:
                    session.add(SkillGroupTable(**data, ordinal=ordinal))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
                    existing.ordinal = ordinal
            await session.commit()

    async def list_by_program(self, program_id: str) -> list[SkillGroup]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SkillGroupTable)
                .where(SkillGroupTable.program_id == program_id)
                .order_by(SkillGroupTable.ordinal)
            )
            return [SkillGroup.model_validate(_row_to_dict(row)) for row in result.scalars().all()]


class NeedRepository:
    async def delete_by_program(self, program_id: str) -> int:
        """Drop every Need row for a program. Returns the row count removed.

        Same defect as SkillRepository.delete_by_program: `need_id` is a fresh
        uuid per run and bulk_insert upserts by it. Needs also hold
        member_skill_ids pointing at skill rows that the extraction re-run has
        just replaced, so a surviving old Need would reference dead skill ids.
        """
        async with AsyncSessionLocal() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(delete(NeedTable).where(NeedTable.program_id == program_id)),
            )
            await session.commit()
            return result.rowcount

    async def has_any(self, program_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NeedTable.need_id).where(NeedTable.program_id == program_id).limit(1)
            )
            return result.first() is not None

    async def bulk_insert(self, needs: list[Need]) -> None:
        async with AsyncSessionLocal() as session:
            for need in needs:
                # excluded_at is a datetime; the ORM column rejects its ISO string.
                data = _fix_datetimes(need.model_dump(mode="json"), NeedTable)
                existing = await session.get(NeedTable, need.need_id)
                if existing is None:
                    session.add(NeedTable(**data))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
            await session.commit()

    async def list_by_program(self, program_id: str) -> list[Need]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NeedTable).where(NeedTable.program_id == program_id)
            )
            return [Need.model_validate(_row_to_dict(row)) for row in result.scalars().all()]

    async def list_active_by_program(self, program_id: str) -> list[Need]:
        """Needs neither folded into a merged Need nor excluded by the designer.

        What every downstream stage reads, so an exclusion needs no filter of its own.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(NeedTable).where(
                    NeedTable.program_id == program_id,
                    NeedTable.merged_into.is_(None),
                    NeedTable.excluded_at.is_(None),
                )
            )
            return [Need.model_validate(_row_to_dict(row)) for row in result.scalars().all()]

    async def set_excluded(
        self, program_id: str, need_id: str, excluded_at: datetime | None
    ) -> Need:
        """Exclude a Need (a timestamp) or restore it (None). KeyError if not this program's."""
        async with AsyncSessionLocal() as session:
            row = await session.get(NeedTable, need_id)
            if row is None or row.program_id != program_id:
                raise KeyError(need_id)
            row.excluded_at = excluded_at
            await session.commit()
            return Need.model_validate(_row_to_dict(row))

    async def write_merge(self, program_id: str, originals: list[Need], merged: Need) -> Need:
        """Store a merged Need and hide its originals, in one transaction.

        The same pairing as `split` in reverse: the originals pointing at a parent
        and the parent existing are one fact, and a half-applied merge would hide
        Needs under a parent that was never written.
        """
        async with AsyncSessionLocal() as session:
            for original in originals:
                row = await session.get(NeedTable, original.need_id)
                if row is None or row.program_id != program_id:
                    raise KeyError(original.need_id)
                row.merged_into = merged.need_id
            session.add(NeedTable(**_fix_datetimes(merged.model_dump(mode="json"), NeedTable)))
            await session.commit()
            return merged

    async def split(self, program_id: str, merged_need_id: str) -> list[Need]:
        """Undo a merge: delete the merged Need and free its originals.

        One session, one commit — the merged row going away and the originals
        coming back are one fact, and a half-applied split would leave Needs
        hidden under a parent that no longer exists. Returns the restored
        originals.
        """
        async with AsyncSessionLocal() as session:
            merged = await session.get(NeedTable, merged_need_id)
            if merged is None or merged.program_id != program_id:
                raise KeyError(merged_need_id)
            result = await session.execute(
                select(NeedTable).where(
                    NeedTable.program_id == program_id,
                    NeedTable.merged_into == merged_need_id,
                )
            )
            originals = list(result.scalars().all())
            for row in originals:
                row.merged_into = None
            await session.delete(merged)
            await session.commit()
            return [Need.model_validate(_row_to_dict(row)) for row in originals]


class PLOChangedDuringRedraft(Exception):
    """A PLO `replace` was asked to supersede is not the one the caller read.

    Raised from inside the transaction before anything is written: the row is
    gone, its version differs from the one expected, or (for a `review`
    replace) the designer has edited it since. `plo_id` names the first such row.
    """

    def __init__(self, plo_id: str) -> None:
        super().__init__(plo_id)
        self.plo_id = plo_id


class PLORepository:
    async def delete_by_program(self, program_id: str) -> int:
        """Drop every PLO row for a program. Returns the row count removed.

        Needed for the same reason as the Skill and Need equivalents, by a
        different route. `plo_id` is stable (PLO1..PLOn, OPT1..OPTn), so the
        upsert in bulk_insert refreshes what a re-run produces again — but a run
        that yields *fewer* PLOs than the last leaves the surplus behind, and
        need_combination has already deleted the Needs they cited. The result is
        a PLO whose trace resolves to nothing.

        The program's superseded history and its stored report go in the same
        transaction: they hang off the PLO set the designer is discarding, and a
        re-run starts clean.
        """
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(SupersededPLOTable).where(SupersededPLOTable.program_id == program_id)
            )
            await session.execute(
                delete(PLOFeedbackActionTable).where(
                    PLOFeedbackActionTable.program_id == program_id
                )
            )
            await session.execute(
                delete(PLOReportTable).where(PLOReportTable.program_id == program_id)
            )
            result = cast(
                CursorResult[Any],
                await session.execute(delete(PLOTable).where(PLOTable.program_id == program_id)),
            )
            await session.commit()
            return result.rowcount

    async def bulk_insert(self, plos: list[PLO]) -> None:
        async with AsyncSessionLocal() as session:
            for plo in plos:
                data = _plo_row_data(plo)
                # Composite identity — plo_id alone repeats across programs, and
                # session.get(PLOTable, plo.plo_id) used to resolve to whichever
                # program got there first, moving its row to this one on upsert.
                existing = await session.get(
                    PLOTable, {"program_id": plo.program_id, "plo_id": plo.plo_id}
                )
                if existing is None:
                    session.add(PLOTable(**data))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
            await session.commit()

    async def update_if_version(self, plo: PLO, *, expected_version: int) -> bool:
        """Overwrite one stored PLO only if its `version` is still `expected_version`.

        `PUT /plos/{id}` reads, edits and writes back; between the read and the write a
        redraft can merge the row away or another PUT can move it. `bulk_insert` is an
        upsert, so it would resurrect the first and overwrite the second. This is a
        conditional UPDATE built from the same row mapping and never inserts: False means
        no row matched (gone, or the version moved), and nothing was written.
        """
        data = _plo_row_data(plo)
        for key in ("program_id", "plo_id"):
            data.pop(key, None)
        async with AsyncSessionLocal() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(PLOTable)
                    .where(
                        PLOTable.program_id == plo.program_id,
                        PLOTable.plo_id == plo.plo_id,
                        PLOTable.version == expected_version,
                    )
                    .values(**data)
                ),
            )
            await session.commit()
            return result.rowcount == 1

    async def replace(
        self,
        program_id: str,
        remove_plo_ids: list[str],
        add: list[PLO],
        *,
        cause: str = "designer",
        expect: Mapping[str, int] | None = None,
        trail_row: FeedbackAction | None = None,
    ) -> int:
        """Drop some outcomes and write others, in one transaction.

        The designer-driven merge needs both halves to land together: the PLOs it
        supersedes are gone and the one replacing them exists, or neither is true.
        Doing it as a delete followed by an insert leaves a window where the
        program has lost outcomes and gained nothing, and if the insert then fails
        the designer is looking at a curriculum with holes in it.

        Deleting first also frees the plo_id the new outcome wants: a PLO's
        identity is (program_id, plo_id) and `next_plo_id` hands back the lowest
        free number within this program, so a merge normally reuses the lowest
        slot it just emptied.

        `cause` is written on each history row: "designer" for a merge on the PLO
        page, "review" for Agent 4's send-back.

        `expect` (plo_id -> `version` as the caller read it before drafting)
        is optimistic concurrency for a redraft: the draft takes minutes and
        `PUT /plos/{id}` is not blocked meanwhile, so the rows are re-read here,
        locked, and a row that is gone, has a different version (any PUT bumps it,
        even one that leaves the statement alone), or carries
        `designer_edited_at` on a `review` replace raises
        `PLOChangedDuringRedraft` with nothing written. Without the check the
        delete below would take the designer's edit with it.

        `trail_row` is send-back's `plo_feedback_actions` row for this change,
        inserted in the same transaction: an applied change and its trail row
        land together or not at all, so a loop cancelled right after the commit
        cannot leave a changed PLO with no row saying why.

        Returns the number of rows removed.
        """
        async with AsyncSessionLocal() as session:
            removed = 0
            to_read = sorted(set(remove_plo_ids) | set(expect or {}))
            current: dict[str, PLOTable] = {}
            if to_read and (add or expect is not None):
                rows = (
                    (
                        await session.execute(
                            select(PLOTable)
                            .where(
                                PLOTable.program_id == program_id,
                                PLOTable.plo_id.in_(to_read),
                            )
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                current = {row.plo_id: row for row in rows}
            for plo_id, version in (expect or {}).items():
                row = current.get(plo_id)
                if (
                    row is None
                    or row.version != version
                    or (cause == "review" and row.designer_edited_at is not None)
                ):
                    raise PLOChangedDuringRedraft(plo_id)
            if remove_plo_ids:
                if add:
                    # History first, in this same transaction: a PLO is either
                    # live or in superseded_plos, never lost and never both.
                    # Nothing replaces them when `add` is empty, so there is no
                    # `superseded_by` to record.
                    doomed = [current[pid] for pid in remove_plo_ids if pid in current]
                    now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC like every column here
                    for row in doomed:
                        session.add(
                            SupersededPLOTable(
                                id=str(uuid.uuid4()),
                                program_id=program_id,
                                plo_id=row.plo_id,
                                snapshot=_json_safe(_row_to_dict(row)),
                                superseded_by=add[0].plo_id,
                                superseded_at=now,
                                cause=cause,
                            )
                        )
                result = cast(
                    CursorResult[Any],
                    await session.execute(
                        delete(PLOTable).where(
                            PLOTable.program_id == program_id,
                            PLOTable.plo_id.in_(remove_plo_ids),
                        )
                    ),
                )
                removed = result.rowcount
            for plo in add:
                data = _plo_row_data(plo)
                # Same composite identity as bulk_insert — see the comment there.
                existing = await session.get(
                    PLOTable, {"program_id": plo.program_id, "plo_id": plo.plo_id}
                )
                if existing is None:
                    session.add(PLOTable(**data))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
            if trail_row is not None:
                session.add(PLOFeedbackActionTable(**trail_row.model_dump()))
            await session.commit()
            return removed

    async def list_by_program(self, program_id: str) -> list[PLO]:
        """Every PLO for a program, core series first and numerically within it.

        Ordered here because `plo_id` carries meaning: PLO1 is the outcome
        drafted from the most-demanded Need, and synthesis takes care to keep
        that order through `asyncio.gather`. Without an ORDER BY the read threw
        it away again — Postgres returns heap order, and an UPDATE moves a row
        to the end of it, so editing one outcome reshuffled the มคอ.2 matrix and
        the UI list. It showed up as a revalidated PLO4 appearing last in the
        exported workbook.

        `is_optional` first keeps the two series apart (OPT sorts before PLO
        lexicographically, which would put the supplementary outcomes at the
        top), then length before value so PLO9 precedes PLO10 rather than
        following PLO1. Length rather than a cast off a fixed prefix width:
        both prefixes are three characters today and nothing should depend on
        that staying true.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PLOTable)
                .where(PLOTable.program_id == program_id)
                .order_by(
                    PLOTable.is_optional,
                    func.length(PLOTable.plo_id),
                    PLOTable.plo_id,
                )
            )
            rows = result.scalars().all()
            return [PLO.model_validate(_row_to_dict(row)) for row in rows]


class SupersededPLORepository:
    """Read side of the PLOs a designer's merge replaced. Writes happen in
    `PLORepository.replace`, in the same transaction as the delete."""

    async def list_by_program(self, program_id: str) -> list[SupersededPLO]:
        """Newest first. A snapshot that no longer validates as a PLO (validators
        tightened since it was written) is skipped with a warning, not raised:
        history is advisory and must not take the page down."""
        async with AsyncSessionLocal() as session:
            rows = (
                (
                    await session.execute(
                        select(SupersededPLOTable)
                        .where(SupersededPLOTable.program_id == program_id)
                        .order_by(
                            SupersededPLOTable.superseded_at.desc(),
                            func.length(SupersededPLOTable.plo_id),
                            SupersededPLOTable.plo_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
        out: list[SupersededPLO] = []
        for row in rows:
            try:
                out.append(
                    SupersededPLO(
                        id=row.id,
                        program_id=row.program_id,
                        superseded_by=row.superseded_by,
                        superseded_at=row.superseded_at,
                        plo=PLO.model_validate(row.snapshot),
                        cause=row.cause,
                    )
                )
            except ValidationError as exc:
                logger.warning(f"superseded PLO {row.id} ({row.plo_id}) skipped: {exc!r}")
        return out


class PLOFeedbackRepository:
    """The trail of what the PLO set review sent back (phase 4)."""

    async def add(self, actions: list[FeedbackAction]) -> None:
        if not actions:
            return
        async with AsyncSessionLocal() as session:
            for action in actions:
                session.add(PLOFeedbackActionTable(**action.model_dump()))
            await session.commit()

    async def list_by_program(self, program_id: str) -> list[FeedbackAction]:
        """Newest first by `created_at`. Rows are written per action, so within one
        round this is reverse action order; the UI re-sorts a round ascending.
        `id` is a uuid4, so it only makes an exact tie deterministic, not meaningful."""
        async with AsyncSessionLocal() as session:
            rows = (
                (
                    await session.execute(
                        select(PLOFeedbackActionTable)
                        .where(PLOFeedbackActionTable.program_id == program_id)
                        .order_by(
                            PLOFeedbackActionTable.created_at.desc(),
                            PLOFeedbackActionTable.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
        return [FeedbackAction.model_validate(_row_to_dict(row)) for row in rows]


class LLMUsageRepository:
    """Token and latency accounting, one row per provider response (phase 5)."""

    async def add(self, row: LLMUsage) -> None:
        async with AsyncSessionLocal() as session:
            session.add(LLMUsageTable(**row.model_dump()))
            await session.commit()

    async def summary(self, program_id: str) -> UsageSummary:
        """Totals per slot and per job (newest job first), summed in SQL.

        Three grouped queries: per slot, per (job, slot) joined to `jobs` for the
        kind, and per (session, slot) for rows with a session and no job. Rows with
        neither reach `total` and `by_slot` only.
        """
        calls = func.count(LLMUsageTable.id)
        failed = func.coalesce(func.sum(case((LLMUsageTable.ok.is_(False), 1), else_=0)), 0)
        prompt = func.coalesce(func.sum(LLMUsageTable.prompt_tokens), 0)
        completion = func.coalesce(func.sum(LLMUsageTable.completion_tokens), 0)
        reasoning = func.coalesce(func.sum(LLMUsageTable.reasoning_tokens), 0)
        latency = func.coalesce(func.sum(LLMUsageTable.latency_ms), 0)
        measures = (calls, failed, prompt, completion, reasoning, latency)

        async with AsyncSessionLocal() as session:
            slot_rows = (
                await session.execute(
                    select(LLMUsageTable.slot, *measures)
                    .where(LLMUsageTable.program_id == program_id)
                    .group_by(LLMUsageTable.slot)
                    .order_by(LLMUsageTable.slot)
                )
            ).all()
            job_rows = (
                await session.execute(
                    select(
                        LLMUsageTable.job_id,
                        JobTable.kind,
                        LLMUsageTable.slot,
                        func.min(LLMUsageTable.created_at),
                        *measures,
                    )
                    .outerjoin(JobTable, JobTable.job_id == LLMUsageTable.job_id)
                    .where(
                        LLMUsageTable.program_id == program_id,
                        LLMUsageTable.job_id.is_not(None),
                    )
                    .group_by(LLMUsageTable.job_id, JobTable.kind, LLMUsageTable.slot)
                    .order_by(LLMUsageTable.job_id, LLMUsageTable.slot)
                )
            ).all()
            session_rows = (
                await session.execute(
                    select(
                        LLMUsageTable.session_id,
                        LLMUsageTable.slot,
                        func.min(LLMUsageTable.created_at),
                        *measures,
                    )
                    .where(
                        LLMUsageTable.program_id == program_id,
                        LLMUsageTable.job_id.is_(None),
                        LLMUsageTable.session_id.is_not(None),
                    )
                    .group_by(LLMUsageTable.session_id, LLMUsageTable.slot)
                    .order_by(LLMUsageTable.session_id, LLMUsageTable.slot)
                )
            ).all()

        by_slot = [SlotUsage(slot=r[0], **_totals_kwargs(r[1:])) for r in slot_rows]
        jobs: dict[str, JobUsage] = {}
        for r in job_rows:
            job_id, kind, slot, first_at = r[0], r[1], r[2], r[3]
            job = jobs.get(job_id)
            if job is None:
                job = jobs[job_id] = JobUsage(job_id=job_id, kind=kind or "", started=first_at)
            elif first_at < job.started:
                job.started = first_at
            slot_usage = SlotUsage(slot=slot, **_totals_kwargs(r[4:]))
            job.by_slot.append(slot_usage)
            job.total = _add_totals(job.total, slot_usage)
        sessions: dict[str, SessionUsage] = {}
        for r in session_rows:
            session_id, slot, first_at = r[0], r[1], r[2]
            entry = sessions.get(session_id)
            if entry is None:
                entry = sessions[session_id] = SessionUsage(session_id=session_id, started=first_at)
            elif first_at < entry.started:
                entry.started = first_at
            slot_usage = SlotUsage(slot=slot, **_totals_kwargs(r[3:]))
            entry.by_slot.append(slot_usage)
            entry.total = _add_totals(entry.total, slot_usage)
        total = UsageTotals()
        for slot_usage in by_slot:
            total = _add_totals(total, slot_usage)
        return UsageSummary(
            total=total,
            by_slot=by_slot,
            by_job=sorted(jobs.values(), key=lambda j: j.started, reverse=True),
            by_session=sorted(sessions.values(), key=lambda x: x.started, reverse=True),
        )


def _totals_kwargs(values: Sequence[Any]) -> dict[str, int]:
    names = (
        "calls",
        "failed_calls",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "latency_ms",
    )
    return {n: int(v or 0) for n, v in zip(names, values, strict=True)}


def _add_totals(a: UsageTotals, b: UsageTotals) -> UsageTotals:
    return UsageTotals(
        calls=a.calls + b.calls,
        failed_calls=a.failed_calls + b.failed_calls,
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        reasoning_tokens=a.reasoning_tokens + b.reasoning_tokens,
        latency_ms=a.latency_ms + b.latency_ms,
    )


# Stored in their own columns; everything else rides in the JSONB body, so a new
# field is stored by default.
_REVIEW_COLUMN_FIELDS = {"program_id", "plo_fingerprint", "model", "created_at"}


class PLOReportRepository:
    """The latest PLO report per program (phase 6), one row replaced in place."""

    async def get(self, program_id: str) -> PLOReport | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(PLOReportTable, program_id)
            if row is None:
                return None
            return PLOReport(
                program_id=row.program_id,
                plo_fingerprint=row.plo_fingerprint,
                created_at=row.created_at,
                report=row.report,
            )

    async def upsert(self, report: PLOReport) -> None:
        created_at = report.created_at
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(UTC).replace(tzinfo=None)
        async with AsyncSessionLocal() as session:
            existing = await session.get(PLOReportTable, report.program_id)
            if existing is None:
                session.add(
                    PLOReportTable(
                        program_id=report.program_id,
                        plo_fingerprint=report.plo_fingerprint,
                        created_at=created_at,
                        report=report.report,
                    )
                )
            else:
                existing.plo_fingerprint = report.plo_fingerprint
                existing.created_at = created_at
                existing.report = report.report
            await session.commit()

    async def delete_by_program(self, program_id: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(PLOReportTable).where(PLOReportTable.program_id == program_id)
            )
            await session.commit()


class PLOReviewRepository:
    """The latest PLO set review per program. Advisory data; see stages/plo_review.py."""

    async def get(self, program_id: str) -> PLOSetReview | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(PLOReviewTable, program_id)
            if row is None:
                return None
            return PLOSetReview.model_validate(
                {
                    **row.review,
                    "program_id": row.program_id,
                    "plo_fingerprint": row.plo_fingerprint,
                    "model": row.model,
                    "created_at": row.created_at,
                }
            )

    async def upsert(self, review: PLOSetReview) -> None:
        body = review.model_dump(mode="json", exclude=_REVIEW_COLUMN_FIELDS)
        async with AsyncSessionLocal() as session:
            existing = await session.get(PLOReviewTable, review.program_id)
            if existing is None:
                session.add(
                    PLOReviewTable(
                        program_id=review.program_id,
                        plo_fingerprint=review.plo_fingerprint,
                        model=review.model,
                        created_at=review.created_at,
                        review=body,
                    )
                )
            else:
                existing.plo_fingerprint = review.plo_fingerprint
                existing.model = review.model
                existing.created_at = review.created_at
                existing.review = body
            await session.commit()

    async def delete_by_program(self, program_id: str) -> int:
        async with AsyncSessionLocal() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    delete(PLOReviewTable).where(PLOReviewTable.program_id == program_id)
                ),
            )
            await session.commit()
            return result.rowcount


class CheckpointRepository:
    async def save(self, checkpoint: StageCheckpoint) -> None:
        async with AsyncSessionLocal() as session:
            data = _fix_datetimes(checkpoint.model_dump(mode="json"), CheckpointTable)
            existing = await session.get(CheckpointTable, checkpoint.checkpoint_id)
            if existing is None:
                session.add(CheckpointTable(**data))
            else:
                for k, v in data.items():
                    setattr(existing, k, v)
            await session.commit()

    async def get_pending(self, program_id: str) -> StageCheckpoint | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(CheckpointTable)
                .where(
                    CheckpointTable.program_id == program_id,
                    CheckpointTable.status == "pending",
                )
                .order_by(CheckpointTable.created_at.desc())
                .limit(1)
            )
            row = result.scalars().first()
            if row is None:
                return None
            return StageCheckpoint.model_validate(_row_to_dict(row))

    async def approve(self, checkpoint_id: str, reviewer: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(CheckpointTable)
                .where(CheckpointTable.checkpoint_id == checkpoint_id)
                .values(
                    status="approved",
                    reviewed_by=reviewer,
                    reviewed_at=datetime.utcnow(),
                )
            )
            await session.commit()


class SessionRepository:
    async def create(self, session: SessionInfo) -> SessionInfo:
        async with AsyncSessionLocal() as db:
            data = _fix_datetimes(session.model_dump(mode="json"), SessionTable)
            db.add(SessionTable(**data))
            await db.commit()
        return session

    async def get(self, session_id: str) -> SessionInfo | None:
        async with AsyncSessionLocal() as db:
            row = await db.get(SessionTable, session_id)
            if row is None:
                return None
            return SessionInfo.model_validate(_row_to_dict(row))

    async def list_by_program(self, program_id: str) -> list[SessionInfo]:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(SessionTable)
                .where(SessionTable.program_id == program_id)
                .order_by(SessionTable.created_at.desc())
            )
            rows = result.scalars().all()
            return [SessionInfo.model_validate(_row_to_dict(row)) for row in rows]

    async def set_status(self, session_id: str, status: str, message: str | None = None) -> None:
        """Set the status, and the message explaining it when there is one.

        Writes the same column `set_suspended` uses — it is the session's
        message, not only a suspension's — and only when a message is given, so
        resuming a run does not blank the note from the checkpoint it came from.
        """
        async with AsyncSessionLocal() as db:
            row = await db.get(SessionTable, session_id)
            if row is None:
                return
            row.status = status
            if message is not None:
                row.suspended_message = message
            row.updated_at = datetime.utcnow()
            await db.commit()

    async def fail_all_running(self, message: str) -> int:
        """Startup sweep: a graph run is an in-process task, so a session still
        `running` belongs to a dead process. Writes the message to the same
        column `set_status` does."""
        async with AsyncSessionLocal() as db:
            result = cast(
                CursorResult[Any],
                await db.execute(
                    update(SessionTable)
                    .where(SessionTable.status == "running")
                    .values(
                        status="failed", suspended_message=message, updated_at=datetime.utcnow()
                    )
                ),
            )
            await db.commit()
            return result.rowcount

    async def delete(self, program_id: str, session_id: str) -> bool:
        """Delete one session row, scoped to its program.

        Returns False if it does not exist OR belongs to another program — the
        same 404 either way, so the caller cannot learn that an id exists under
        a program they did not ask about.

        Only the row. The checkpoint thread it names lives in LangGraph's own
        schema with no foreign key back here, so deleting this row is what makes
        that thread unreachable rather than what removes it; the route drops the
        thread first and `prune_threads` is the sweep for whatever still slips
        through.
        """
        async with AsyncSessionLocal() as db:
            row = await db.get(SessionTable, session_id)
            if row is None or row.program_id != program_id:
                return False
            await db.delete(row)
            await db.commit()
            return True

    async def set_suspended(self, session_id: str, stage: str, message: str) -> None:
        async with AsyncSessionLocal() as db:
            row = await db.get(SessionTable, session_id)
            if row is None:
                return
            row.status = "suspended"
            row.current_stage = stage
            row.suspended_message = message
            row.updated_at = datetime.utcnow()
            await db.commit()


class JobRepository:
    """Background stage runs (api/jobs.py). `label_th` is not stored; the
    runner fills it on the way out."""

    async def insert(self, job: JobInfo) -> None:
        async with AsyncSessionLocal() as session:
            data = job.model_dump(exclude={"label_th"})
            session.add(JobTable(**data))
            await session.commit()

    async def get(self, job_id: str) -> JobInfo | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(JobTable, job_id)
            return None if row is None else JobInfo.model_validate(_row_to_dict(row))

    async def list_by_program(
        self, program_id: str, *, active_only: bool = False, limit: int = 20
    ) -> list[JobInfo]:
        async with AsyncSessionLocal() as session:
            stmt = select(JobTable).where(JobTable.program_id == program_id)
            if active_only:
                stmt = stmt.where(JobTable.status == "running")
            stmt = stmt.order_by(JobTable.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [JobInfo.model_validate(_row_to_dict(r)) for r in rows]

    async def find_running(self, program_id: str) -> JobInfo | None:
        running = await self.list_by_program(program_id, active_only=True, limit=1)
        return running[0] if running else None

    async def finish(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: Any | None = None,
        error_th: str | None = None,
    ) -> bool:
        """Record the outcome. False when the row is gone (program deleted
        while the job ran) — never raises for that."""
        async with AsyncSessionLocal() as session:
            row = await session.get(JobTable, job_id)
            if row is None:
                return False
            row.status = status
            row.result = result
            row.error_th = error_th
            row.finished_at = datetime.utcnow()
            await session.commit()
            return True

    async def fail_all_running(self, message: str) -> int:
        """Startup sweep: a job still `running` belongs to a dead process."""
        async with AsyncSessionLocal() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(JobTable)
                    .where(JobTable.status == "running")
                    .values(status="failed", error_th=message, finished_at=datetime.utcnow())
                ),
            )
            await session.commit()
            return result.rowcount


# The two callers that write to llm_cache, as stored in LLMCacheTable.kind.
# They live beside the repository rather than in prune_cache because they are
# column values, and a stage reaching into the pruning tool for the name of the
# row it is writing has the dependency backwards.
CACHE_KIND_EXTRACTION = "extraction"
CACHE_KIND_CLUSTERING = "clustering"


class LLMCacheRepository:
    async def get(self, evidence_hash: str) -> tuple[str, str] | None:
        """Return (model, result_json) for the given hash, or None on miss."""
        async with AsyncSessionLocal() as session:
            row = await session.get(LLMCacheTable, evidence_hash)
            if row is None:
                return None
            return (row.model, row.result_json)

    async def set(
        self,
        evidence_hash: str,
        model: str,
        result_json: str,
        *,
        kind: str,
        contract: str,
    ) -> None:
        """Store one payload, recording which caller and contract produced it.

        `kind` and `contract` are keyword-only because neither is read on the way
        back out: the hash already covers both, so they cannot change what gets
        hit. They exist for prune_cache, which has to explain why a row is
        unreachable, and passing them positionally next to `model` would make
        three interchangeable strings in a row.
        """
        async with AsyncSessionLocal() as session:
            existing = await session.get(LLMCacheTable, evidence_hash)
            if existing is None:
                session.add(
                    LLMCacheTable(
                        evidence_hash=evidence_hash,
                        kind=kind,
                        model=model,
                        contract=contract,
                        result_json=result_json,
                        created_at=datetime.utcnow(),
                    )
                )
            else:
                # created_at is deliberately left alone — see LLMCacheTable.
                existing.kind = kind
                existing.model = model
                existing.contract = contract
                existing.result_json = result_json
            await session.commit()

    async def all_rows(self) -> list[LLMCacheTable]:
        """Every row, for the sweep. The payloads come along: they are the bulk
        of the table, but a sweep that streamed keys and then fetched each row
        would hold the table open for the length of a maintenance run to save
        memory nobody is short of at this size."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(LLMCacheTable))
            return list(result.scalars().all())

    async def delete_hashes(self, hashes: Sequence[str]) -> int:
        """Drop the named rows, returning how many went. No-op on an empty list —
        a bare `IN ()` is a syntax error in Postgres, and "delete nothing" is the
        normal outcome of a sweep that found nothing."""
        if not hashes:
            return 0
        async with AsyncSessionLocal() as session:
            # Same cast as delete_cascade: execute() is typed as returning a
            # Result, and only the CursorResult a DML statement actually yields
            # carries rowcount.
            result = cast(
                CursorResult[Any],
                await session.execute(
                    delete(LLMCacheTable).where(LLMCacheTable.evidence_hash.in_(list(hashes)))
                ),
            )
            await session.commit()
            return result.rowcount or 0
