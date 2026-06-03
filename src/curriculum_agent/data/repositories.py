from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update

from curriculum_agent.data.orm import (
    CheckpointTable,
    ClusterTable,
    EvidenceTable,
    LLMCacheTable,
    PLOTable,
    ProgramTable,
    SessionTable,
    SkillTable,
    YLOTable,
)
from curriculum_agent.data.postgres import AsyncSessionLocal
from curriculum_agent.models import (
    PLO,
    YLO,
    ExtractedSkill,
    ProgramMetadata,
    SessionInfo,
    SkillCluster,
    StageCheckpoint,
    StakeholderEvidence,
    YLOMatrix,
)


def _row_to_dict(row) -> dict:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns}


def _fix_datetimes(data: dict, table_cls: type) -> dict:
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

    async def get(self, program_id: str) -> ProgramMetadata | None:
        async with AsyncSessionLocal() as session:
            row = await session.get(ProgramTable, program_id)
            if row is None:
                return None
            return ProgramMetadata.model_validate(_row_to_dict(row))


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


class SkillRepository:
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


class ClusterRepository:
    async def bulk_insert(self, clusters: list[SkillCluster]) -> None:
        async with AsyncSessionLocal() as session:
            for cluster in clusters:
                data = cluster.model_dump(mode="json")
                existing = await session.get(ClusterTable, cluster.cluster_id)
                if existing is None:
                    session.add(ClusterTable(**data))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
            await session.commit()

    async def list_by_program(self, program_id: str) -> list[SkillCluster]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClusterTable).where(ClusterTable.program_id == program_id)
            )
            rows = result.scalars().all()
            return [SkillCluster.model_validate(_row_to_dict(row)) for row in rows]


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


class YLORepository:
    async def save_matrix(self, matrix: YLOMatrix) -> None:
        plo_repo = PLORepository()
        await plo_repo.bulk_insert(matrix.plos)
        async with AsyncSessionLocal() as session:
            for ylo in matrix.ylos:
                data = ylo.model_dump(mode="json")
                existing = await session.get(YLOTable, ylo.ylo_id)
                if existing is None:
                    session.add(YLOTable(**data))
                else:
                    for k, v in data.items():
                        setattr(existing, k, v)
            await session.commit()

    async def get_matrix(self, program_id: str) -> YLOMatrix | None:
        plo_repo = PLORepository()
        plos = await plo_repo.list_by_program(program_id)
        if not plos:
            return None
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(YLOTable).where(YLOTable.program_id == program_id)
            )
            ylo_rows = result.scalars().all()
            ylos = [YLO.model_validate(_row_to_dict(row)) for row in ylo_rows]
        return YLOMatrix(program_id=program_id, plos=plos, ylos=ylos)


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

    async def set_suspended(
        self, session_id: str, stage: str, message: str
    ) -> None:
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
                existing.created_at = datetime.utcnow()
            await session.commit()
