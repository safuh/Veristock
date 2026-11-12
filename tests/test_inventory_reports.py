"""Tests for deterministic tenant inventory reports."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from veristock.api.reports import inventory_report


class FakeResult:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def one(self):
        return self._row

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self):
        self.scalar_values = iter((3, 2))
        self.execute_results = iter(
            (
                FakeResult(row=(2, Decimal("14.5000"))),
                FakeResult(
                    rows=[
                        ("branch-1", "MAIN", "Main branch", 2, Decimal("14.5000")),
                        ("branch-2", "WEST", "West branch", 0, Decimal("0")),
                    ]
                ),
            )
        )

    async def scalar(self, statement):
        return next(self.scalar_values)

    async def execute(self, statement):
        return next(self.execute_results)


@pytest.mark.asyncio
async def test_inventory_report_returns_deterministic_tenant_snapshot():
    report = await inventory_report(
        organization=SimpleNamespace(id="org-1"),
        session=FakeSession(),
    )

    assert report.organization_id == "org-1"
    assert report.active_item_count == 3
    assert report.active_branch_count == 2
    assert report.stocked_item_count == 2
    assert report.zero_stock_item_count == 1
    assert report.total_units_on_hand == Decimal("14.5000")
    assert len(report.branches) == 2
    assert report.branches[0].branch_id == "branch-1"
    assert report.metrics[-1].source_reference == "inventory:summary:total-units"
