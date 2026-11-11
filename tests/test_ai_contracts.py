"""Validation tests for the isolated AI boundary contracts."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from veristock.ai.contracts import (
    AnomalyFinding,
    DemandForecastPoint,
    ModelRun,
    VisionAssessment,
)


def model_run() -> ModelRun:
    return ModelRun(
        provider="test",
        model="fixture",
        latency_ms=12,
        confidence=0.9,
    )


def test_forecast_requires_bounds_to_contain_prediction() -> None:
    with pytest.raises(ValidationError, match="Forecast bounds"):
        DemandForecastPoint(
            period_start=date(2026, 11, 11),
            predicted_demand=Decimal("12"),
            lower_bound=Decimal("13"),
            upper_bound=Decimal("18"),
        )


def test_vision_assessment_defaults_to_manual_review() -> None:
    result = VisionAssessment(candidates=(), run=model_run())

    assert result.needs_manual_review is True
    assert result.suggested_quantity is None


def test_anomaly_signal_is_not_a_fraud_verdict() -> None:
    result = AnomalyFinding(
        category="unusual_adjustment",
        severity="high",
        score=0.91,
        summary="Adjustment is outside the expected range.",
        evidence_references=("movement:123",),
        run=model_run(),
    )

    assert result.category == "unusual_adjustment"
    assert result.score == 0.91


def test_ai_contracts_reject_unexpected_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ModelRun(
            provider="test",
            model="fixture",
            latency_ms=1,
            stock_quantity=100,
        )
