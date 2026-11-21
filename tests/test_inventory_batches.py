"""Integration coverage for lot receipts, FEFO issues and batch controls."""

from datetime import date, timedelta
from decimal import Decimal
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
from veristock.inventory.models import InventoryItem
from veristock.organizations.models import Branch


def test_batch_receiving_fefo_issue_and_quarantine(tmp_path) -> None:
    import asyncio

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'batches.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, branch_id, item_id = (str(uuid4()) for _ in range(4))
    membership_id, role_id = str(uuid4()), str(uuid4())
    permissions = {
        code: str(uuid4()) for code in ("inventory.manage", "inventory.read", "sales.record")
    }

    async def seed() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all(
                [
                    User(id=user_id, identifier="batch@example.com", password_hash="x"),
                    Organization(id=org_id, kind="client", legal_name="Batch Tenant"),
                    OrganizationMembership(
                        id=membership_id, organization_id=org_id, user_id=user_id, status="active"
                    ),
                    Role(
                        id=role_id, code="client_operator", name="Client Operator", scope="client"
                    ),
                    MembershipRole(membership_id=membership_id, role_id=role_id),
                    Branch(id=branch_id, organization_id=org_id, code="MAIN", name="Main"),
                    InventoryItem(
                        id=item_id,
                        organization_id=org_id,
                        sku="BATCH-1",
                        name="Milk",
                        base_unit_code="EA",
                        status="active",
                    ),
                ]
            )
            for code, permission_id in permissions.items():
                session.add(Permission(id=permission_id, code=code, description=code))
                session.add(RolePermission(role_id=role_id, permission_id=permission_id))
            await session.commit()

    asyncio.run(seed())
    settings = Settings(environment=Environment.TEST, database_url=database_url)
    tokens = TokenService("x" * 32)
    token = tokens.create(user_id, timedelta(minutes=10), token_type="access")
    headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}
    today = date.today()
    with TestClient(create_app(settings, access_token_service=tokens)) as client:
        later = client.post(
            "/api/inventory/batches/receive",
            headers=headers,
            json={
                "branch_id": branch_id,
                "item_id": item_id,
                "lot_code": "LOT-LATE",
                "quantity": "5",
                "expiry_date": (today + timedelta(days=30)).isoformat(),
                "idempotency_key": "batch-receive-late-01",
            },
        )
        earlier = client.post(
            "/api/inventory/batches/receive",
            headers=headers,
            json={
                "branch_id": branch_id,
                "item_id": item_id,
                "lot_code": "LOT-EARLY",
                "quantity": "3",
                "expiry_date": (today + timedelta(days=10)).isoformat(),
                "idempotency_key": "batch-receive-early-01",
            },
        )
        assert later.status_code == 201, later.text
        assert earlier.status_code == 201, earlier.text

        # Ordinary sales must also consume the same batch ledger using FEFO.
        sale = client.post(
            "/api/sales",
            headers=headers,
            json={
                "branch_id": branch_id,
                "idempotency_key": "batch-linked-sale-0001",
                "lines": [{"item_id": item_id, "quantity": "1", "unit_code": "EA"}],
            },
        )
        assert sale.status_code == 201, sale.text
        ledger = client.get("/api/inventory/movements", headers=headers)
        assert ledger.status_code == 200, ledger.text
        sale_movements = [row for row in ledger.json() if row["source_id"] == sale.json()["id"]]
        assert len(sale_movements) == 1
        assert sale_movements[0]["batch_id"] == earlier.json()["id"]
        listed = client.get("/api/inventory/batches", headers=headers, params={"item_id": item_id})
        assert listed.status_code == 200, listed.text
        early_balance = next(row for row in listed.json() if row["id"] == earlier.json()["id"])
        assert Decimal(early_balance["quantity_on_hand"]) == Decimal("2.0000")

        issue_payload = {
            "branch_id": branch_id,
            "item_id": item_id,
            "quantity": "4",
            "idempotency_key": "batch-issue-fefo-01",
        }
        issued = client.post(
            "/api/inventory/batches/issue-fefo", headers=headers, json=issue_payload
        )
        assert issued.status_code == 201, issued.text
        assert issued.json()["allocations"] == [
            {"batch_id": earlier.json()["id"], "quantity": "2.0000"},
            {"batch_id": later.json()["id"], "quantity": "2.0000"},
        ]
        replay = client.post(
            "/api/inventory/batches/issue-fefo", headers=headers, json=issue_payload
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["movement_ids"] == issued.json()["movement_ids"]

        quarantined = client.patch(
            f"/api/inventory/batches/{later.json()['id']}/status",
            headers=headers,
            json={"status": "quarantined"},
        )
        assert quarantined.status_code == 200, quarantined.text
        blocked = client.post(
            "/api/inventory/batches/issue-fefo",
            headers=headers,
            json={
                "branch_id": branch_id,
                "item_id": item_id,
                "quantity": "1",
                "idempotency_key": "batch-issue-quarantine-01",
            },
        )
        assert blocked.status_code == 409

    asyncio.run(engine.dispose())
