"""Validated contracts shared by AI adapters and application use cases.

These types describe advisory outputs only. They are not inventory commands and
must never be persisted as authoritative stock, sale, or reconciliation facts.
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AIContract(BaseModel):
    """Base class for strict, versionable AI boundary contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelRun(AIContract):
    """Provenance for one model execution."""

    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    model_version: str | None = Field(default=None, max_length=120)
    latency_ms: int = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    request_id: str | None = Field(default=None, max_length=100)


class VisionMatchCandidate(AIContract):
    """A possible catalogue match proposed from image evidence."""

    item_id: str = Field(min_length=1, max_length=36)
    sku: str | None = Field(default=None, max_length=80)
    label: str = Field(min_length=1, max_length=240)
    confidence: float = Field(ge=0.0, le=1.0)


class VisionAssessment(AIContract):
    """Vision output requiring explicit human confirmation."""

    candidates: tuple[VisionMatchCandidate, ...] = Field(max_length=10)
    extracted_barcode: str | None = Field(default=None, max_length=128)
    extracted_text: str | None = Field(default=None, max_length=1000)
    suggested_quantity: Decimal | None = Field(default=None, ge=0)
    quantity_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    needs_manual_review: bool = True
    run: ModelRun


class DemandForecastPoint(AIContract):
    """One forecast period with a point estimate and uncertainty bounds."""

    period_start: date
    predicted_demand: Decimal = Field(ge=0)
    lower_bound: Decimal = Field(ge=0)
    upper_bound: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "DemandForecastPoint":
        if not self.lower_bound <= self.predicted_demand <= self.upper_bound:
            raise ValueError("Forecast bounds must contain the point estimate")
        return self


class DemandForecast(AIContract):
    """Forecast output for a single item and branch."""

    organization_id: str = Field(min_length=1, max_length=36)
    branch_id: str = Field(min_length=1, max_length=36)
    item_id: str = Field(min_length=1, max_length=36)
    generated_on: date
    horizon_days: int = Field(gt=0, le=365)
    points: tuple[DemandForecastPoint, ...] = Field(min_length=1, max_length=365)
    run: ModelRun


class AnomalyFinding(AIContract):
    """Explainable anomaly signal; never a fraud determination."""

    category: str = Field(min_length=1, max_length=80)
    severity: Literal["low", "medium", "high", "critical"]
    score: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=1, max_length=500)
    evidence_references: tuple[str, ...] = Field(max_length=50)
    run: ModelRun


class ReportNarrative(AIContract):
    """Narrative generated from already-computed, authorized report metrics."""

    summary: str = Field(min_length=1, max_length=3000)
    observations: tuple[str, ...] = Field(max_length=30)
    recommended_actions: tuple[str, ...] = Field(max_length=30)
    source_references: tuple[str, ...] = Field(max_length=100)
    run: ModelRun
