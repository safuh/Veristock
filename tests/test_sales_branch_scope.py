"""Branch authorization regressions for sales operations."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from veristock.api import sales
from veristock.api.sales import (
    OpeningBalanceCreate,
    SaleCreate,
    SaleLineCreate,
)


class FakeScalarRows:
    def all(self):
        return []


class FakeSession:
    def __init__(self):
        self.scalar_calls = 0
        self.scalars_calls = 0
        self.statement = None

    async def scalar(self, statement):
        self.scalar_calls += 1
        return None

    async def scalars(self, statement):
        self.scalars_calls += 1
        self.statement = statement
        return FakeScalarRows()


@pytest.mark.asyncio
async def test_sale_post_checks_assignment_before_idempotency_lookup(monkeypatch):
    async def denied(session, user, organization, branch_id):
        raise HTTPException(status_code=403, detail="Branch assignment required")

    monkeypatch.setattr(sales, "require_branch_assignment", denied)
    session = FakeSession()
    payload = SaleCreate(
        branch_id="branch-2",
        idempotency_key="sale-key-123",
        lines=[
            SaleLineCreate(
                item_id="item-1",
                quantity="1",
                unit_code="EA",
            )
        ],
    )

    with pytest.raises(HTTPException) as error:
        await sales.post_sale(
            payload=payload,
            organization=SimpleNamespace(id="org-1"),
            user=SimpleNamespace(id="field-user"),
            session=session,
        )

    assert error.value.status_code == 403
    assert session.scalar_calls == 0


@pytest.mark.asyncio
async def test_sales_history_is_filtered_to_assigned_branches(monkeypatch):
    async def assigned(session, user, organization):
        return {"branch-1"}

    monkeypatch.setattr(sales, "accessible_branch_ids", assigned)
    session = FakeSession()

    result = await sales.list_sales(
        organization=SimpleNamespace(id="org-1"),
        user=SimpleNamespace(id="field-user"),
        session=session,
    )

    assert result == []
    assert session.scalars_calls == 1
    assert "sales.branch_id IN" in str(session.statement)


@pytest.mark.asyncio
async def test_sales_history_hides_explicit_unassigned_branch(monkeypatch):
    async def assigned(session, user, organization):
        return {"branch-1"}

    monkeypatch.setattr(sales, "accessible_branch_ids", assigned)
    session = FakeSession()

    with pytest.raises(HTTPException) as error:
        await sales.list_sales(
            organization=SimpleNamespace(id="org-1"),
            user=SimpleNamespace(id="field-user"),
            session=session,
            branch_id="branch-2",
        )

    assert error.value.status_code == 404
    assert session.scalars_calls == 0



@pytest.mark.asyncio
async def test_opening_balance_checks_assignment_before_idempotency_lookup(monkeypatch):
    async def denied(session, user, organization, branch_id):
        raise HTTPException(status_code=403, detail="Branch assignment required")

    monkeypatch.setattr(sales, "require_branch_assignment", denied)
    session = FakeSession()
    payload = OpeningBalanceCreate(
        branch_id="branch-2",
        item_id="item-1",
        quantity="10",
        idempotency_key="opening-key-123",
    )

    with pytest.raises(HTTPException) as error:
        await sales.record_opening_balance(
            payload=payload,
            organization=SimpleNamespace(id="org-1"),
            user=SimpleNamespace(id="field-user"),
            session=session,
        )

    assert error.value.status_code == 403
    assert session.scalar_calls == 0


@pytest.mark.asyncio
async def test_adjustment_checks_assignment_before_idempotency_lookup(monkeypatch):
    async def denied(session, user, organization, branch_id):
        raise HTTPException(status_code=403, detail="Branch assignment required")

    monkeypatch.setattr(sales, "require_branch_assignment", denied)
    session = FakeSession()
    payload = sales.StockAdjustmentCreate(
        branch_id="branch-2",
        item_id="item-1",
        quantity_delta="2",
        unit_code="EA",
        reason="Correct a verified receiving error",
        idempotency_key="adjustment-key-123",
    )

    with pytest.raises(HTTPException) as error:
        await sales.record_stock_adjustment(
            payload=payload,
            organization=SimpleNamespace(id="org-1"),
            user=SimpleNamespace(id="field-user"),
            session=session,
        )

    assert error.value.status_code == 403
    assert session.scalar_calls == 0


@pytest.mark.asyncio
async def test_stock_movement_history_is_filtered_to_assigned_branches(monkeypatch):
    async def assigned(session, user, organization):
        return {"branch-1"}

    monkeypatch.setattr(sales, "accessible_branch_ids", assigned)
    session = FakeSession()

    result = await sales.list_stock_movements(
        organization=SimpleNamespace(id="org-1"),
        user=SimpleNamespace(id="field-user"),
        session=session,
    )

    assert result == []
    assert session.scalars_calls == 1
    assert "stock_movements.branch_id IN" in str(session.statement)


@pytest.mark.asyncio
async def test_stock_movement_history_hides_explicit_unassigned_branch(monkeypatch):
    async def assigned(session, user, organization):
        return {"branch-1"}

    monkeypatch.setattr(sales, "accessible_branch_ids", assigned)
    session = FakeSession()

    with pytest.raises(HTTPException) as error:
        await sales.list_stock_movements(
            organization=SimpleNamespace(id="org-1"),
            user=SimpleNamespace(id="field-user"),
            session=session,
            branch_id="branch-2",
        )

    assert error.value.status_code == 404
    assert session.scalars_calls == 0


def test_stock_adjustment_requires_non_whitespace_reason():
    with pytest.raises(ValueError):
        sales.StockAdjustmentCreate(
            branch_id="branch-1",
            item_id="item-1",
            quantity_delta="1",
            unit_code="EA",
            reason="          ",
            idempotency_key="adjustment-key-123",
        )


@pytest.mark.asyncio
async def test_adjustment_reversal_checks_branch_assignment_before_mutation(monkeypatch):
    async def denied(session, user, organization, branch_id):
        raise HTTPException(status_code=403, detail="Branch assignment required")

    monkeypatch.setattr(sales, "require_branch_assignment", denied)
    session = FakeSession()
    original = SimpleNamespace(
        id="movement-1",
        organization_id="org-1",
        branch_id="branch-2",
        source_type="manual_adjustment",
        quantity_delta=-2,
    )

    async def get_original(statement):
        session.scalar_calls += 1
        return original

    session.scalar = get_original
    with pytest.raises(HTTPException) as error:
        await sales.reverse_manual_stock_adjustment(
            movement_id="movement-1",
            payload=sales.StockMovementReversalCreate(
                reason="Correct an incorrectly recorded adjustment",
                idempotency_key="reverse-key-123",
            ),
            organization=SimpleNamespace(id="org-1"),
            user=SimpleNamespace(id="counter-user"),
            session=session,
        )

    assert error.value.status_code == 403
    assert session.scalar_calls == 1


def test_adjustment_reversal_requires_a_meaningful_reason():
    with pytest.raises(ValueError):
        sales.StockMovementReversalCreate(
            reason="       ",
            idempotency_key="reverse-key-123",
        )
