# ruff: noqa: E501
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
from veristock.inventory.models import InventoryItem, StockBalance, StockMovement
from veristock.organizations.models import Branch
from veristock.stocktaking.models import StocktakeObservation


def test_blind_stocktake_capture_submit_and_recount(tmp_path) -> None:
    import asyncio

    async def seed(database_url: str) -> tuple[str, str, str, str, str]:
        engine = create_async_engine(database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        user_id, supervisor_id, org_id, branch_id, item_id = (
            str(uuid4()) for _ in range(5)
        )
        membership_id, supervisor_membership_id, role_id, approver_role_id = (
            str(uuid4()) for _ in range(4)
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with factory() as session:
                session.add_all(
                    [
                        User(id=user_id, identifier="counter@example.com", password_hash="x"),
                        User(
                            id=supervisor_id,
                            identifier="supervisor@example.com",
                            password_hash="x",
                        ),
                        Organization(id=org_id, kind="client", legal_name="Count Tenant"),
                        OrganizationMembership(
                            id=membership_id,
                            organization_id=org_id,
                            user_id=user_id,
                            status="active",
                        ),
                        Role(id=role_id, code="count_team", name="Count Team", scope="client"),
                        Role(
                            id=approver_role_id,
                            code="stocktake_approver",
                            name="Stocktake Approver",
                            scope="client",
                        ),
                        MembershipRole(membership_id=membership_id, role_id=role_id),
                        MembershipRole(
                            membership_id=membership_id,
                            role_id=approver_role_id,
                        ),
                        OrganizationMembership(
                            id=supervisor_membership_id,
                            organization_id=org_id,
                            user_id=supervisor_id,
                            status="active",
                        ),
                        MembershipRole(
                            membership_id=supervisor_membership_id,
                            role_id=approver_role_id,
                        ),
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
                for code in ("stocktake.manage", "stocktake.read", "stocktake.count", "stocktake.submit", "stocktake.approve"):
                    permission_id = str(uuid4())
                    session.add(
                        Permission(id=permission_id, code=code, description=code)
                    )
                    session.add(
                        RolePermission(role_id=role_id, permission_id=permission_id)
                    )
                    if code == "stocktake.approve":
                        session.add(
                            RolePermission(
                                role_id=approver_role_id,
                                permission_id=permission_id,
                            )
                        )
                await session.commit()
        finally:
            await engine.dispose()
        return user_id, supervisor_id, org_id, branch_id, item_id

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'stocktaking.db'}"
    user_id, supervisor_id, org_id, branch_id, item_id = asyncio.run(seed(database_url))
    tokens = TokenService("s" * 32)
    token = tokens.create(user_id, timedelta(minutes=10), token_type="access")
    settings = Settings(
        environment=Environment.TEST,
        database_url=database_url,
        stocktake_evidence_storage_dir=tmp_path / "private-evidence",
    )
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

        evidence_url = (
            f"/api/stocktakes/{stocktake_id}/observations/{counted.json()['id']}/evidence"
        )
        invalid_evidence = client.post(
            evidence_url,
            headers={**headers, "Content-Type": "text/plain"},
            content=b"not an image",
        )
        assert invalid_evidence.status_code == 415

        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000b49444154789c636000020000050001a5f645400000000049454e44ae426082"
        )
        uploaded_evidence = client.post(
            evidence_url,
            headers={**headers, "Content-Type": "image/png", "X-Filename": "../shelf.png"},
            content=png,
        )
        assert uploaded_evidence.status_code == 201
        evidence = uploaded_evidence.json()
        assert evidence["original_filename"] == "shelf.png"
        assert evidence["media_type"] == "image/png"
        assert evidence["byte_size"] == len(png)
        assert len(evidence["sha256_digest"]) == 64

        listed_evidence = client.get(evidence_url, headers=headers)
        assert listed_evidence.status_code == 200
        assert [entry["id"] for entry in listed_evidence.json()] == [evidence["id"]]
        downloaded_evidence = client.get(
            f"/api/stocktakes/{stocktake_id}/evidence/{evidence['id']}/content",
            headers=headers,
        )
        assert downloaded_evidence.status_code == 200
        assert downloaded_evidence.content == png
        assert downloaded_evidence.headers["x-content-type-options"] == "nosniff"
        assert downloaded_evidence.headers["cache-control"] == "private, no-store"

        submitted = client.post(f"/api/stocktakes/{stocktake_id}/submit", headers=headers)
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"

        supervisor_token = tokens.create(
            supervisor_id, timedelta(minutes=10), token_type="access"
        )
        supervisor_headers = {
            "Authorization": f"Bearer {supervisor_token}",
            "X-Organization-ID": org_id,
        }
        missing_rejection_reason = client.post(
            f"/api/stocktakes/{stocktake_id}/reject",
            headers=supervisor_headers,
        )
        assert missing_rejection_reason.status_code == 422
        whitespace_rejection_reason = client.post(
            f"/api/stocktakes/{stocktake_id}/reject",
            headers=supervisor_headers,
            json={"reason_code": "other", "reason": "          "},
        )
        assert whitespace_rejection_reason.status_code == 422
        rejected = client.post(
            f"/api/stocktakes/{stocktake_id}/reject",
            headers=supervisor_headers,
            json={
                "reason_code": "evidence_insufficient",
                "reason": "The submitted count needs supporting evidence.",
            },
        )
        assert rejected.status_code == 201
        assert rejected.json()["round_number"] == 2

        rejection_recount = client.post(
            f"/api/stocktakes/{stocktake_id}/observations",
            headers=headers,
            json={
                "item_id": item_id,
                "counted_quantity": "11",
                "unit_code": "EA",
                "idempotency_key": "count-device-rejected-0001",
            },
        )
        assert rejection_recount.status_code == 201
        rejection_submit = client.post(
            f"/api/stocktakes/{stocktake_id}/submit",
            headers=headers,
        )
        assert rejection_submit.status_code == 200

        missing_reason = client.post(
            f"/api/stocktakes/{stocktake_id}/recount",
            headers=headers,
        )
        assert missing_reason.status_code == 422
        whitespace_recount_reason = client.post(
            f"/api/stocktakes/{stocktake_id}/recount",
            headers=headers,
            json={"reason_code": "other", "reason": "          "},
        )
        assert whitespace_recount_reason.status_code == 422

        recount = client.post(
            f"/api/stocktakes/{stocktake_id}/recount",
            headers=headers,
            json={
                "reason_code": "count_discrepancy",
                "reason": "Initial physical count did not match expected stock.",
            },
        )
        assert recount.status_code == 201
        assert recount.json()["round_number"] == 3

        zero_count = client.post(
            f"/api/stocktakes/{stocktake_id}/observations",
            headers=headers,
            json={
                "item_id": item_id,
                "counted_quantity": "10",
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

        async def record_post_count_movement() -> None:
            engine = create_async_engine(database_url)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    observation = await session.scalar(
                        select(StocktakeObservation)
                        .where(StocktakeObservation.stocktake_id == stocktake_id)
                        .order_by(StocktakeObservation.counted_at.desc())
                    )
                    balance = await session.scalar(
                        select(StockBalance).where(
                            StockBalance.organization_id == org_id,
                            StockBalance.branch_id == branch_id,
                            StockBalance.item_id == item_id,
                        )
                    )
                    assert observation is not None
                    assert balance is not None
                    balance.quantity_on_hand -= Decimal("2")
                    session.add(
                        StockMovement(
                            id=str(uuid4()),
                            organization_id=org_id,
                            branch_id=branch_id,
                            item_id=item_id,
                            quantity_delta=Decimal("-2"),
                            unit_code="EA",
                            source_type="manual_adjustment",
                            idempotency_key="manual-after-count-0001",
                            actor_user_id=user_id,
                            occurred_at=observation.counted_at + timedelta(seconds=1),
                        )
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(record_post_count_movement())

        review_queue = client.get("/api/stocktakes/review-queue", headers=headers)
        assert review_queue.status_code == 200
        assert len(review_queue.json()) == 1
        queued = review_queue.json()[0]
        assert queued["stocktake_id"] == stocktake_id
        assert queued["reference"] == "ST-001"
        assert queued["branch_name"] == "Main"
        assert queued["round_number"] == 3
        assert queued["item_count"] == 1
        assert queued["variance_count"] == 1
        assert queued["shortage_count"] == 1
        assert queued["surplus_count"] == 0

        reconciliation = client.get(
            f"/api/stocktakes/{stocktake_id}/reconciliation",
            headers=headers,
        )
        assert reconciliation.status_code == 200
        line = reconciliation.json()["lines"][0]
        assert line["expected_quantity"] == "14.0000"
        assert line["counted_quantity"] == "10.0000"
        assert line["variance_quantity"] == "-4.0000"
        assert line["variance_status"] == "shortage"
        assert line["post_count_movement_delta"] == "-2.0000"
        assert line["reconciled_quantity"] == "8.0000"
        assert line["current_quantity"] == "12.0000"

        same_user_approval = client.post(
            f"/api/stocktakes/{stocktake_id}/approve", headers=headers
        )
        assert same_user_approval.status_code == 409

        cannot_reject_own_count = client.post(
            f"/api/stocktakes/{stocktake_id}/reject",
            headers=headers,
            json={
                "reason_code": "variance_unexplained",
                "reason": "This counter cannot independently reject their own count.",
            },
        )
        assert cannot_reject_own_count.status_code == 409

        approved = client.post(
            f"/api/stocktakes/{stocktake_id}/approve", headers=supervisor_headers
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"
        assert approved.json()["adjustment_count"] == 1
        assert approved.json()["total_quantity_delta"] == "-4.0000"

        decision_history = client.get(
            f"/api/stocktakes/{stocktake_id}/decisions",
            headers=headers,
        )
        assert decision_history.status_code == 200
        decisions = decision_history.json()
        assert [entry["action"] for entry in decisions] == [
            "rejected",
            "recount_requested",
            "approved",
        ]
        assert decisions[0]["reason_code"] == "evidence_insufficient"
        assert decisions[0]["reason"] == (
            "The submitted count needs supporting evidence."
        )
        assert decisions[0]["actor_user_id"] == supervisor_id
        assert decisions[1]["reason_code"] == "count_discrepancy"
        assert decisions[1]["reason"] == (
            "Initial physical count did not match expected stock."
        )
        assert decisions[1]["actor_user_id"] == user_id
        assert decisions[2]["actor_user_id"] == supervisor_id

    async def verify() -> None:
        engine = create_async_engine(database_url)
        try:
            async with async_sessionmaker(engine)() as session:
                balance = await session.scalar(
                    select(StockBalance).where(
                        StockBalance.organization_id == org_id,
                        StockBalance.branch_id == branch_id,
                        StockBalance.item_id == item_id,
                    )
                )
                movements = list(
                    (
                        await session.scalars(
                            select(StockMovement).where(
                                StockMovement.organization_id == org_id,
                                StockMovement.source_type == "stocktake_adjustment",
                            )
                        )
                    ).all()
                )
                observations = list(
                    (
                        await session.scalars(
                            select(StocktakeObservation).where(
                                StocktakeObservation.stocktake_id == stocktake_id
                            )
                        )
                    ).all()
                )
                assert len(observations) == 3
                assert balance is not None
                assert balance.quantity_on_hand == Decimal("8")
                assert len(movements) == 1
        finally:
            await engine.dispose()

    asyncio.run(verify())
