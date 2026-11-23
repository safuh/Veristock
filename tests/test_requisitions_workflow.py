"""Purchase requisition submission, segregation of duties and decision history."""

import asyncio
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
from veristock.inventory.models import InventoryItem, Supplier
from veristock.organizations.models import Branch


def test_requisition_requires_independent_approver_and_keeps_history(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'requisitions.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    requester_id, approver_id, org_id, branch_id, item_id, supplier_id = (
        str(uuid4()) for _ in range(6)
    )
    role_id = str(uuid4())

    async def seed() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all(
                [
                    User(id=requester_id, identifier="requester@example.test", password_hash="x"),
                    User(id=approver_id, identifier="approver@example.test", password_hash="x"),
                    Organization(id=org_id, kind="client", legal_name="Requisition Tenant"),
                    OrganizationMembership(
                        id=str(uuid4()),
                        organization_id=org_id,
                        user_id=requester_id,
                        status="active",
                    ),
                    OrganizationMembership(
                        id=str(uuid4()),
                        organization_id=org_id,
                        user_id=approver_id,
                        status="active",
                    ),
                    Role(
                        id=role_id,
                        code="inventory_manager",
                        name="Inventory Manager",
                        scope="client",
                    ),
                    Branch(id=branch_id, organization_id=org_id, code="MAIN", name="Main Branch"),
                    InventoryItem(
                        id=item_id,
                        organization_id=org_id,
                        sku="PAPER-001",
                        name="Printer paper",
                        base_unit_code="REAM",
                        status="active",
                    ),
                    Supplier(
                        id=supplier_id,
                        organization_id=org_id,
                        code="SUP-001",
                        name="Office Supplies Ltd",
                        default_currency="KES",
                        status="active",
                    ),
                ]
            )
            for membership in (requester_id, approver_id):
                session.add(
                    MembershipRole(
                        membership_id=next(
                            x.id
                            for x in session.new
                            if isinstance(x, OrganizationMembership) and x.user_id == membership
                        ),
                        role_id=role_id,
                    )
                )
            for code in ("inventory.manage", "inventory.read"):
                permission = Permission(id=str(uuid4()), code=code, description=code)
                session.add(permission)
                session.add(RolePermission(role_id=role_id, permission_id=permission.id))
            await session.commit()

    asyncio.run(seed())
    tokens = TokenService("r" * 32)
    requester_token = tokens.create(requester_id, timedelta(minutes=10), token_type="access")
    approver_token = tokens.create(approver_id, timedelta(minutes=10), token_type="access")
    settings = Settings(environment=Environment.TEST, database_url=database_url)
    with TestClient(create_app(settings, access_token_service=tokens)) as client:
        requester_headers = {
            "Authorization": f"Bearer {requester_token}",
            "X-Organization-ID": org_id,
        }
        approver_headers = {
            "Authorization": f"Bearer {approver_token}",
            "X-Organization-ID": org_id,
        }
        payload = {
            "reference": "REQ-2026-001",
            "branch_id": branch_id,
            "justification": "Monthly office stationery replenishment",
            "idempotency_key": "req-2026-001-key",
            "lines": [{"item_id": item_id, "quantity": "12", "estimated_unit_cost": "850"}],
        }
        created = client.post(
            "/api/procurement/requisitions",
            headers=requester_headers,
            json=payload,
        )
        assert created.status_code == 201, created.text
        requisition_id = created.json()["id"]
        replay = client.post(
            "/api/procurement/requisitions",
            headers=requester_headers,
            json=payload,
        )
        assert replay.status_code == 201 and replay.json()["id"] == requisition_id

        submitted = client.post(
            f"/api/procurement/requisitions/{requisition_id}/submit",
            headers=requester_headers,
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"
        self_approval = client.post(
            f"/api/procurement/requisitions/{requisition_id}/approve",
            headers=requester_headers,
            json={},
        )
        assert self_approval.status_code == 403

        approved = client.post(
            f"/api/procurement/requisitions/{requisition_id}/approve",
            headers=approver_headers,
            json={"reason": "Within approved operating budget"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        history = client.get(
            f"/api/procurement/requisitions/{requisition_id}/decisions",
            headers=approver_headers,
        )
        assert history.status_code == 200
        assert [entry["decision"] for entry in history.json()] == ["submitted", "approved"]
        assert history.json()[-1]["actor_user_id"] == approver_id
        converted = client.post(
            f"/api/procurement/requisitions/{requisition_id}/convert-to-purchase-order",
            headers=approver_headers,
            json={"supplier_id": supplier_id, "purchase_order_reference": "PO-FROM-REQ-001"},
        )
        assert converted.status_code == 201, converted.text
        assert converted.json()["requisition_status"] == "converted"
        assert converted.json()["purchase_order_status"] == "draft"
        assert converted.json()["lines"][0]["unit_cost"] == "850.0000"
        repeated_conversion = client.post(
            f"/api/procurement/requisitions/{requisition_id}/convert-to-purchase-order",
            headers=approver_headers,
            json={"supplier_id": supplier_id, "purchase_order_reference": "IGNORED-RETRY"},
        )
        assert repeated_conversion.status_code == 201
        assert (
            repeated_conversion.json()["purchase_order_id"] == converted.json()["purchase_order_id"]
        )
        assert (
            client.post(
                f"/api/procurement/requisitions/{requisition_id}/reject",
                headers=approver_headers,
                json={"reason": "No longer needed"},
            ).status_code
            == 409
        )

    asyncio.run(engine.dispose())
