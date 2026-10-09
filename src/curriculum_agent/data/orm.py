from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProgramTable(Base):
    __tablename__ = "programs"

    program_id: Mapped[str] = mapped_column(String, primary_key=True)
    name_th: Mapped[str] = mapped_column(Text)
    name_en: Mapped[str] = mapped_column(Text)
    field: Mapped[str] = mapped_column(Text)
    isced_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    degree_level: Mapped[str] = mapped_column(String(20))
    duration_years: Mapped[int] = mapped_column(Integer)
    faculty: Mapped[str] = mapped_column(Text)
    university: Mapped[str] = mapped_column(Text)
    # Nullable in the column, "" on the Pydantic side, following isced_code and
    # name_th respectively. The repository normalises None to "" on read: a None
    # reaching the extraction cache key would hash the string "None".
    scope_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    program_goals_th: Mapped[list[str]] = mapped_column(JSONB)
    professional_council: Mapped[str | None] = mapped_column(Text, nullable=True)
    accreditation_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_benchmark_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    program_objectives_th: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    # Set only by POST /programs/{id}/copy. Not a ForeignKey: deleting the
    # source program must not reach its copies.
    copied_from: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceTable(Base):
    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    stakeholder_type: Mapped[str] = mapped_column(String(50))
    source_name: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_th: Mapped[str] = mapped_column(Text)
    raw_text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime)
    classification: Mapped[str] = mapped_column(String(20), default="unclassified")
    classification_rationale_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'metadata' is a SQLAlchemy reserved attribute name — stored as extra_metadata
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SkillTable(Base):
    __tablename__ = "skills"

    skill_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    skill_name_th: Mapped[str] = mapped_column(Text)
    skill_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    ksec_category: Mapped[str] = mapped_column(String(2))
    bloom_level: Mapped[str] = mapped_column(String(20))
    evidence_span_th: Mapped[str] = mapped_column(Text)
    source_evidence_id: Mapped[str] = mapped_column(String, ForeignKey("evidence.evidence_id"))
    source_stakeholder_type: Mapped[str] = mapped_column(String(50), default="employer")
    classification: Mapped[str] = mapped_column(String(20), default="unclassified")
    is_field_relevant: Mapped[bool] = mapped_column(Boolean, default=True)
    is_graduate_capability: Mapped[bool] = mapped_column(Boolean, default=True)
    extraction_method: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)


class NeedTable(Base):
    __tablename__ = "needs"

    need_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    statement_th: Mapped[str] = mapped_column(Text)
    statement_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NOT NULL with an empty server_default, not nullable: the column was
    # backfilled rather than left open, so "no reason recorded" is a string a
    # reader can see rather than a NULL every consumer has to branch on. The
    # default catches a row written by a path that predates the field — a
    # suspended checkpoint resuming — without failing the insert.
    rationale_th: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    ksec_category: Mapped[str] = mapped_column(String(2))
    bloom_level: Mapped[str] = mapped_column(String(20))
    member_skill_ids: Mapped[list[str]] = mapped_column(JSONB)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSONB)
    stakeholder_coverage: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    source_stakeholder_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    freq: Mapped[int] = mapped_column(Integer)
    demand_score: Mapped[float] = mapped_column(Float)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    classification_coverage: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    in_field_skill_count: Mapped[int] = mapped_column(Integer, default=0)
    graduate_capability_skill_count: Mapped[int] = mapped_column(Integer, default=0)


class PLOTable(Base):
    __tablename__ = "plos"

    # Composite PK. plo_id alone (PLO1..PLOn / OPT1..OPTn) repeats across every
    # program, so a single-column PK let one program's synthesis run move
    # another program's PLO1 to itself via upsert-by-plo_id and overwrite it.
    # A PLO's identity is (program, plo_id), never plo_id alone.
    __table_args__ = (PrimaryKeyConstraint("program_id", "plo_id", name="plos_pkey"),)

    plo_id: Mapped[str] = mapped_column(String)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    statement_th: Mapped[str] = mapped_column(Text)
    statement_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    bloom_level: Mapped[str] = mapped_column(String(20))
    action_verb_th: Mapped[str] = mapped_column(Text)
    # Serialized SMARTCheck model — bool criteria, optional notes string, and
    # the findings list. The findings ride inside this existing column on
    # purpose: it is already JSONB, so the richest part of a verdict needed no
    # migration and rows written before it deserialise on the model's default.
    smart_check: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_need_ids: Mapped[list[str]] = mapped_column(JSONB)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    rationale_th: Mapped[str] = mapped_column(Text)
    distinctive_feature_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    smart_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    smart_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    soft_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # String(20) rather than a PG enum: this project has never created one, and
    # a fifth value later would otherwise need a type migration.
    smart_validated_by: Mapped[str] = mapped_column(String(20), default="legacy")
    smart_diagnosis_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)


class PLOReviewTable(Base):
    """The advisory PLO set review, one row per program (stages/plo_review.py).

    Keyed by program alone: only the latest review is kept, and a new one
    replaces it. `plo_fingerprint` says which PLO set it was made from; the
    findings ride in one JSONB column because nothing queries inside them.
    """

    __tablename__ = "plo_reviews"

    program_id: Mapped[str] = mapped_column(
        String, ForeignKey("programs.program_id"), primary_key=True
    )
    plo_fingerprint: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    review: Mapped[dict[str, Any]] = mapped_column(JSONB)


class JobTable(Base):
    """A background stage run (api/jobs.py). `result` is the JSON body the
    route used to return synchronously; `error_th` is what the designer reads
    when it failed. String kind/status, not PG enums (project convention)."""

    __tablename__ = "jobs"
    # Matches the migration: `find_running` and the active-only listing filter on both.
    __table_args__ = (Index("ix_jobs_program_status", "program_id", "status"),)

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    error_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CheckpointTable(Base):
    __tablename__ = "checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    stage: Mapped[str] = mapped_column(String(30))
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    designer_notes_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    edits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class SessionTable(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    thread_id: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    suspended_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class LLMCacheTable(Base):
    # Not "llm_extraction_cache": skill extraction was the only caller when the
    # table was created, and LLM clustering has shared it since. The old name
    # read as a promise that clustering results were not cached.
    __tablename__ = "llm_cache"

    # SHA-256 over everything that decides the answer — the input text, the
    # model, the contract fingerprint, and whatever else the caller varies.
    evidence_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Which caller wrote the row: prune_cache.EXTRACTION or .CLUSTERING. Already
    # implied by the contract fingerprint, so it changes nothing about what gets
    # hit; it is a column so a sweep can judge each caller against the slot that
    # caller actually resolves to, which differ.
    kind: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    # Short hash of the response schema and the prompt that produced the payload
    # (_EXTRACTION_CONTRACT / _CLUSTERING_CONTRACT). Also inside the key, and a
    # column for the same reason: editing a prompt orphans every row it wrote,
    # and a hash cannot be asked which prompt produced it.
    contract: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)
    # When the payload was first computed — never touched on overwrite, and that
    # is the intended reading. Everything that decides the payload is inside the
    # key, so a second write to a live hash stores the value already there; the
    # first computation is the row's real age, which is what --older-than wants.
    created_at: Mapped[datetime] = mapped_column(DateTime)
