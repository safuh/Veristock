"""Purchase order, partial GRN, batch creation and stock posting integration tests."""

import asyncio
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
    Supplier,
)
from veristock.inventory.procurement import (
    GoodsReceipt,
    InventoryCostAllocation,
    InventoryCostLayer,
    PurchaseOrder,
)
from veristock.organizations.models import Branch


def test_purchase_order_partial_receipts_update_stock_and_are_idempotent(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'procurement.db'}"
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id, org_id, branch_id, item_id, supplier_id = (str(uuid4()) for _ in range(5))
    membership_id, role_id = str(uuid4()), str(uuid4())

    async def seed() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all(
                [
                    User(id=user_id, identifier="buyer@example.test", password_hash="x"),
                    Organization(id=org_id, kind="client", legal_name="Procurement Tenant"),
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
                    Branch(id=branch_id, organization_id=org_id, code="MAIN", name="Main Branch"),
                    InventoryItem(
                        id=item_id,
                        organization_id=org_id,
                        sku="RICE-001",
                        name="Rice",
                        base_unit_code="KG",
                        status="active",
                    ),
                    Supplier(
                        id=supplier_id,
                        organization_id=org_id,
                        code="SUP-001",
                        name="Regional Foods",
                        default_currency="KES",
                        status="active",
                    ),
                ]
            )
            for code in ("inventory.manage", "inventory.read", "sales.record"):
                permission = Permission(id=str(uuid4()), code=code, description=code)
                session.add(permission)
                session.add(RolePermission(role_id=role_id, permission_id=permission.id))
            await session.commit()

    asyncio.run(seed())
    tokens = TokenService("p" * 32)
    token = tokens.create(user_id, timedelta(minutes=10), token_type="access")
    headers = {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}
    settings = Settings(environment=Environment.TEST, database_url=database_url)

    with TestClient(create_app(settings, access_token_service=tokens)) as client:
        order_payload = {
            "reference": "PO-2026-001",
            "supplier_id": supplier_id,
            "branch_id": branch_id,
            "currency": "KES",
            "expected_delivery_date": "2099-12-31",
            "idempotency_key": "po-create-2026-001",
            "lines": [{"item_id": item_id, "quantity": "10", "unit_cost": "125.50"}],
        }
        created = client.post(
            "/api/procurement/purchase-orders", headers=headers, json=order_payload
        )
        assert created.status_code == 201, created.text
        po_id = created.json()["id"]
        assert (
            client.post(
                "/api/procurement/purchase-orders", headers=headers, json=order_payload
            ).json()["id"]
            == po_id
        )

        issued = client.post(f"/api/procurement/purchase-orders/{po_id}/issue", headers=headers)
        assert issued.status_code == 200, issued.text
        po_line_id = issued.json()["lines"][0]["id"]

        first_receipt = {
            "reference": "GRN-001",
            "supplier_delivery_reference": "DELIVERY-001",
            "idempotency_key": "grn-create-2026-001",
            "lines": [
                {
                    "purchase_order_line_id": po_line_id,
                    "quantity": "4",
                    "lot_code": "RICE-LOT-01",
                    "expiry_date": "2027-12-31",
                }
            ],
        }
        receipt = client.post(
            f"/api/procurement/purchase-orders/{po_id}/receipts",
            headers=headers,
            json=first_receipt,
        )
        assert receipt.status_code == 201, receipt.text
        assert receipt.json()["lines"][0]["batch_id"]
        assert (
            client.post(
                f"/api/procurement/purchase-orders/{po_id}/receipts",
                headers=headers,
                json=first_receipt,
            ).json()["id"]
            == receipt.json()["id"]
        )
        mismatched_replay = {
            **first_receipt,
            "lines": [
                {
                    **first_receipt["lines"][0],
                    "lot_code": "DIFFERENT-LOT",
                }
            ],
        }
        assert (
            client.post(
                f"/api/procurement/purchase-orders/{po_id}/receipts",
                headers=headers,
                json=mismatched_replay,
            ).status_code
            == 409
        )
        assert (
            client.get("/api/procurement/purchase-orders", headers=headers).json()[0]["status"]
            == "partially_received"
        )

        second_receipt = {
            "reference": "GRN-002",
            "idempotency_key": "grn-create-2026-002",
            "lines": [
                {
                    "purchase_order_line_id": po_line_id,
                    "quantity": "6",
                    "lot_code": "RICE-LOT-01",
                    "expiry_date": "2027-12-31",
                }
            ],
        }
        completed = client.post(
            f"/api/procurement/purchase-orders/{po_id}/receipts",
            headers=headers,
            json=second_receipt,
        )
        assert completed.status_code == 201, completed.text
        completed_po = client.get("/api/procurement/purchase-orders", headers=headers).json()[0]
        assert completed_po["delivery_status"] == "on_time"
        assert completed_po["completed_at"] is not None
        assert (
            client.get("/api/procurement/purchase-orders", headers=headers).json()[0]["status"]
            == "received"
        )
        cost_layers = client.get("/api/procurement/valuation/cost-layers", headers=headers)
        assert cost_layers.status_code == 200, cost_layers.text
        assert cost_layers.json()["valuation_status"] == "receipt_cost_layers_only"
        assert len(cost_layers.json()["items"]) == 2
        assert sum(
            Decimal(str(layer["received_quantity"])) for layer in cost_layers.json()["items"]
        ) == Decimal("10.0000")

        return_payload = {
            "reference": "RET-001",
            "supplier_id": supplier_id,
            "branch_id": branch_id,
            "idempotency_key": "supplier-return-2026-001",
            "reason": "Damaged packaging identified during inspection",
            "lines": [
                {
                    "item_id": item_id,
                    "batch_id": receipt.json()["lines"][0]["batch_id"],
                    "quantity": "2",
                }
            ],
        }
        supplier_return = client.post(
            "/api/procurement/supplier-returns", headers=headers, json=return_payload
        )
        assert supplier_return.status_code == 201, supplier_return.text
        return_id = supplier_return.json()["id"]
        assert (
            client.post(
                "/api/procurement/supplier-returns", headers=headers, json=return_payload
            ).json()["id"]
            == return_id
        )
        dispatched_return = client.post(
            f"/api/procurement/supplier-returns/{return_id}/dispatch", headers=headers
        )
        assert dispatched_return.status_code == 200, dispatched_return.text
        assert dispatched_return.json()["status"] == "dispatched"
        assert (
            client.post(
                f"/api/procurement/supplier-returns/{return_id}/dispatch", headers=headers
            ).json()["status"]
            == "dispatched"
        )

        performance = client.get(f"/api/suppliers/{supplier_id}/performance", headers=headers)
        assert performance.status_code == 200, performance.text
        metrics = performance.json()
        assert metrics["purchase_order_count"] == 1
        assert metrics["fully_received_purchase_order_count"] == 1
        assert metrics["completed_on_time_order_count"] == 1
        assert metrics["completed_late_order_count"] == 0
        assert metrics["on_time_delivery_rate_percent"] == "100.00"
        assert metrics["currency_metrics"] == [
            {
                "currency": "KES",
                "ordered_value": "1255.00000000",
                "received_value": "1255.00000000",
                "outstanding_value": "0E-8",
            }
        ]
        assert metrics["unit_metrics"] == [
            {
                "unit_code": "KG",
                "ordered_quantity": "10.0000",
                "received_quantity": "10.0000",
                "returned_quantity": "2.0000",
                "fulfilment_rate_percent": "100.00",
                "return_rate_percent": "20.00",
            }
        ]

        over_return = {
            **return_payload,
            "reference": "RET-002",
            "idempotency_key": "supplier-return-2026-002",
            "lines": [
                {
                    **return_payload["lines"][0],
                    "quantity": "9",
                }
            ],
        }
        excessive = client.post(
            "/api/procurement/supplier-returns", headers=headers, json=over_return
        )
        assert excessive.status_code == 201
        assert (
            client.post(
                f"/api/procurement/supplier-returns/{excessive.json()['id']}/dispatch",
                headers=headers,
            ).status_code
            == 409
        )

        over_receipt = {
            "reference": "GRN-003",
            "idempotency_key": "grn-create-2026-003",
            "lines": [{"purchase_order_line_id": po_line_id, "quantity": "1"}],
        }
        assert (
            client.post(
                f"/api/procurement/purchase-orders/{po_id}/receipts",
                headers=headers,
                json=over_receipt,
            ).status_code
            == 409
        )

        sale = client.post(
            "/api/sales",
            headers=headers,
            json={
                "branch_id": branch_id,
                "idempotency_key": "sale-cost-layer-0001",
                "reference": "POS-COST-001",
                "lines": [
                    {
                        "item_id": item_id,
                        "quantity": "3",
                        "unit_code": "KG",
                        "unit_price": "150",
                        "currency": "KES",
                    }
                ],
            },
        )
        assert sale.status_code == 201, sale.text
        movement_costs = client.get(
            "/api/procurement/valuation/movement-costs",
            headers=headers,
            params={"branch_id": branch_id, "item_id": item_id},
        )
        assert movement_costs.status_code == 200, movement_costs.text
        cost_report = movement_costs.json()
        assert cost_report["currency_aggregation"] == "separate_currency_buckets_no_conversion"
        assert {event["event_type"] for event in cost_report["events"]} == {
            "cost_consumption",
        }
        assert cost_report["summary"][0]["consumed_quantity"] == "5.0000"
        assert cost_report["summary"][0]["consumed_cost"] == "627.5000"
        sale_costs = client.get(
            "/api/procurement/valuation/movement-costs",
            headers=headers,
            params={"branch_id": branch_id, "item_id": item_id, "source_type": "sale"},
        )
        assert sale_costs.status_code == 200, sale_costs.text
        assert sale_costs.json()["summary"][0]["consumed_quantity"] == "3.0000"
        assert sale_costs.json()["summary"][0]["consumed_cost"] == "376.5000"
        financials = client.get(
            "/api/procurement/valuation/cogs",
            headers=headers,
            params={"branch_id": branch_id, "item_id": item_id},
        )
        assert financials.status_code == 200, financials.text
        financial_row = financials.json()["items"][0]
        assert financial_row["currency"] == "KES"
        assert Decimal(financial_row["revenue"]) == Decimal("450.0000")
        assert Decimal(financial_row["cogs"]) == Decimal("376.5000")
        assert Decimal(financial_row["gross_profit"]) == Decimal("73.5000")
        assert financial_row["profit_comparable"] is True
        assert financials.json()["incomplete_line_count"] == 0
        invalid_period = client.get(
            "/api/procurement/valuation/movement-costs",
            headers=headers,
            params={"from_date": "2026-12-31", "to_date": "2026-01-01"},
        )
        assert invalid_period.status_code == 422

        valuation = client.get(
            "/api/procurement/valuation/on-hand",
            headers=headers,
            params={"branch_id": branch_id, "item_id": item_id},
        )
        assert valuation.status_code == 200, valuation.text
        valuation_item = valuation.json()["items"][0]
        assert valuation_item["quantity_on_hand"] == "5.0000"
        assert valuation_item["costed_quantity"] == "5.0000"
        assert valuation_item["uncosted_quantity"] == "0.0000"
        assert valuation_item["valuation_complete"] is True
        assert valuation_item["cost_layers"][0]["currency"] == "KES"
        assert valuation_item["cost_layers"][0]["carrying_value"] == "627.5000"

    async def verify_ledger() -> None:
        async with factory() as session:
            balance = await session.scalar(
                select(StockBalance).where(
                    StockBalance.organization_id == org_id,
                    StockBalance.branch_id == branch_id,
                    StockBalance.item_id == item_id,
                )
            )
            batch = await session.scalar(
                select(InventoryBatch).where(
                    InventoryBatch.organization_id == org_id, InventoryBatch.item_id == item_id
                )
            )
            batch_balance = await session.scalar(
                select(BatchStockBalance).where(
                    BatchStockBalance.organization_id == org_id,
                    BatchStockBalance.item_id == item_id,
                )
            )
            movements = list(
                (
                    await session.scalars(
                        select(StockMovement).where(
                            StockMovement.organization_id == org_id,
                            StockMovement.source_type == "purchase_receipt",
                        )
                    )
                ).all()
            )
            po = await session.get(PurchaseOrder, po_id)
            receipts = list(
                (
                    await session.scalars(
                        select(GoodsReceipt).where(GoodsReceipt.organization_id == org_id)
                    )
                ).all()
            )
            cost_layers = list(
                (
                    await session.scalars(
                        select(InventoryCostLayer).where(
                            InventoryCostLayer.organization_id == org_id
                        )
                    )
                ).all()
            )
            assert (
                balance is not None
                and batch is not None
                and batch_balance is not None
                and po is not None
            )
            assert balance.quantity_on_hand == Decimal("5.0000")
            assert batch_balance.quantity_on_hand == Decimal("5.0000")
            return_movements = list(
                (
                    await session.scalars(
                        select(StockMovement).where(
                            StockMovement.organization_id == org_id,
                            StockMovement.source_type == "supplier_return",
                        )
                    )
                ).all()
            )
            assert len(return_movements) == 1
            assert return_movements[0].quantity_delta == Decimal("-2.0000")
            assert po.status == "received"
            assert len(movements) == 2
            assert len(receipts) == 2
            assert len(cost_layers) == 2
            assert sum(layer.received_quantity for layer in cost_layers) == Decimal("10.0000")
            assert sum(layer.remaining_quantity for layer in cost_layers) == Decimal("5.0000")
            allocations = list(
                (
                    await session.scalars(
                        select(InventoryCostAllocation).where(
                            InventoryCostAllocation.organization_id == org_id
                        )
                    )
                ).all()
            )
            assert len(allocations) == 3
            assert sum(row.quantity for row in allocations) == Decimal("5.0000")
            assert sum(row.extended_cost for row in allocations) == Decimal("627.5000")
            assert all(row.unit_cost == Decimal("125.5000") for row in allocations)
            assert all(row.currency == "KES" for row in allocations)

    asyncio.run(verify_ledger())
    asyncio.run(engine.dispose())
