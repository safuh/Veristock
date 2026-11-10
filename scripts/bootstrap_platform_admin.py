"""One-time bootstrap for the initial Veristock platform owner.

Run after applying Alembic migrations:
    BOOTSTRAP_ADMIN_EMAIL=... BOOTSTRAP_ADMIN_PASSWORD=... \\
        uv run python scripts/bootstrap_platform_admin.py

The password is read only from the environment; it is never accepted as a CLI
argument or printed. The operation is idempotent for the same account.
"""

import asyncio
import os
import sys

from sqlalchemy import select

from veristock.auth import PasswordHasher
from veristock.core.config import get_settings
from veristock.core.database import create_engine, create_session_factory
from veristock.identity import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    Role,
    User,
)


async def bootstrap() -> None:
    """Create the platform organization and grant the initial owner role."""
    identifier = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    if not identifier or not password:
        raise SystemExit(
            "Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD in the environment."
        )
    if len(password) < 12:
        raise SystemExit("BOOTSTRAP_ADMIN_PASSWORD must contain at least 12 characters.")

    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            organizations = list(
                (
                    await session.scalars(
                        select(Organization).where(Organization.kind == "platform")
                    )
                ).all()
            )
            if len(organizations) > 1:
                raise SystemExit(
                    "More than one platform organization exists; resolve this manually."
                )
            if organizations:
                platform = organizations[0]
            else:
                platform = Organization(
                    kind="platform",
                    legal_name="Veristock Inventory Solutions Ltd.",
                    trading_name="Veristock",
                    timezone="Africa/Nairobi",
                )
                session.add(platform)
                await session.flush()

            user = await session.scalar(
                select(User).where(User.identifier == identifier)
            )
            if user is None:
                user = User(
                    identifier=identifier,
                    password_hash=PasswordHasher().hash(password),
                    status="active",
                )
                session.add(user)
                await session.flush()
            elif user.status != "active":
                raise SystemExit(
                    "The requested user exists but is not active; reactivate it explicitly."
                )

            membership = await session.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == platform.id,
                    OrganizationMembership.user_id == user.id,
                )
            )
            if membership is None:
                membership = OrganizationMembership(
                    organization_id=platform.id,
                    user_id=user.id,
                    status="active",
                )
                session.add(membership)
                await session.flush()
            elif membership.status != "active":
                raise SystemExit(
                    "The platform membership exists but is not active; resolve it explicitly."
                )

            owner_role = await session.scalar(
                select(Role).where(Role.code == "platform_owner", Role.scope == "platform")
            )
            if owner_role is None:
                raise SystemExit(
                    "The platform_owner role is missing. Apply Alembic migrations first."
                )

            assignment = await session.scalar(
                select(MembershipRole).where(
                    MembershipRole.membership_id == membership.id,
                    MembershipRole.role_id == owner_role.id,
                )
            )
            if assignment is None:
                session.add(
                    MembershipRole(
                        membership_id=membership.id,
                        role_id=owner_role.id,
                    )
                )
            await session.commit()
            print(f"Platform owner ready: {identifier} ({user.id})")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(bootstrap())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Bootstrap failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
