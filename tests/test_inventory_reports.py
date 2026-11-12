"""Tests for deterministic tenant inventory reports and AI narratives."""

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
