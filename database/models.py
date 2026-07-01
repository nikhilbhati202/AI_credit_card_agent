"""SQLAlchemy models for the six-table schema (architecture doc, Section 12: ER Diagram).

Written before the first Alembic migration per the implementation guide, Section 6.1:
migrations are generated from these models, never hand-written first.
"""

import enum
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# text-embedding-3-small produces 1536-dimensional vectors (Section 9.1). If the embedding
# model changes, this dimension and the stored data must be migrated together (Section 9.2).
EMBEDDING_DIM = 1536


class Base(DeclarativeBase):
    pass


class RewardUnit(enum.StrEnum):
    """Known reward-unit types (risk analysis, Section 17: reward_unit must be a validated enum)."""

    POINTS = "points"
    MILES = "miles"
    CASHBACK = "cashback"


class CapType(enum.StrEnum):
    MONTHLY = "monthly"
    ANNUAL = "annual"


class RewardRuleStatus(enum.StrEnum):
    """Mirrors the human-review workflow in Section 11.2: rows start pending_review."""

    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"
    SUPERSEDED = "superseded"


class CardDocument(Base):
    """A single versioned issuer document (Section 6.5: never overwritten, only superseded)."""

    __tablename__ = "card_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")
    reward_rules: Mapped[list["RewardRule"]] = relationship(back_populates="document")
    transfer_partners: Mapped[list["TransferPartner"]] = relationship(back_populates="document")


class DocumentChunk(Base):
    """A retrievable chunk of a card document, embedded for vector search (Sections 8-9)."""

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("card_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized copy of card_name to avoid a join on the hot retrieval path (doc, Section 12.2).
    card_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    # Carries embedding model name/version (Section 9.2) plus any other chunk-time metadata.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[CardDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class RewardRule(Base):
    """An extracted, structured reward rule (Section 11), gated by confidence_score/status."""

    __tablename__ = "reward_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("card_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    card_name: Mapped[str] = mapped_column(String(255), nullable=False)
    spend_category: Mapped[str] = mapped_column(String(100), nullable=False)
    reward_rate: Mapped[float] = mapped_column(Float, nullable=False)
    reward_unit: Mapped[RewardUnit] = mapped_column(Enum(RewardUnit), nullable=False)
    cap_type: Mapped[CapType | None] = mapped_column(Enum(CapType), nullable=True)
    cap_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    exclusion_flag: Mapped[bool] = mapped_column(default=False)
    milestone_flag: Mapped[bool] = mapped_column(default=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[RewardRuleStatus] = mapped_column(
        Enum(RewardRuleStatus), nullable=False, default=RewardRuleStatus.PENDING_REVIEW
    )
    conflict_flag: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[CardDocument] = relationship(back_populates="reward_rules")

    __table_args__ = (Index("ix_reward_rules_card_category", "card_name", "spend_category"),)


class TransferPartner(Base):
    """A point-transfer partner and ratio for a card (Section 10.11, FR-7)."""

    __tablename__ = "transfer_partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("card_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )
    card_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    partner_name: Mapped[str] = mapped_column(String(255), nullable=False)
    transfer_ratio_from: Mapped[float] = mapped_column(Float, nullable=False)
    transfer_ratio_to: Mapped[float] = mapped_column(Float, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[CardDocument] = relationship(back_populates="transfer_partners")


class UserProfile(Base):
    """Persisted user identity, owned cards, and long-term memory (FR-1, FR-8)."""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    cards_owned: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    conversation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    monthly_spend_pattern: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RecommendationLog(Base):
    """Audit trail of every query/answer, for compliance (FR-11) and evaluation (FR-12)."""

    __tablename__ = "recommendation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retrieved_chunk_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    tool_calls: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    final_answer: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    feedback: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_recommendation_logs_user_created", "user_id", "created_at"),)
