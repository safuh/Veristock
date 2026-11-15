"""Branch authorization regressions for sales operations."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from veristock.api import sales
from veristock.api.sales import SaleCreate, SaleLineCreate


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
