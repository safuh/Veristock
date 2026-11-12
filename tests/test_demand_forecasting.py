"""Tests for deterministic demand planning calculations."""

from decimal import Decimal

import pytest

from veristock.ai.forecasting import calculate_demand_metrics


def test_forecast_uses_full_lookback_window_and_target_coverage() -> None:
    result = calculate_demand_metrics(
        units_sold=Decimal("60"),
        quantity_on_hand=Decimal("10"),
        lookback_days=30,
        target_days=14,
    )

    assert result.units_sold == Decimal("60")
    assert result.average_daily_demand == Decimal("2")
    assert result.days_of_cover == Decimal("5")
    assert result.recommended_replenishment_quantity == Decimal("18")


def test_forecast_includes_lead_time_and_safety_stock() -> None:
    result = calculate_demand_metrics(
        units_sold=Decimal("60"),
        quantity_on_hand=Decimal("10"),
        lookback_days=30,
        target_days=14,
        lead_time_days=5,
        safety_stock_days=2,
    )

    assert result.reorder_point_quantity == Decimal("14")
    assert result.days_until_reorder == Decimal("0")
    assert result.recommended_replenishment_quantity == Decimal("32")


def test_forecast_does_not_recommend_replenishment_when_stock_is_sufficient() -> None:
    result = calculate_demand_metrics(
        units_sold=Decimal("30"),
        quantity_on_hand=Decimal("40"),
        lookback_days=30,
        target_days=14,
    )

    assert result.days_of_cover == Decimal("40")
    assert result.recommended_replenishment_quantity == Decimal("0")


def test_forecast_handles_items_without_sales_history() -> None:
    result = calculate_demand_metrics(
        units_sold=Decimal("0"),
        quantity_on_hand=Decimal("8"),
        lookback_days=30,
        target_days=14,
    )

    assert result.average_daily_demand == Decimal("0")
    assert result.days_of_cover is None
    assert result.recommended_replenishment_quantity == Decimal("0")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"lookback_days": 0}, "lookback_days"),
        ({"target_days": 0}, "target_days"),
        ({"lead_time_days": -1}, "lead_time_days"),
        ({"safety_stock_days": -1}, "safety_stock_days"),
        ({"units_sold": Decimal("-1")}, "units_sold"),
        ({"quantity_on_hand": Decimal("-1")}, "quantity_on_hand"),
    ],
)
def test_forecast_rejects_invalid_inputs(overrides: dict, message: str) -> None:
    values = {
        "units_sold": Decimal("10"),
        "quantity_on_hand": Decimal("5"),
        "lookback_days": 30,
        "target_days": 14,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        calculate_demand_metrics(**values)
