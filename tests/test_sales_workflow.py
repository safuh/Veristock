"""Integration tests for tenant-scoped opening stock and sale posting."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
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
from veristock.inventory.models import InventoryItem, Sale, StockBalance, StockMovement
from veristock.organizations.models import Branch


@pytest.mark.asyncio
async def test_opening_balance_and_sale_posting_are_atomic_and_idempotent(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'sales.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, branch_id, item_id = (str(uuid4()) for _ in range(4))
    membership_id, role_id = str(uuid4()), str(uuid4())
    permission_ids = {code: str(uuid4()) for code in ("inventory.manage", "sales.record")}
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all(
                [
                    User(id=user_id, identifier="sales@example.com", password_hash="x"),
                    Organization(id=org_id, kind="client", legal_name="Tenant A"),
                    OrganizationMembership(
                        id=membership_id, organization_id=org_id, user_id=user_id, status="active"
                    ),
                    Role(id=role_id, code="client_operator", name="Client Operator", scope="client"),
                    MembershipRole(membership_id=membership_id, role_id=role_id),
                    Branch(id=branch_id, organization_id=org_id, code="MAIN", name="Main"),
                    InventoryItem(
                        id=item_id,
                        organization_id=org_id,
                        sku="SKU-1",
                        name="Widget",
                        base_unit_code="EA",
                        status="active",
                    ),
                ]
            )
            for code, permission_id in permission_ids.items():
                session.add(Permission(id=permission_id, code=code, description=code))
                session.add(RolePermission(role_id=role_id, permission_id=permission_id))
            await session.commit()
    finally:
        await engine.dispose()

    settings = Settings(environment=Environment.TEST, database_url=database_url)
    tokens = TokenService("x" * 32)
    token = tokens.create(user_id, timedelta(minutes=10), token_type="access")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": org_id,
    }
    with TestClient(create_app(settings, access_token_service=tokens)) as client:
        opening = client.post(
            "/api/inventory/opening-balances",
            headers=headers,
            json={
                "branch_id": branch_id,
                "item_id": item_id,
                "quantity": "10",
                "idempotency_key": "opening-2026-001",
            },
        )
        assert opening.status_code == 201
        assert opening.json()["quantity_on_hand"] == "10.0000"

        replay = client.post(
            "/api/inventory/opening-balances",
            headers=headers,
            json={
                "branch_id": branch_id,
                "item_id": item_id,
                "quantity": "10",
                "idempotency_key": "opening-2026-001",
            },
        )
        assert replay.status_code == 201

        sale_payload = {
            "branch_id": branch_id,
            "idempotency_key": "sale-register-0001",
            "reference": "POS-0001",
            "lines": [
                {
                    "item_id": item_id,
                    "quantity": "3",
                    "unit_code": "EA",
                    "unit_price": "12.50",
                    "currency": "KES",
                }
            ],
        }
        posted = client.post("/api/sales", headers=headers, json=sale_payload)
        assert posted.status_code == 201
        assert posted.json()["status"] == "posted"
        assert len(posted.json()["lines"]) == 1

        replayed_sale = client.post("/api/sales", headers=headers, json=sale_payload)
        assert replayed_sale.status_code == 201
        assert replayed_sale.json()["id"] == posted.json()["id"]

        changed_replay = {**sale_payload, "lines": [{**sale_payload["lines"][0], "quantity": "4"}]}
        conflict = client.post("/api/sales", headers=headers, json=changed_replay)
        assert conflict.status_code == 409

        insufficient = {
            **sale_payload,
            "idempotency_key": "sale-register-0002",
            "lines": [{**sale_payload["lines"][0], "quantity": "8"}],
        }
        rejected = client.post("/api/sales", headers=headers, json=insufficient)
        assert rejected.status_code == 409

        balances = client.get("/api/inventory/balances", headers=headers)
        assert balances.status_code == 200
        assert Decimal(balances.json()[0]["quantity_on_hand"]) == Decimal("7.0000")

    engine = create_async_engine(database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            assert await session.scalar(select(Sale).where(Sale.organization_id == org_id)) is not None
            assert await session.scalar(
                select(StockMovement.id).where(
                    StockMovement.organization_id == org_id,
                    StockMovement.source_type == "sale",
                )
            ) is not None
            balance = await session.scalar(
                select(StockBalance).where(
                    StockBalance.organization_id == org_id,
                    StockBalance.branch_id == branch_id,
                    StockBalance.item_id == item_id,
                )
            )
            assert balance is not None
            assert balance.quantity_on_hand == Decimal("7.0000")
    finally:
        await engine.dispose()
