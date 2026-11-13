"""Tests for tenant-scoped replenishment policy management."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from veristock.api.replenishment import (
    ReplenishmentPolicyWrite,
    upsert_replenishment_policy,
)


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def one_or_none(self):
        return self.row


class FakeSession:
    def __init__(self, *, scope_exists=True, policy=None):
        self.scope_exists = scope_exists
        self.policy = policy
        self.added = []
        self.commits = 0
        self.refreshed = []

    async def execute(self, statement):
        return FakeResult(("branch-1", "item-1") if self.scope_exists else None)

    async def scalar(self, statement):
        return self.policy

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        value.updated_at = datetime.now(UTC)
        self.refreshed.append(value)


@pytest.mark.asyncio
async def test_upsert_creates_tenant_scoped_policy_with_actor_provenance():
    session = FakeSession()
    result = await upsert_replenishment_policy(
        branch_id="branch-1",
        item_id="item-1",
        payload=ReplenishmentPolicyWrite(lead_time_days=6, safety_stock_days=3),
        organization=SimpleNamespace(id="org-1"),
        user=SimpleNamespace(id="user-1"),
        session=session,
    )

    assert result.organization_id == "org-1"
    assert result.branch_id == "branch-1"
    assert result.item_id == "item-1"
    assert result.lead_time_days == 6
    assert result.safety_stock_days == 3
    assert result.updated_by_user_id == "user-1"
    assert session.commits == 1
    assert session.refreshed == [result]


@pytest.mark.asyncio
async def test_upsert_updates_existing_policy_without_creating_duplicate():
    policy = SimpleNamespace(
        organization_id="org-1",
        branch_id="branch-1",
        item_id="item-1",
        lead_time_days=2,
        safety_stock_days=1,
        updated_by_user_id="old-user",
    )
    session = FakeSession(policy=policy)
    result = await upsert_replenishment_policy(
        branch_id="branch-1",
        item_id="item-1",
        payload=ReplenishmentPolicyWrite(lead_time_days=8, safety_stock_days=4),
        organization=SimpleNamespace(id="org-1"),
        user=SimpleNamespace(id="user-2"),
        session=session,
    )

    assert result is policy
    assert result.lead_time_days == 8
    assert result.safety_stock_days == 4
    assert result.updated_by_user_id == "user-2"
    assert session.added == []
    assert session.commits == 1


@pytest.mark.asyncio
async def test_upsert_rejects_branch_or_item_outside_active_tenant():
    session = FakeSession(scope_exists=False)

    with pytest.raises(HTTPException) as error:
        await upsert_replenishment_policy(
            branch_id="foreign-branch",
            item_id="foreign-item",
            payload=ReplenishmentPolicyWrite(),
            organization=SimpleNamespace(id="org-1"),
            user=SimpleNamespace(id="user-1"),
            session=session,
        )

    assert error.value.status_code == 404
    assert session.commits == 0


def test_policy_inputs_reject_values_outside_supported_range():
    with pytest.raises(ValueError):
        ReplenishmentPolicyWrite(lead_time_days=181)
    with pytest.raises(ValueError):
        ReplenishmentPolicyWrite(safety_stock_days=-1)
