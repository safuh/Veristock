"""Organization tenancy and role-based authorization persistence."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
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


class Organization(Base):
    """Platform or client organization."""

    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("kind IN ('platform', 'client')", name="ck_organizations_kind"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'archived')",
            name="ck_organizations_status",
        ),
        Index("ix_organizations_kind_status", "kind", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(240), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Nairobi")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrganizationMembership(Base):
    """A user's access relationship with an organization."""

    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_memberships_status",
        ),
        Index("ix_memberships_user_status", "user_id", "status"),
        Index("ix_memberships_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Role(Base):
    """Named permission bundle, scoped to platform or client organizations."""

    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint("scope IN ('platform', 'client')", name="ck_roles_scope"),
        UniqueConstraint("code", name="uq_roles_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Permission(Base):
    """Stable permission identifier used by application policies."""

    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("code", name="uq_permissions_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)


class MembershipRole(Base):
    """Role granted to a user within one organization membership."""

    __tablename__ = "membership_roles"
    __table_args__ = (
        UniqueConstraint("membership_id", "role_id", name="uq_membership_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    membership_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organization_memberships.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )


class RolePermission(Base):
    """Permission included in a role."""

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    role_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )
