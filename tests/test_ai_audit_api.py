"""Tests for tenant-scoped AI execution history."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from veristock.api.ai_audit import list_ai_executions


class FakeScalarResult:
    def __init__(self, records):
        self._records = records

    def all(self):
        return self._records


class FakeSession:
    def __init__(self, records):
        self.records = records
        self.statement = None

    async def scalars(self, statement):
        self.statement = statement
        return FakeScalarResult(self.records)


@pytest.mark.asyncio
async def test_ai_execution_history_is_filtered_to_active_tenant():
    record = SimpleNamespace(
        id="audit-1",
        organization_id="tenant-a",
        user_id="user-a",
        operation="report_narrative",
        status="succeeded",
        provider="test-provider",
        model="test-model",
        model_version=None,
        latency_ms=12,
        request_id="request-1",
        source_references=["inventory:summary:total-units"],
        failure_code=None,
        created_at=datetime.now(UTC),
    )
    session = FakeSession([record])

    results = await list_ai_executions(
        organization=SimpleNamespace(id="tenant-a"),
        session=session,
        limit=25,
        offset=0,
    )

    compiled = str(
        session.statement.compile(compile_kwargs={"literal_binds": True})
    )
    assert "ai_execution_records.organization_id = 'tenant-a'" in compiled
    assert len(results) == 1
    assert results[0].id == "audit-1"
    assert results[0].status == "succeeded"
    assert results[0].source_references == [
        "inventory:summary:total-units"
    ]
    assert not hasattr(results[0], "user_id")
    assert not hasattr(results[0], "organization_id")
