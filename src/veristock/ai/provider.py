"""Provider-neutral interfaces for optional AI integrations."""

from typing import Protocol

from .contracts import ReportNarrative
from .requests import ReportNarrativeRequest


class AIProvider(Protocol):
    """Adapter contract for a text-generation provider."""

    @property
    def provider_name(self) -> str:
        """Stable provider identifier."""

    @property
    def model_name(self) -> str:
        """Configured model identifier."""

    async def generate_report_narrative(
        self,
        request: ReportNarrativeRequest,
    ) -> ReportNarrative:
        """Generate narrative from supplied metrics only."""
