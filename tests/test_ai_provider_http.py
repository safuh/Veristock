"""Tests for the optional OpenAI-compatible AI provider adapter."""

import json

import pytest

from veristock.ai.provider_http import OpenAICompatibleProvider
from veristock.ai.requests import ReportMetric, ReportNarrativeRequest


def report_request() -> ReportNarrativeRequest:
    return ReportNarrativeRequest(
        period_start="2026-11-01",
        period_end="2026-11-07",
        metrics=(
            ReportMetric(
                key="inventory.zero_stock_items",
                label="Zero-stock items",
                value="4",
                unit="items",
                source_reference="inventory:zero-stock",
            ),
        ),
    )


def provider_response() -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "summary": "Four items have no stock.",
                            "observations": ["Review the zero-stock items."],
                            "recommended_actions": ["Review replenishment."],
                            "source_references": ["inventory:zero-stock"],
                        }
                    )
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_compatible_provider_parses_json_and_attaches_trusted_provenance() -> None:
    captured: dict[str, object] = {}

    class StubProvider(OpenAICompatibleProvider):
        def _post_json(self, payload: dict[str, object]) -> dict[str, object]:
            captured["payload"] = payload
            return provider_response()

    provider = StubProvider(
        base_url="https://llm.example.test/v1/",
        model="example-model",
        api_key="secret-test-key",
    )
    result = await provider.generate_report_narrative(report_request())

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "example-model"
    assert "inventory:zero-stock" in payload["messages"][1]["content"]
    assert result.run.provider == "openai-compatible"
    assert result.run.model == "example-model"
    assert result.source_references == ("inventory:zero-stock",)


@pytest.mark.asyncio
async def test_compatible_provider_rejects_invalid_provider_response() -> None:
    class InvalidProvider(OpenAICompatibleProvider):
        def _post_json(self, payload: dict[str, object]) -> dict[str, object]:
            return {"choices": []}

    provider = InvalidProvider(
        base_url="http://localhost:11434/v1",
        model="local-model",
    )
    with pytest.raises(RuntimeError, match="invalid response"):
        await provider.generate_report_narrative(report_request())


def test_compatible_provider_rejects_unsafe_base_urls() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        OpenAICompatibleProvider(
            base_url="https://user:password@example.test/v1",
            model="model",
        )
