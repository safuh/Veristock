"""Trusted actor context for AI operations."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AIExecutionContext:
    """Identity context retained by Veristock, never forwarded to model providers."""

    organization_id: str
    user_id: str
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.organization_id.strip():
            raise ValueError("organization_id is required")
        if not self.user_id.strip():
            raise ValueError("user_id is required")
