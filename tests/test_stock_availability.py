"""Tests for conservative stock availability reconstruction."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from veristock.inventory.availability import (
    StockMovementEvent,
    calculate_stock_availability,
)


def event(day: int, delta: str, source: str = "manual_adjustment") -> StockMovementEvent:
    return StockMovementEvent(
        occurred_at=datetime(2026, 1, day, tzinfo=UTC),
        quantity_delta=Decimal(delta),
        source_type=source,
    )


def test_reconstructs_in_stock_and_stockout_exposure() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=4)
    result = calculate_stock_availability(
        movements=[
            event(1, "10", "opening_balance"),
            event(2, "-10", "sale"),
            event(4, "5", "manual_adjustment"),
        ],
        window_start=start,
        window_end=end,
    )

    assert result is not None
    assert result.observed_days == Decimal("4")
    assert result.in_stock_days == Decimal("2")
    assert result.out_of_stock_days == Decimal("2")
    assert result.availability_fraction == Decimal("0.5")
    assert result.coverage_fraction == Decimal("1")
    assert result.history_complete is True


def test_marks_history_partial_when_opening_balance_is_inside_window() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=4)
    result = calculate_stock_availability(
        movements=[event(3, "8", "opening_balance")],
        window_start=start,
        window_end=end,
    )

    assert result is not None
    assert result.observed_days == Decimal("2")
    assert result.in_stock_days == Decimal("2")
    assert result.coverage_fraction == Decimal("0.5")
    assert result.history_complete is False


def test_refuses_history_without_an_opening_balance_anchor() -> None:
    result = calculate_stock_availability(
        movements=[event(1, "-2", "sale"), event(2, "5")],
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 3, tzinfo=UTC),
    )

    assert result is None


def test_refuses_ambiguous_simultaneous_opening_movements() -> None:
    result = calculate_stock_availability(
        movements=[
            event(1, "10", "opening_balance"),
            event(1, "-2", "sale"),
        ],
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 3, tzinfo=UTC),
    )

    assert result is None


def test_rejects_naive_or_reversed_window() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        calculate_stock_availability(
            movements=[event(1, "5", "opening_balance")],
            window_start=datetime(2026, 1, 1),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="after"):
        calculate_stock_availability(
            movements=[event(1, "5", "opening_balance")],
            window_start=datetime(2026, 1, 2, tzinfo=UTC),
            window_end=datetime(2026, 1, 1, tzinfo=UTC),
        )
