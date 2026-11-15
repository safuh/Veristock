"""Application service for tenant-safe AI use cases."""

import asyncio

from .context import AIExecutionContext
from .contracts import ReportNarrative
from .provider import AIProvider
from .requests import ReportNarrativeRequest


class AIServiceUnavailable(RuntimeError):
    """Raised when a requested AI capability has no configured provider."""


class AIProviderFailure(RuntimeError):
    """Raised when a provider fails, times out, or returns invalid provenance."""


class AIService:
    """Runs optional AI tasks without granting providers access to business systems."""

    def __init__(
        self,
        provider: AIProvider | None = None,
        *,
        timeout_seconds: float = 20.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._provider = provider
        self._timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        """Whether a provider has been explicitly configured."""
        return self._provider is not None

    @property
    def provider_name(self) -> str | None:
        """Configured provider identifier for audit metadata."""
        return self._provider.provider_name if self._provider is not None else None

    @property
    def model_name(self) -> str | None:
        """Configured model identifier for audit metadata."""
        return self._provider.model_name if self._provider is not None else None

    async def generate_report_narrative(
        self,
        request: ReportNarrativeRequest,
        context: AIExecutionContext,
    ) -> ReportNarrative:
        """Generate a narrative from authorized, precomputed metrics.

        Organization and actor context is required for audit correlation but is
        deliberately not included in the provider request. Provider output may
        only cite source references present in the input metrics.
        """
        if not context.organization_id or not context.user_id:
            raise ValueError("Authenticated organization and user context is required")
        if self._provider is None:
            raise AIServiceUnavailable("AI narrative generation is not configured")

        try:
            result = await asyncio.wait_for(
                self._provider.generate_report_narrative(request),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            raise AIProviderFailure("AI provider request timed out") from exc
        except Exception as exc:
            raise AIProviderFailure("AI provider request failed") from exc

        if result.run.provider != self._provider.provider_name:
            raise AIProviderFailure("AI provider provenance does not match configuration")
        if result.run.model != self._provider.model_name:
            raise AIProviderFailure("AI model provenance does not match configuration")

        allowed_references = {metric.source_reference for metric in request.metrics}
        if not set(result.source_references).issubset(allowed_references):
            raise AIProviderFailure("AI response cited an unknown report source")

        return result
