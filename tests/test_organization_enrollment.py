"""Integration tests for client enrollment and platform organization management."""

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from veristock.app import create_app
from veristock.auth.tokens import TokenService
from veristock.core.config import Environment, Settings
from veristock.core.database import Base
from veristock.identity import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    Permission,
    Role,
    RolePermission,
    User,
)
from veristock.organizations.models import (
    Branch,
    OrganizationContact,
    OrganizationEnrollment,
)
from veristock.workforce.models import EmployeeProfile


def test_business_enrollment_requires_platform_approval(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'organization-enrollment.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    applicant_id = str(uuid4())
    platform_user_id = str(uuid4())
    platform_org_id = str(uuid4())
    platform_membership_id = str(uuid4())
    platform_role_id = str(uuid4())
    client_admin_role_id = str(uuid4())
    permission_id = str(uuid4())
    try:
        import asyncio

        async def seed() -> None:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with factory() as session:
                session.add_all(
                    [
                        User(
                            id=applicant_id,
                            identifier="owner@example.com",
                            password_hash="not-used",
                        ),
                        User(
                            id=platform_user_id,
                            identifier="ops@example.com",
                            password_hash="not-used",
                        ),
                        Organization(
                            id=platform_org_id,
                            kind="platform",
                            legal_name="Veristock",
                        ),
                        OrganizationMembership(
                            id=platform_membership_id,
                            organization_id=platform_org_id,
                            user_id=platform_user_id,
                            status="active",
                        ),
                        Role(
                            id=platform_role_id,
                            code="platform_owner",
                            name="Platform Owner",
                            scope="platform",
                        ),
                        Role(
                            id=client_admin_role_id,
                            code="client_admin",
                            name="Client Administrator",
                            scope="client",
                        ),
                        Permission(
                            id=permission_id,
                            code="organization.manage",
                            description="Manage client organizations",
                        ),
                        MembershipRole(
                            membership_id=platform_membership_id,
                            role_id=platform_role_id,
                        ),
                        RolePermission(
                            role_id=platform_role_id,
                            permission_id=permission_id,
                        ),
                    ]
                )
                await session.commit()

        asyncio.run(seed())
    finally:
        pass

    settings = Settings(environment=Environment.TEST, database_url=database_url)
    tokens = TokenService("x" * 32)
    applicant_token = tokens.create(
        applicant_id, timedelta(minutes=10), token_type="access"
    )
    platform_token = tokens.create(
        platform_user_id, timedelta(minutes=10), token_type="access"
    )
    try:
        with TestClient(create_app(settings, access_token_service=tokens)) as client:
            applicant_headers = {"Authorization": f"Bearer {applicant_token}"}
            submitted = client.post(
                "/api/organizations/enrollments",
                headers=applicant_headers,
                json={
                    "legal_name": "Acme Retail Limited",
                    "trading_name": "Acme Retail",
                    "timezone": "Africa/Nairobi",
                    "contact_name": "Business Owner",
                    "contact_email": "owner@example.com",
                    "contact_phone": "+254700000000",
                },
            )
            assert submitted.status_code == 201
            enrollment = submitted.json()
            assert enrollment["status"] == "pending"
            assert enrollment["organization_id"] is None

            duplicate = client.post(
                "/api/organizations/enrollments",
                headers=applicant_headers,
                json={
                    "legal_name": "Acme Retail Limited",
                    "contact_name": "Business Owner",
                    "contact_email": "owner@example.com",
                },
            )
            assert duplicate.status_code == 409

            platform_headers = {
                "Authorization": f"Bearer {platform_token}",
                "X-Organization-ID": platform_org_id,
            }
            pending = client.get(
                "/api/organizations/enrollments", headers=platform_headers
            )
            assert pending.status_code == 200
            assert len(pending.json()) == 1

            approved = client.post(
                f"/api/organizations/enrollments/{enrollment['id']}/approve",
                headers=platform_headers,
                json={"review_note": "Business details verified"},
            )
            assert approved.status_code == 200
            result = approved.json()
            assert result["status"] == "approved"
            assert result["organization_id"]

            organizations = client.get(
                "/api/organizations?status=active", headers=platform_headers
            )
            assert organizations.status_code == 200
            assert len(organizations.json()) == 1
            assert organizations.json()[0]["legal_name"] == "Acme Retail Limited"
            assert organizations.json()[0]["active_members"] == 1

            client_headers = {
                "Authorization": f"Bearer {applicant_token}",
                "X-Organization-ID": result["organization_id"],
            }
            current = client.get(
                "/api/organizations/current", headers=client_headers
            )
            assert current.status_code == 200
            assert current.json()["id"] == result["organization_id"]

            suspended = client.patch(
                f"/api/organizations/{result['organization_id']}/status",
                headers=platform_headers,
                json={"status": "suspended"},
            )
            assert suspended.status_code == 200
            assert suspended.json()["status"] == "suspended"

            denied = client.get(
                "/api/organizations/current", headers=client_headers
            )
            assert denied.status_code == 403
    finally:
        import asyncio

        asyncio.run(engine.dispose())
