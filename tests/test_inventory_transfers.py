"""Inter-branch transfer workflow integration tests."""

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
from veristock.inventory.models import (
    BatchStockBalance,
    InventoryBatch,
    InventoryItem,
    StockBalance,
    StockMovement,
)
from veristock.inventory.transfers import StockTransfer
from veristock.organizations.models import Branch


def test_transfer_dispatch_receive_is_idempotent_and_moves_batches(tmp_path) -> None:
    import asyncio

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'transfers.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, source_id, destination_id, item_batch_id, item_bulk_id = (
        str(uuid4()) for _ in range(6)
    )
    membership_id, role_id = str(uuid4()), str(uuid4())

    async def seed() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all(
                [
                    User(id=user_id, identifier="transfer@example.com", password_hash="x"),
                    Organization(id=org_id, kind="client", legal_name="Transfer Tenant"),
                    OrganizationMembership(
                        id=membership_id, organization_id=org_id, user_id=user_id, status="active"
                    ),
                    Role(
                        id=role_id,
                        code="inventory_manager",
                        name="Inventory Manager",
                        scope="client",
                    ),
                    MembershipRole(membership_id=membership_id, role_id=role_id),
                    Branch(id=source_id, organization_id=org_id, code="SRC", name="Source"),
                    Branch(
                        id=destination_id, organization_id=org_id, code="DST", name="Destination"
                    ),
                    InventoryItem(
                        id=item_batch_id,
                        organization_id=org_id,
                        sku="BATCH",
                        name="Batch item",
                        base_unit_code="EA",
                        status="active",
                    ),
                    InventoryItem(
                        id=item_bulk_id,
                        organization_id=org_id,
                        sku="BULK",
                        name="Bulk item",
                        base_unit_code="EA",
                        status="active",
                    ),
                    StockBalance(
                        id=str(uuid4()),
                        organization_id=org_id,
                        branch_id=source_id,
                        item_id=item_batch_id,
                        quantity_on_hand=Decimal("5"),
                    ),
                    StockBalance(
                        id=str(uuid4()),
                        organization_id=org_id,
                        branch_id=source_id,
                        item_id=item_bulk_id,
                        quantity_on_hand=Decimal("8"),
                    ),
                    InventoryBatch(
                        id="transfer-batch-source",
                        organization_id=org_id,
                        item_id=item_batch_id,
                        branch_id=source_id,
                        lot_code="LOT-TRANSFER",
                        expiry_date=None,
                        status="active",
                    ),
                    BatchStockBalance(
                        id=str(uuid4()),
                        organization_id=org_id,
                        branch_id=source_id,
                        item_id=item_batch_id,
                        batch_id="transfer-batch-source",
                        quantity_on_hand=Decimal("5"),
                    ),
                ]
            )
            for code in ("inventory.manage", "inventory.read"):
                permission = Permission(id=str(uuid4()), code=code, description=code)
                session.add(permission)
                session.add(RolePermission(role_id=role_id, permission_id=permission.id))
            await session.commit()

    asyncio.run(seed())
    tokens = TokenService("t" * 32)
    token = tokens.create(user_id, timedelta(minutes=10), token_type="access")
    headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}
    settings = Settings(environment=Environment.TEST, database_url=database_url)

    with TestClient(create_app(settings, access_token_service=tokens)) as client:
        payload = {
            "reference": "TR-001",
            "source_branch_id": source_id,
            "destination_branch_id": destination_id,
            "idempotency_key": "transfer-create-0001",
            "lines": [
                {"item_id": item_batch_id, "batch_id": "transfer-batch-source", "quantity": "2"},
                {"item_id": item_bulk_id, "quantity": "3"},
            ],
        }
        created = client.post("/api/inventory/transfers", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        transfer_id = created.json()["id"]
        replay = client.post("/api/inventory/transfers", headers=headers, json=payload)
        assert replay.status_code == 201
        assert replay.json()["id"] == transfer_id

        mismatched = {
            **payload,
            "lines": [{"item_id": item_bulk_id, "quantity": "4"}, payload["lines"][0]],
        }
        assert (
            client.post("/api/inventory/transfers", headers=headers, json=mismatched).status_code
            == 409
        )

        dispatched = client.post(
            f"/api/inventory/transfers/{transfer_id}/dispatch", headers=headers
        )
        assert dispatched.status_code == 200, dispatched.text
        assert dispatched.json()["status"] == "dispatched"
        assert (
            client.post(
                f"/api/inventory/transfers/{transfer_id}/dispatch", headers=headers
            ).status_code
            == 200
        )

        async def balances_after_dispatch() -> tuple[Decimal, Decimal]:
            async with factory() as session:
                source_batch = await session.scalar(
                    select(BatchStockBalance).where(
                        BatchStockBalance.batch_id == "transfer-batch-source"
                    )
                )
                bulk = await session.scalar(
                    select(StockBalance).where(
                        StockBalance.branch_id == source_id, StockBalance.item_id == item_bulk_id
                    )
                )
                assert source_batch is not None and bulk is not None
                return source_batch.quantity_on_hand, bulk.quantity_on_hand

        assert asyncio.run(balances_after_dispatch()) == (Decimal("3.0000"), Decimal("5.0000"))

        received = client.post(f"/api/inventory/transfers/{transfer_id}/receive", headers=headers)
        assert received.status_code == 200, received.text
        assert received.json()["status"] == "received"
        assert (
            client.post(
                f"/api/inventory/transfers/{transfer_id}/receive", headers=headers
            ).status_code
            == 200
        )

        async def verify_destination() -> tuple[Decimal, Decimal, int]:
            async with factory() as session:
                batch_balance = await session.scalar(
                    select(BatchStockBalance).where(
                        BatchStockBalance.organization_id == org_id,
                        BatchStockBalance.branch_id == destination_id,
                        BatchStockBalance.item_id == item_batch_id,
                    )
                )
                bulk_balance = await session.scalar(
                    select(StockBalance).where(
                        StockBalance.organization_id == org_id,
                        StockBalance.branch_id == destination_id,
                        StockBalance.item_id == item_bulk_id,
                    )
                )
                transfer = await session.scalar(
                    select(StockTransfer).where(StockTransfer.id == transfer_id)
                )
                movements = list(
                    (
                        await session.scalars(
                            select(StockMovement).where(
                                StockMovement.organization_id == org_id,
                                StockMovement.source_type == "stock_transfer",
                                StockMovement.source_id == transfer_id,
                            )
                        )
                    ).all()
                )
                assert (
                    batch_balance is not None and bulk_balance is not None and transfer is not None
                )
                return batch_balance.quantity_on_hand, bulk_balance.quantity_on_hand, len(movements)

        assert asyncio.run(verify_destination()) == (Decimal("2.0000"), Decimal("3.0000"), 4)

    asyncio.run(engine.dispose())
