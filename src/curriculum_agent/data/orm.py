from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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
    degree_level: Mapped[str] = mapped_column(String(20))
    duration_years: Mapped[int] = mapped_column(Integer)
    faculty: Mapped[str] = mapped_column(Text)
    university: Mapped[str] = mapped_column(Text)
    vision_th: Mapped[str] = mapped_column(Text)
    student_identity_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    professional_council: Mapped[str | None] = mapped_column(Text, nullable=True)
    accreditation_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_benchmark_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    program_objectives_th: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)


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
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)


class SkillTable(Base):
    __tablename__ = "skills"

    skill_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    skill_name_th: Mapped[str] = mapped_column(Text)
    skill_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_type: Mapped[str] = mapped_column(String(20))
    is_subject_specific: Mapped[bool] = mapped_column(Boolean)
    source_evidence_id: Mapped[str] = mapped_column(String, ForeignKey("evidence.evidence_id"))
    extraction_method: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)


class ClusterTable(Base):
    __tablename__ = "clusters"

    cluster_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    canonical_name_th: Mapped[str] = mapped_column(Text)
    canonical_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_th: Mapped[str] = mapped_column(Text)
    skill_type: Mapped[str] = mapped_column(String(20))
    is_subject_specific: Mapped[bool] = mapped_column(Boolean)
    member_skill_ids: Mapped[list] = mapped_column(JSONB)
    source_evidence_ids: Mapped[list] = mapped_column(JSONB)
    stakeholder_coverage: Mapped[dict] = mapped_column(JSONB, default=dict)
    demand_score: Mapped[float] = mapped_column(Float)
    is_common_need: Mapped[bool] = mapped_column(Boolean, default=False)
    sample_quotes_th: Mapped[list] = mapped_column(JSONB, default=list)


class PLOTable(Base):
    __tablename__ = "plos"

    plo_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    statement_th: Mapped[str] = mapped_column(Text)
    statement_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str] = mapped_column(String(20))
    bloom_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    krathwohl_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_subject_specific: Mapped[bool] = mapped_column(Boolean)
    action_verb_th: Mapped[str] = mapped_column(Text)
    smart_check: Mapped[dict] = mapped_column(JSONB)
    source_cluster_ids: Mapped[list] = mapped_column(JSONB)
    source_evidence_ids: Mapped[list] = mapped_column(JSONB, default=list)
    rationale_th: Mapped[str] = mapped_column(Text)
    distinctive_feature_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_rationale_th: Mapped[str | None] = mapped_column(Text, nullable=True)


class YLOTable(Base):
    __tablename__ = "ylos"

    ylo_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    parent_plo_id: Mapped[str] = mapped_column(String, ForeignKey("plos.plo_id"))
    year: Mapped[int] = mapped_column(Integer)
    statement_th: Mapped[str] = mapped_column(Text)
    statement_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    bloom_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    krathwohl_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action_verb_th: Mapped[str] = mapped_column(Text)
    smart_check: Mapped[dict] = mapped_column(JSONB)
    rationale_th: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)


class CheckpointTable(Base):
    __tablename__ = "checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String, primary_key=True)
    program_id: Mapped[str] = mapped_column(String, ForeignKey("programs.program_id"))
    stage: Mapped[str] = mapped_column(String(30))
    artifacts: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    designer_notes_th: Mapped[str | None] = mapped_column(Text, nullable=True)
    edits: Mapped[dict] = mapped_column(JSONB, default=dict)


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
    __tablename__ = "llm_extraction_cache"

    # SHA-256(text_slice + "\x00" + model_name) — model name is baked into the hash
    evidence_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(128))
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
