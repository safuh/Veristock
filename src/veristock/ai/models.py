"""Persistence for auditable AI executions."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from veristock.core.database import Base


class AIExecutionRecord(Base):
    """Minimal metadata for one AI operation; never stores prompts or raw report data."""

    __tablename__ = "ai_execution_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'unavailable')",
            name="ck_ai_execution_records_status",
        ),
        CheckConstraint(
            "operation IN ('report_narrative')",
            name="ck_ai_execution_records_operation",
        ),
        Index(
            "ix_ai_execution_records_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_ai_execution_records_user_created",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(
        String(40), nullable=False, default="report_narrative"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(160))
    model_version: Mapped[str | None] = mapped_column(String(120))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(128))
    source_references: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    failure_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
