"""Bounded inputs for AI use cases.

Only precomputed, authorized metrics cross this boundary. This module deliberately
does not accept SQL, ORM entities, database sessions, or arbitrary tenant data.
"""

from datetime import date
from decimal import Decimal

from pydantic import Field, model_validator

from .contracts import AIContract


class ReportMetric(AIContract):
    """One deterministic metric prepared by the reporting domain."""

    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    value: Decimal
    unit: str | None = Field(default=None, max_length=40)
    source_reference: str = Field(min_length=1, max_length=120)


class ReportNarrativeRequest(AIContract):
    """Safe, structured input for narrative generation."""

    period_start: date
    period_end: date
    metrics: tuple[ReportMetric, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_period_and_metrics(self) -> "ReportNarrativeRequest":
        if self.period_end < self.period_start:
            raise ValueError("Report period end must not precede its start")
        keys = [metric.key for metric in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("Report metric keys must be unique")
        references = [metric.source_reference for metric in self.metrics]
        if len(references) != len(set(references)):
            raise ValueError("Report source references must be unique")
        return self
