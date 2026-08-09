from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update

from curriculum_agent.data.orm import (
    Base,
    CheckpointTable,
    EvidenceTable,
    LLMCacheTable,
    NeedTable,
    PLOTable,
    ProgramTable,
    SessionTable,
    SkillTable,
)
from curriculum_agent.data.postgres import AsyncSessionLocal
from curriculum_agent.models import (
    PLO,
    ExtractedSkill,
    Need,
    ProgramMetadata,
    ProgramSummary,
    SessionInfo,
    StageCheckpoint,
    StakeholderEvidence,
)


def _row_to_dict(row: Base) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns}


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
            return ProgramMetadata.model_validate(_row_to_dict(row))

    async def exists(self, program_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            row = await session.get(ProgramTable, program_id)
            return row is not None

    async def list_all(self) -> list[ProgramSummary]:
        """All programs (created_at DESC), each with its latest session state."""
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
                current_stage=(
                    latest[p.program_id].current_stage if p.program_id in latest else None
                ),
                session_status=(latest[p.program_id].status if p.program_id in latest else None),
            )
            for p in prog_rows
        ]

    async def delete_cascade(self, program_id: str) -> bool:
        """Hard-delete a program and everything under it, in one transaction.

        Deletes skills before evidence because SkillTable.source_evidence_id
        is a FK into EvidenceTable. Returns False (no-op) if program_id
        doesn't exist — the six prior deletes affect zero rows either way.
        """
        async with AsyncSessionLocal() as session:
            await session.execute(delete(SkillTable).where(SkillTable.program_id == program_id))
            await session.execute(delete(NeedTable).where(NeedTable.program_id == program_id))
            await session.execute(delete(PLOTable).where(PLOTable.program_id == program_id))
            await session.execute(
                delete(CheckpointTable).where(CheckpointTable.program_id == program_id)
            )
            await session.execute(delete(SessionTable).where(SessionTable.program_id == program_id))
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

    async def bulk_insert(self, needs: list[Need]) -> None:
        async with AsyncSessionLocal() as session:
            for need in needs:
                data = need.model_dump(mode="json")
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


class PLORepository:
    async def bulk_insert(self, plos: list[PLO]) -> None:
        async with AsyncSessionLocal() as session:
            for plo in plos:
                data = plo.model_dump(mode="json")
                existing = await session.get(PLOTable, plo.plo_id)
                if existing is None:
                    session.add(PLOTable(**data))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
            await session.commit()

    async def list_by_program(self, program_id: str) -> list[PLO]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PLOTable).where(PLOTable.program_id == program_id)
            )
            rows = result.scalars().all()
            return [PLO.model_validate(_row_to_dict(row)) for row in rows]


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

    async def set_status(self, session_id: str, status: str) -> None:
        async with AsyncSessionLocal() as db:
            row = await db.get(SessionTable, session_id)
            if row is None:
                return
            row.status = status
            row.updated_at = datetime.utcnow()
            await db.commit()

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


class LLMCacheRepository:
    async def get(self, evidence_hash: str) -> tuple[str, str] | None:
        """Return (model, result_json) for the given hash, or None on miss."""
        async with AsyncSessionLocal() as session:
            row = await session.get(LLMCacheTable, evidence_hash)
            if row is None:
                return None
            return (row.model, row.result_json)

    async def set(self, evidence_hash: str, model: str, result_json: str) -> None:
        async with AsyncSessionLocal() as session:
            existing = await session.get(LLMCacheTable, evidence_hash)
            if existing is None:
                session.add(
                    LLMCacheTable(
                        evidence_hash=evidence_hash,
                        model=model,
                        result_json=result_json,
                        created_at=datetime.utcnow(),
                    )
                )
            else:
                existing.model = model
                existing.result_json = result_json
            await session.commit()
