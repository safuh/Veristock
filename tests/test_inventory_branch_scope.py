"""Integration coverage for branch-scoped inventory visibility."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
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
from veristock.inventory.models import InventoryItem, StockBalance
from veristock.organizations.models import Branch, BranchMembership


@pytest.mark.asyncio
async def test_field_inventory_reads_are_limited_to_assigned_branches(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'branch-inventory.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id = str(uuid4()), str(uuid4())
    membership_id, role_id = str(uuid4()), str(uuid4())
    assigned_branch_id, other_branch_id, item_id = (str(uuid4()), str(uuid4()), str(uuid4()))
    permission_ids = {code: str(uuid4()) for code in ("inventory.read", "stocktake.count")}
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        identifier="counter@example.com",
                        password_hash="x",
                    ),
                    Organization(
                        id=org_id,
                        kind="client",
                        legal_name="Tenant A",
                    ),
                    OrganizationMembership(
                        id=membership_id,
                        organization_id=org_id,
                        user_id=user_id,
                        status="active",
                    ),
                    Role(
                        id=role_id,
                        code="field_counter",
                        name="Field Counter",
                        scope="client",
                    ),
                    MembershipRole(
                        membership_id=membership_id,
                        role_id=role_id,
                    ),
                    Branch(
                        id=assigned_branch_id,
                        organization_id=org_id,
                        code="A",
                        name="Assigned branch",
                    ),
                    Branch(
                        id=other_branch_id,
                        organization_id=org_id,
                        code="B",
                        name="Unassigned branch",
                    ),
                    InventoryItem(
                        id=item_id,
                        organization_id=org_id,
                        sku="SKU-1",
                        name="Widget",
                        base_unit_code="EA",
                        status="active",
                    ),
                    StockBalance(
                        id=str(uuid4()),
                        organization_id=org_id,
                        branch_id=assigned_branch_id,
                        item_id=item_id,
                        quantity_on_hand=Decimal("5"),
                    ),
                    StockBalance(
                        id=str(uuid4()),
                        organization_id=org_id,
                        branch_id=other_branch_id,
                        item_id=item_id,
                        quantity_on_hand=Decimal("99"),
                    ),
                    BranchMembership(
                        id=str(uuid4()),
                        organization_id=org_id,
                        branch_id=assigned_branch_id,
                        membership_id=membership_id,
                        assigned_by_user_id=user_id,
                    ),
                ]
            )
            for code, permission_id in permission_ids.items():
                session.add(Permission(id=permission_id, code=code, description=code))
                session.add(
                    RolePermission(
                        role_id=role_id,
                        permission_id=permission_id,
                    )
                )
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
        balances = client.get("/api/inventory/balances", headers=headers)
        assert balances.status_code == 200
        assert len(balances.json()) == 1
        assert balances.json()[0]["branch_id"] == assigned_branch_id
        assert Decimal(balances.json()[0]["quantity_on_hand"]) == Decimal("5")

        denied = client.get(
            f"/api/inventory/balances?branch_id={other_branch_id}",
            headers=headers,
        )
        assert denied.status_code == 404

        summary = client.get("/api/inventory/summary", headers=headers)
        assert summary.status_code == 200
        assert summary.json()["branch_count"] == 1
        assert Decimal(summary.json()["total_units_on_hand"]) == Decimal("5")
