"""Tenant-owned metadata for stocktake evidence objects."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from veristock.core.database import Base


class StocktakeEvidence(Base):
    __tablename__ = "stocktake_evidence"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="ck_stocktake_evidence_size_positive"),
        CheckConstraint(
            "media_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_stocktake_evidence_media_type",
        ),
        UniqueConstraint("storage_key", name="uq_stocktake_evidence_storage_key"),
        Index(
            "ix_stocktake_evidence_org_stocktake",
            "organization_id",
            "stocktake_id",
            "created_at",
        ),
        Index("ix_stocktake_evidence_observation", "observation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    stocktake_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False
    )
    round_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktake_rounds.id", ondelete="RESTRICT"), nullable=False
    )
    observation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stocktake_observations.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    uploaded_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
