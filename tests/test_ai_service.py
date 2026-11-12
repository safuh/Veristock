"""Tests for provider execution and report narrative safety boundaries."""

import asyncio
from datetime import date

import pytest

from veristock.ai.context import AIExecutionContext
from veristock.ai.contracts import ModelRun, ReportNarrative
from veristock.ai.provider import AIProvider
from veristock.ai.requests import ReportMetric, ReportNarrativeRequest
from veristock.ai.service import (
    AIProviderFailure,
    AIService,
    AIServiceUnavailable,
)


class FakeProvider:
    provider_name = "test-provider"
    model_name = "test-model"

    async def generate_report_narrative(
        self,
        request: ReportNarrativeRequest,
    ) -> ReportNarrative:
        return ReportNarrative(
            summary="Sales increased during the selected period.",
            observations=("Sales increased.",),
            recommended_actions=("Review replenishment levels.",),
            source_references=tuple(
                metric.source_reference for metric in request.metrics
            ),
            run=ModelRun(
                provider=self.provider_name,
                model=self.model_name,
                latency_ms=5,
            ),
        )


def request() -> ReportNarrativeRequest:
    return ReportNarrativeRequest(
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 7),
        metrics=(
            ReportMetric(
                key="sales_total",
                label="Sales total",
                value="1250.00",
                unit="KES",
                source_reference="sales:weekly-total",
            ),
        ),
    )


def context() -> AIExecutionContext:
    return AIExecutionContext(
        organization_id="org-123",
        user_id="user-123",
        request_id="request-123",
    )


def test_report_request_rejects_invalid_period_and_duplicate_metrics() -> None:
    with pytest.raises(ValueError, match="period end"):
        ReportNarrativeRequest(
            period_start=date(2026, 11, 8),
            period_end=date(2026, 11, 1),
            metrics=request().metrics,
        )

    metric = request().metrics[0]
    with pytest.raises(ValueError, match="keys must be unique"):
        ReportNarrativeRequest(
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 7),
            metrics=(metric, metric),
        )


@pytest.mark.asyncio
async def test_service_requires_provider() -> None:
    with pytest.raises(AIServiceUnavailable):
        await AIService().generate_report_narrative(request(), context())


@pytest.mark.asyncio
async def test_service_returns_validated_narrative() -> None:
    service = AIService(FakeProvider())

    result = await service.generate_report_narrative(request(), context())

    assert result.summary.startswith("Sales increased")
    assert result.source_references == ("sales:weekly-total",)


@pytest.mark.asyncio
async def test_service_rejects_unknown_source_references() -> None:
    class InvalidReferenceProvider(FakeProvider):
        async def generate_report_narrative(
            self,
            report_request: ReportNarrativeRequest,
        ) -> ReportNarrative:
            result = await super().generate_report_narrative(report_request)
            return result.model_copy(
                update={"source_references": ("sales:another-tenant",)}
            )

    with pytest.raises(AIProviderFailure, match="unknown report source"):
        await AIService(InvalidReferenceProvider()).generate_report_narrative(
            request(),
            context(),
        )


@pytest.mark.asyncio
async def test_service_enforces_provider_timeout() -> None:
    class SlowProvider(FakeProvider):
        async def generate_report_narrative(
            self,
            report_request: ReportNarrativeRequest,
        ) -> ReportNarrative:
            await asyncio.sleep(0.05)
            return await super().generate_report_narrative(report_request)

    with pytest.raises(AIProviderFailure, match="timed out"):
        await AIService(SlowProvider(), timeout_seconds=0.001).generate_report_narrative(
            request(),
            context(),
        )


def test_context_rejects_blank_identity() -> None:
    with pytest.raises(ValueError, match="organization_id"):
        AIExecutionContext(organization_id=" ", user_id="user-123")
