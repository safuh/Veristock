# ruff: noqa: E501
"""Tenant-owned branch and contact persistence models."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from veristock.core.database import Base


class Branch(Base):
    """A physical or operational location owned by one organization."""

    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_branches_org_code"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_branches_status"),
        Index("ix_branches_org_status", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    address_line_1: Mapped[str | None] = mapped_column(String(240))
    address_line_2: Mapped[str | None] = mapped_column(String(240))
    town: Mapped[str | None] = mapped_column(String(120))
    county: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(24))
    phone: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OrganizationContact(Base):
    """A named business contact belonging to a single tenant."""

    __tablename__ = "organization_contacts"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_contacts_status"),
        Index("ix_contacts_org_status", "organization_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    title: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OrganizationEnrollment(Base):
    """A business request to join Veristock, reviewed by platform operations."""

    __tablename__ = "organization_enrollments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_organization_enrollments_status",
        ),
        Index(
            "ix_org_enrollments_status_created",
            "status",
            "created_at",
        ),
        Index(
            "ix_org_enrollments_requester_status",
            "requester_user_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requester_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    legal_name: Mapped[str] = mapped_column(String(240), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(240))
    business_registration_number: Mapped[str | None] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Nairobi")
    contact_name: Mapped[str] = mapped_column(String(180), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    business_description: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    review_note: Mapped[str | None] = mapped_column(String(1000))
    organization_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="RESTRICT")
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
