"""AI capabilities isolated from Veristock business domains."""

from .context import AIExecutionContext
from .contracts import (
    AnomalyFinding,
    DemandForecast,
    DemandForecastPoint,
    ModelRun,
    ReportNarrative,
    VisionAssessment,
    VisionMatchCandidate,
)
from .models import AIExecutionRecord
from .provider import AIProvider
from .provider_http import OpenAICompatibleProvider
from .requests import ReportMetric, ReportNarrativeRequest
from .service import AIProviderFailure, AIService, AIServiceUnavailable

__all__ = [
    "AIExecutionContext",
    "AIExecutionRecord",
    "AIProvider",
    "AIProviderFailure",
    "AIService",
    "AIServiceUnavailable",
    "OpenAICompatibleProvider",
    "AnomalyFinding",
    "DemandForecast",
    "DemandForecastPoint",
    "ModelRun",
    "ReportMetric",
    "ReportNarrative",
    "ReportNarrativeRequest",
    "VisionAssessment",
    "VisionMatchCandidate",
]
