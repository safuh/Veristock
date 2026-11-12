"""Tests for deterministic tenant inventory reports and AI narratives."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from veristock.ai.contracts import ModelRun, ReportNarrative
from veristock.ai.requests import ReportNarrativeRequest
from veristock.ai.service import AIService
from veristock.api.reports import (
    generate_inventory_narrative,
    inventory_report,
)


class FakeResult:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def one(self):
        return self._row

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self):
        self.scalar_values = iter((3, 2))
        self.execute_results = iter(
            (
                FakeResult(row=(2, Decimal("14.5000"))),
                FakeResult(
                    rows=[
                        ("branch-1", "MAIN", "Main branch", 2, Decimal("14.5000")),
                        ("branch-2", "WEST", "West branch", 0, Decimal("0")),
                    ]
                ),
            )
        )
        self.added = []
        self.commit_count = 0

    async def scalar(self, statement):
        return next(self.scalar_values)

    async def execute(self, statement):
        return next(self.execute_results)

    def add(self, record):
        self.added.append(record)

    async def commit(self):
        self.commit_count += 1


class FakeProvider:
    provider_name = "test-provider"
    model_name = "test-model"

    async def generate_report_narrative(
        self,
        report_request: ReportNarrativeRequest,
    ) -> ReportNarrative:
        return ReportNarrative(
            summary="The inventory snapshot contains three active items.",
            observations=("Two items currently have stock.",),
            recommended_actions=("Review the item without stock.",),
            source_references=tuple(
                metric.source_reference for metric in report_request.metrics
            ),
            run=ModelRun(
                provider=self.provider_name,
                model=self.model_name,
                latency_ms=3,
            ),
        )


def fake_request():
    return SimpleNamespace(state=SimpleNamespace(request_id="request-1"))


@pytest.mark.asyncio
async def test_inventory_report_returns_deterministic_tenant_snapshot():
    report = await inventory_report(
        organization=SimpleNamespace(id="org-1"),
        session=FakeSession(),
    )

    assert report.organization_id == "org-1"
    assert report.active_item_count == 3
    assert report.active_branch_count == 2
    assert report.stocked_item_count == 2
    assert report.zero_stock_item_count == 1
    assert report.total_units_on_hand == Decimal("14.5000")
    assert len(report.branches) == 2
    assert report.branches[0].branch_id == "branch-1"
    assert report.metrics[-1].source_reference == "inventory:summary:total-units"


@pytest.mark.asyncio
async def test_inventory_narrative_persists_tenant_scoped_success_audit():
    session = FakeSession()
    result = await generate_inventory_narrative(
        request=fake_request(),
        organization=SimpleNamespace(id="org-1"),
        user=SimpleNamespace(id="user-1"),
        session=session,
        ai_service=AIService(FakeProvider()),
    )

    assert result.narrative.summary.startswith("The inventory snapshot")
    assert result.advisory_only is True
    assert session.commit_count == 1
    audit = session.added[0]
    assert audit.organization_id == "org-1"
    assert audit.user_id == "user-1"
    assert audit.status == "succeeded"
    assert audit.provider == "test-provider"
    assert audit.model == "test-model"
    assert audit.request_id == "request-1"
    assert len(audit.source_references) == 5


@pytest.mark.asyncio
async def test_unconfigured_ai_provider_is_audited_and_returns_503():
    session = FakeSession()

    with pytest.raises(HTTPException) as error:
        await generate_inventory_narrative(
            request=fake_request(),
            organization=SimpleNamespace(id="org-1"),
            user=SimpleNamespace(id="user-1"),
            session=session,
            ai_service=AIService(),
        )

    assert error.value.status_code == 503
    assert session.commit_count == 1
    audit = session.added[0]
    assert audit.status == "unavailable"
    assert audit.failure_code == "provider_not_configured"
    assert audit.organization_id == "org-1"
    assert audit.user_id == "user-1"

@pytest.mark.asyncio
async def test_ai_provider_status_does_not_expose_configuration_secrets():
    from veristock.api.reports import ai_provider_status

    configured = await ai_provider_status(
        organization=SimpleNamespace(id="org-1"),
        ai_service=AIService(FakeProvider()),
    )
    unconfigured = await ai_provider_status(
        organization=SimpleNamespace(id="org-1"),
        ai_service=AIService(),
    )

    assert configured.configured is True
    assert configured.provider == "test-provider"
    assert configured.model == "test-model"
    assert unconfigured.configured is False
    assert unconfigured.provider is None
    assert unconfigured.model is None


class FakeForecastSession:
    def __init__(self):
        self.statement = None
        self.execute_count = 0

    async def execute(self, statement):
        self.execute_count += 1
        if self.execute_count > 1:
            return FakeResult(rows=[])
        self.statement = statement
        item = SimpleNamespace(
            id="item-1",
            sku="SKU-1",
            name="Cooking oil",
            base_unit_code="bottle",
        )
        return FakeResult(
            rows=[
                (
                    item,
                    Decimal("60"),
                    12,
                    Decimal("10"),
                    5,
                    2,
                    None,
                    None,
                )
            ]
        )


@pytest.mark.asyncio
async def test_demand_forecast_uses_tenant_scoped_sales_and_stock_totals():
    from veristock.api.reports import inventory_demand_forecast

    session = FakeForecastSession()
    result = await inventory_demand_forecast(
        organization=SimpleNamespace(id="org-1"),
        session=session,
        lookback_days=30,
        target_days=14,
        lead_time_days=5,
        safety_stock_days=2,
        limit=200,
        offset=0,
    )

    assert result.branch_id is None
    assert result.lookback_days == 30
    assert result.target_days == 14
    assert result.lead_time_days == 5
    assert result.safety_stock_days == 2
    assert len(result.items) == 1
    item = result.items[0]
    assert item.item_id == "item-1"
    assert item.units_sold_in_window == Decimal("60")
    assert item.sales_activity_days == 12
    assert item.sales_activity_fraction == Decimal("0.4")
    assert item.average_daily_demand == Decimal("2")
    assert item.quantity_on_hand == Decimal("10")
    assert item.days_of_cover == Decimal("5")
    assert item.reorder_point_quantity == Decimal("14")
    assert item.days_until_reorder == Decimal("0")
    assert item.recommended_replenishment_quantity == Decimal("32")
    assert item.lead_time_days == 5
    assert item.safety_stock_days == 2
    assert item.planning_policy_source == "request_override"
    assert item.sales_source_reference == "sales:posted:item-1:30d"
    assert item.stock_source_reference == "stock:balance:item-1:all-branches"
    assert session.statement is not None
    sql = str(session.statement)
    assert "sales.organization_id" in sql
    assert "sale_lines.organization_id" in sql
    assert "stock_balances.organization_id" in sql
    assert "inventory_items.organization_id" in sql
    assert "CASE WHEN" in sql
    assert "ORDER BY" in sql

class FakePolicyScalars:
    def __init__(self, policies):
        self.policies = policies

    def all(self):
        return self.policies


class FakeBranchForecastSession(FakeForecastSession):
    def __init__(self, *, policy=None):
        super().__init__()
        self.policy = policy
        self.policy_statement = None
        self.movement_rows = []

    async def execute(self, statement):
        self.execute_count += 1
        if self.execute_count > 1:
            return FakeResult(rows=self.movement_rows)
        self.statement = statement
        item = SimpleNamespace(
            id="item-1",
            sku="SKU-1",
            name="Cooking oil",
            base_unit_code="bottle",
        )
        return FakeResult(
            rows=[
                (
                    item,
                    Decimal("60"),
                    12,
                    Decimal("10"),
                    5,
                    2,
                    None,
                    None,
                )
            ]
        )

    async def scalar(self, statement):
        return "branch-1"

    async def scalars(self, statement):
        self.policy_statement = statement
        return FakePolicyScalars([self.policy] if self.policy is not None else [])


@pytest.mark.asyncio
async def test_branch_forecast_uses_saved_item_policy_and_tenant_scope():
    from veristock.api.reports import inventory_demand_forecast

    policy = SimpleNamespace(
        organization_id="org-1",
        branch_id="branch-1",
        item_id="item-1",
        lead_time_days=5,
        safety_stock_days=2,
    )
    session = FakeBranchForecastSession(policy=policy)
    # Effective planning values are selected from the joined policy row.
    async def execute(statement):
        session.execute_count += 1
        if session.execute_count > 1:
            return FakeResult(rows=session.movement_rows)
        session.statement = statement
        return await async_branch_execute_with_policy(statement)

    session.execute = execute
    result = await inventory_demand_forecast(
        organization=SimpleNamespace(id="org-1"),
        session=session,
        branch_id="branch-1",
        lookback_days=30,
        target_days=14,
        lead_time_days=None,
        safety_stock_days=None,
        limit=200,
        offset=0,
    )

    item = result.items[0]
    assert item.lead_time_days == 5
    assert item.safety_stock_days == 2
    assert item.planning_policy_source == "saved_policy"
    assert item.reorder_point_quantity == Decimal("14")
    assert item.recommended_replenishment_quantity == Decimal("32")
    assert result.lead_time_days is None
    assert session.statement is not None
    policy_sql = str(session.statement)
    assert "replenishment_policies.organization_id" in policy_sql
    assert "replenishment_policies.branch_id" in policy_sql


@pytest.mark.asyncio
async def test_branch_forecast_request_override_takes_precedence_over_saved_policy():
    from veristock.api.reports import inventory_demand_forecast

    policy = SimpleNamespace(
        organization_id="org-1",
        branch_id="branch-1",
        item_id="item-1",
        lead_time_days=5,
        safety_stock_days=2,
    )
    session = FakeBranchForecastSession(policy=policy)
    async def execute(statement):
        session.execute_count += 1
        if session.execute_count > 1:
            return FakeResult(rows=session.movement_rows)
        session.statement = statement
        return await async_branch_execute_with_override(statement)

    session.execute = execute
    result = await inventory_demand_forecast(
        organization=SimpleNamespace(id="org-1"),
        session=session,
        branch_id="branch-1",
        lead_time_days=1,
        safety_stock_days=1,
        lookback_days=30,
        target_days=14,
        limit=200,
        offset=0,
    )

    item = result.items[0]
    assert item.lead_time_days == 1
    assert item.safety_stock_days == 1
    assert item.planning_policy_source == "request_override"
    assert item.reorder_point_quantity == Decimal("4")


async def async_branch_execute_with_policy(statement):
    item = SimpleNamespace(
        id="item-1", sku="SKU-1", name="Cooking oil", base_unit_code="bottle"
    )
    return FakeResult(
        rows=[(item, Decimal("60"), 12, Decimal("10"), 5, 2, 5, 2)]
    )


async def async_branch_execute_with_override(statement):
    item = SimpleNamespace(
        id="item-1", sku="SKU-1", name="Cooking oil", base_unit_code="bottle"
    )
    return FakeResult(
        rows=[(item, Decimal("60"), 12, Decimal("10"), 1, 1, 5, 2)]
    )



@pytest.mark.asyncio
async def test_branch_forecast_exposes_opening_balance_anchored_availability():
    from veristock.api.reports import inventory_demand_forecast

    session = FakeBranchForecastSession()
    now = datetime.now(UTC)
    session.movement_rows = [
        ("item-1", Decimal("10"), "opening_balance", now - timedelta(days=10)),
        ("item-1", Decimal("-10"), "sale", now - timedelta(days=8)),
    ]
    result = await inventory_demand_forecast(
        organization=SimpleNamespace(id="org-1"),
        session=session,
        branch_id="branch-1",
        lookback_days=7,
        target_days=14,
        lead_time_days=None,
        safety_stock_days=None,
        limit=200,
        offset=0,
    )

    item = result.items[0]
    assert item.stock_availability_status == "complete"
    assert item.stock_availability_fraction == Decimal("0")
    assert item.stock_availability_coverage_fraction == Decimal("1")
    assert item.stock_availability_source_reference == "stock-movements:item-1:branch-1"
    # Availability is evidence only; this release does not inflate demand.
    assert item.average_daily_demand == Decimal("60") / Decimal("7")


@pytest.mark.asyncio
async def test_all_branch_forecast_does_not_claim_pooled_availability():
    from veristock.api.reports import inventory_demand_forecast

    result = await inventory_demand_forecast(
        organization=SimpleNamespace(id="org-1"),
        session=FakeForecastSession(),
        lookback_days=30,
        target_days=14,
        lead_time_days=None,
        safety_stock_days=None,
        limit=200,
        offset=0,
    )

    item = result.items[0]
    assert item.stock_availability_status == "branch_required"
    assert item.stock_availability_fraction is None
    assert item.stock_availability_coverage_fraction is None
