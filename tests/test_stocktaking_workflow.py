"""Physical stocktaking API workflow tests."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

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
from veristock.inventory.models import InventoryItem, StockBalance
from veristock.organizations.models import Branch
from veristock.stocktaking.models import StocktakeObservation


def test_blind_stocktake_capture_submit_and_recount(tmp_path) -> None:
    import asyncio

    async def seed(database_url: str) -> tuple[str, str, str, str]:
        engine = create_async_engine(database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        user_id, org_id, branch_id, item_id = (str(uuid4()) for _ in range(4))
        membership_id, role_id = str(uuid4()), str(uuid4())
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with factory() as session:
                session.add_all(
                    [
                        User(id=user_id, identifier="counter@example.com", password_hash="x"),
                        Organization(id=org_id, kind="client", legal_name="Count Tenant"),
                        OrganizationMembership(
                            id=membership_id,
                            organization_id=org_id,
                            user_id=user_id,
                            status="active",
                        ),
                        Role(id=role_id, code="count_team", name="Count Team", scope="client"),
                        MembershipRole(membership_id=membership_id, role_id=role_id),
                        Branch(
                            id=branch_id,
                            organization_id=org_id,
                            code="MAIN",
                            name="Main",
                        ),
                        InventoryItem(
                            id=item_id,
                            organization_id=org_id,
                            sku="ITEM-1",
                            barcode="123456789",
                            name="Counted item",
                            base_unit_code="EA",
                            status="active",
                        ),
                        StockBalance(
                            id=str(uuid4()),
                            organization_id=org_id,
                            branch_id=branch_id,
                            item_id=item_id,
                            quantity_on_hand=Decimal("14"),
                        ),
                    ]
                )
                for code in ("stocktake.manage", "stocktake.read", "stocktake.count"):
                    permission_id = str(uuid4())
                    session.add(
                        Permission(id=permission_id, code=code, description=code)
                    )
                    session.add(
                        RolePermission(role_id=role_id, permission_id=permission_id)
                    )
                await session.commit()
        finally:
            await engine.dispose()
        return user_id, org_id, branch_id, item_id

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'stocktaking.db'}"
    user_id, org_id, branch_id, item_id = asyncio.run(seed(database_url))
    tokens = TokenService("s" * 32)
    token = tokens.create(user_id, timedelta(minutes=10), token_type="access")
    settings = Settings(environment=Environment.TEST, database_url=database_url)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": org_id,
    }

    with TestClient(create_app(settings, access_token_service=tokens)) as client:
        created = client.post(
            "/api/stocktakes",
            headers=headers,
            json={"branch_id": branch_id, "reference": "ST-001", "blind_count": True},
        )
        assert created.status_code == 201
        stocktake_id = created.json()["id"]
        assert created.json()["item_count"] == 1

        scope = client.get(f"/api/stocktakes/{stocktake_id}/scope", headers=headers)
        assert scope.status_code == 200
        assert scope.json()[0]["item_id"] == item_id
        assert "expected_quantity" not in scope.json()[0]

        incomplete = client.post(f"/api/stocktakes/{stocktake_id}/submit", headers=headers)
        assert incomplete.status_code == 409

        count_payload = {
            "item_id": item_id,
            "counted_quantity": "12",
            "unit_code": "EA",
            "idempotency_key": "count-device-0001",
        }
        counted = client.post(
            f"/api/stocktakes/{stocktake_id}/observations",
            headers=headers,
            json=count_payload,
        )
        assert counted.status_code == 201
        replay = client.post(
            f"/api/stocktakes/{stocktake_id}/observations",
            headers=headers,
            json=count_payload,
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == counted.json()["id"]

        submitted = client.post(f"/api/stocktakes/{stocktake_id}/submit", headers=headers)
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"

        recount = client.post(f"/api/stocktakes/{stocktake_id}/recount", headers=headers)
        assert recount.status_code == 201
        assert recount.json()["round_number"] == 2

        zero_count = client.post(
            f"/api/stocktakes/{stocktake_id}/observations",
            headers=headers,
            json={
                "item_id": item_id,
                "counted_quantity": "0",
                "unit_code": "EA",
                "idempotency_key": "count-device-0002",
            },
        )
        assert zero_count.status_code == 201
        final_submit = client.post(
            f"/api/stocktakes/{stocktake_id}/submit",
            headers=headers,
        )
        assert final_submit.status_code == 200

    async def verify() -> None:
        engine = create_async_engine(database_url)
        try:
            async with async_sessionmaker(engine)() as session:
                observations = list(
                    (
                        await session.scalars(
                            select(StocktakeObservation).where(
                                StocktakeObservation.stocktake_id == stocktake_id
                            )
                        )
                    ).all()
                )
                assert len(observations) == 2
        finally:
            await engine.dispose()

    asyncio.run(verify())
