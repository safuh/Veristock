"""Tests for the optional OpenAI-compatible AI provider adapter."""

import json

import httpx
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


@pytest.mark.asyncio
async def test_compatible_provider_parses_json_and_attaches_trusted_provenance() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
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
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://llm.example.test/v1/",
            model="example-model",
            api_key="secret-test-key",
            client=client,
        )
        result = await provider.generate_report_narrative(report_request())

    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret-test-key"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    user_content = payload["messages"][1]["content"]
    assert "inventory:zero-stock" in user_content
    assert result.run.provider == "openai-compatible"
    assert result.run.model == "example-model"
    assert result.source_references == ("inventory:zero-stock",)


@pytest.mark.asyncio
async def test_compatible_provider_rejects_invalid_provider_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="http://localhost:11434/v1",
            model="local-model",
            client=client,
        )
        with pytest.raises(RuntimeError, match="invalid response"):
            await provider.generate_report_narrative(report_request())


def test_compatible_provider_rejects_unsafe_base_urls() -> None:
    with pytest.raises(ValueError, match="HTTP"):
        OpenAICompatibleProvider(
            base_url="https://user:password@example.test/v1",
            model="model",
        )
