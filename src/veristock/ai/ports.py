"""Provider-neutral ports for AI capabilities.

Implementations may use Hugging Face, local CPU inference, hosted APIs or
traditional ML. Business domains depend on none of these implementations.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    AnomalyFinding,
    DemandForecast,
    ReportNarrative,
    VisionAssessment,
)


class AIInput(BaseModel):
    """Base for bounded, tenant-scoped data passed into an AI adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DailyDemandObservation(AIInput):
    """Committed stock-out demand for one calendar day."""

    day: date
    quantity: Decimal = Field(ge=0)


class VisionProvider(Protocol):
    """Inspect evidence and suggest catalogue candidates; never post a count."""

    async def assess(
        self,
        image: bytes,
        *,
        mime_type: str,
        organization_id: str,
        branch_id: str,
    ) -> VisionAssessment: ...


class ForecastProvider(Protocol):
    """Forecast demand from authorized, committed historical observations."""

    async def forecast(
        self,
        observations: Sequence[DailyDemandObservation],
        *,
        organization_id: str,
        branch_id: str,
        item_id: str,
        horizon_days: int,
    ) -> DemandForecast: ...


class AnomalyDetector(Protocol):
    """Return explainable risk signals from precomputed business features."""

    async def detect(
        self,
        features: Mapping[str, Decimal | int | float],
        *,
        organization_id: str,
        branch_id: str,
    ) -> Sequence[AnomalyFinding]: ...


class NarrativeGenerator(Protocol):
    """Narrate precomputed metrics; it is not an analytics calculator."""

    async def generate(
        self,
        metrics: Mapping[str, str | Decimal | int],
        *,
        source_references: Sequence[str],
    ) -> ReportNarrative: ...
