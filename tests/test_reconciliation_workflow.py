"""Deterministic stocktake reconciliation API workflow tests."""

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


def test_reconciliation_approval_posts_stock_adjustment_and_prevents_self_approval(
    tmp_path,
) -> None:
    import asyncio

    from veristock.inventory.models import StockMovement
    from veristock.stocktaking.models import ReconciliationApproval, ReconciliationRun

    async def seed(url: str) -> tuple[str, str, str, str, str]:
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        counter, reviewer, org, branch, item = (str(uuid4()) for _ in range(5))
        counter_membership, reviewer_membership, counter_role, reviewer_role = (
            str(uuid4()) for _ in range(4)
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with factory() as session:
                session.add_all(
                    [
                        User(id=counter, identifier="counter@example.com", password_hash="x"),
                        User(id=reviewer, identifier="reviewer@example.com", password_hash="x"),
                        Organization(id=org, kind="client", legal_name="Reconciliation Tenant"),
                        OrganizationMembership(
                            id=counter_membership,
                            organization_id=org,
                            user_id=counter,
                            status="active",
                        ),
                        OrganizationMembership(
                            id=reviewer_membership,
                            organization_id=org,
                            user_id=reviewer,
                            status="active",
                        ),
                        Role(id=counter_role, code="counter", name="Counter", scope="client"),
                        Role(
                            id=reviewer_role,
                            code="client_reviewer",
                            name="Reviewer",
                            scope="client",
                        ),
                        MembershipRole(membership_id=counter_membership, role_id=counter_role),
                        MembershipRole(membership_id=reviewer_membership, role_id=reviewer_role),
                        Branch(id=branch, organization_id=org, code="MAIN", name="Main"),
                        InventoryItem(
                            id=item,
                            organization_id=org,
                            sku="RECON-1",
                            name="Test item",
                            base_unit_code="EA",
                            status="active",
                        ),
                        StockBalance(
                            id=str(uuid4()),
                            organization_id=org,
                            branch_id=branch,
                            item_id=item,
                            quantity_on_hand=Decimal("14"),
                        ),
                    ]
                )
                codes = (
                    "stocktake.manage",
                    "stocktake.read",
                    "stocktake.count",
                    "stocktake.submit",
                    "reconciliation.run",
                    "reconciliation.review",
                    "reconciliation.approve",
                )
                ids = {}
                for code in codes:
                    ids[code] = str(uuid4())
                    session.add(Permission(id=ids[code], code=code, description=code))
                for code in (*codes[:4], "reconciliation.approve"):
                    session.add(RolePermission(role_id=counter_role, permission_id=ids[code]))
                for code in codes[4:]:
                    session.add(RolePermission(role_id=reviewer_role, permission_id=ids[code]))
                await session.commit()
        finally:
            await engine.dispose()
        return counter, reviewer, org, branch, item

    url = f"sqlite+aiosqlite:///{tmp_path / 'reconciliation.db'}"
    counter, reviewer, org, branch, item = asyncio.run(seed(url))
    tokens = TokenService("r" * 32)
    counter_token = tokens.create(counter, timedelta(minutes=10), token_type="access")
    reviewer_token = tokens.create(reviewer, timedelta(minutes=10), token_type="access")
    settings = Settings(environment=Environment.TEST, database_url=url)
    counter_headers = {"Authorization": f"Bearer {counter_token}", "X-Organization-ID": org}
    reviewer_headers = {"Authorization": f"Bearer {reviewer_token}", "X-Organization-ID": org}

    with TestClient(create_app(settings, access_token_service=tokens)) as client:
        created = client.post(
            "/api/stocktakes",
            headers=counter_headers,
            json={"branch_id": branch, "reference": "ST-RECON", "blind_count": True},
        )
        assert created.status_code == 201
        stocktake_id = created.json()["id"]
        counted = client.post(
            f"/api/stocktakes/{stocktake_id}/observations",
            headers=counter_headers,
            json={
                "item_id": item,
                "counted_quantity": "11",
                "unit_code": "EA",
                "idempotency_key": "reconciliation-count-1",
            },
        )
        assert counted.status_code == 201
        submitted = client.post(f"/api/stocktakes/{stocktake_id}/submit", headers=counter_headers)
        assert submitted.status_code == 200

        calculated = client.post(
            f"/api/reconciliations/stocktakes/{stocktake_id}/calculate",
            headers=reviewer_headers,
        )
        assert calculated.status_code == 201
        body = calculated.json()
        assert body["shortage_lines"] == 1
        assert body["lines"][0]["variance_quantity"] == "-3.0000"
        run_id = body["id"]
        duplicate_calculation = client.post(
            f"/api/reconciliations/stocktakes/{stocktake_id}/calculate",
            headers=reviewer_headers,
        )
        assert duplicate_calculation.status_code == 201
        assert duplicate_calculation.json()["id"] == run_id

        denied = client.post(
            f"/api/reconciliations/{run_id}/approve", headers=counter_headers, json={}
        )
        assert denied.status_code == 403

        approved = client.post(
            f"/api/reconciliations/{run_id}/approve",
            headers=reviewer_headers,
            json={"note": "Independently reviewed"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        replay = client.post(
            f"/api/reconciliations/{run_id}/approve", headers=reviewer_headers, json={}
        )
        assert replay.status_code == 200
        assert replay.json()["status"] == "approved"
        closed_recount = client.post(
            f"/api/stocktakes/{stocktake_id}/recount", headers=counter_headers
        )
        assert closed_recount.status_code == 409

        second = client.post(
            "/api/stocktakes",
            headers=counter_headers,
            json={"branch_id": branch, "reference": "ST-STALE", "blind_count": True},
        )
        assert second.status_code == 201
        second_id = second.json()["id"]
        second_count = client.post(
            f"/api/stocktakes/{second_id}/observations",
            headers=counter_headers,
            json={
                "item_id": item,
                "counted_quantity": "8",
                "unit_code": "EA",
                "idempotency_key": "reconciliation-count-2",
            },
        )
        assert second_count.status_code == 201
        assert (
            client.post(f"/api/stocktakes/{second_id}/submit", headers=counter_headers).status_code
            == 200
        )
        second_run = client.post(
            f"/api/reconciliations/stocktakes/{second_id}/calculate",
            headers=reviewer_headers,
        )
        assert second_run.status_code == 201

        async def simulate_concurrent_stock_movement() -> None:
            engine = create_async_engine(url)
            try:
                async with async_sessionmaker(engine)() as session:
                    balance = await session.scalar(
                        select(StockBalance).where(
                            StockBalance.organization_id == org,
                            StockBalance.branch_id == branch,
                            StockBalance.item_id == item,
                        )
                    )
                    assert balance is not None
                    balance.quantity_on_hand += Decimal("1")
                    balance.version += 1
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(simulate_concurrent_stock_movement())
        stale_approval = client.post(
            f"/api/reconciliations/{second_run.json()['id']}/approve",
            headers=reviewer_headers,
            json={"note": "Must not overwrite intervening stock movement"},
        )
        assert stale_approval.status_code == 409

    async def verify() -> None:
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                balance = await session.scalar(
                    select(StockBalance).where(
                        StockBalance.organization_id == org,
                        StockBalance.branch_id == branch,
                        StockBalance.item_id == item,
                    )
                )
                assert balance is not None
                assert balance.quantity_on_hand == Decimal("12.0000")
                assert balance.version == 3
                movements = list(
                    (
                        await session.scalars(
                            select(StockMovement).where(
                                StockMovement.source_type == "stocktake_adjustment"
                            )
                        )
                    ).all()
                )
                assert len(movements) == 1
                assert movements[0].quantity_delta == Decimal("-3.0000")
                run = await session.scalar(
                    select(ReconciliationRun).where(ReconciliationRun.id == run_id)
                )
                assert run is not None and run.status == "approved"
                approvals = list(
                    (
                        await session.scalars(
                            select(ReconciliationApproval).where(
                                ReconciliationApproval.run_id == run_id
                            )
                        )
                    ).all()
                )
                assert len(approvals) == 1
                assert approvals[0].decision == "approved"
        finally:
            await engine.dispose()

    asyncio.run(verify())
