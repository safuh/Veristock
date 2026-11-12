"""Tests for deterministic demand planning calculations."""

from decimal import Decimal

import pytest

from veristock.ai.forecasting import (
    calculate_demand_metrics,
    calculate_stockout_adjustment,
    evaluate_trailing_average,
)


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



def test_stockout_adjustment_uses_only_complete_sufficient_exposure() -> None:
    result = calculate_stockout_adjustment(
        units_sold=Decimal("60"),
        lookback_days=30,
        in_stock_days=Decimal("15"),
        availability_fraction=Decimal("0.5"),
        history_complete=True,
    )

    assert result.average_daily_demand == Decimal("4")
    assert result.adjustment_factor == Decimal("2")
    assert result.status == "adjusted"


def test_stockout_adjustment_caps_uplift_at_two_times_baseline() -> None:
    result = calculate_stockout_adjustment(
        units_sold=Decimal("60"),
        lookback_days=30,
        in_stock_days=Decimal("7"),
        availability_fraction=Decimal("0.233333"),
        history_complete=True,
        minimum_availability_fraction=Decimal("0.2"),
    )

    assert result.average_daily_demand == Decimal("4")
    assert result.adjustment_factor == Decimal("2")


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"in_stock_days": None, "availability_fraction": None}, "unavailable"),
        ({"history_complete": False}, "partial_history"),
        ({"in_stock_days": Decimal("0")}, "no_in_stock_exposure"),
        ({"units_sold": Decimal("0")}, "no_observed_sales"),
        ({"in_stock_days": Decimal("3")}, "insufficient_in_stock_history"),
        ({"availability_fraction": Decimal("0.25")}, "low_availability"),
    ],
)
def test_stockout_adjustment_refuses_weak_evidence(
    overrides: dict, expected_status: str
) -> None:
    values = {
        "units_sold": Decimal("60"),
        "lookback_days": 30,
        "in_stock_days": Decimal("20"),
        "availability_fraction": Decimal("0.666666"),
        "history_complete": True,
    }
    values.update(overrides)

    result = calculate_stockout_adjustment(**values)

    assert result.average_daily_demand is None
    assert result.adjustment_factor is None
    assert result.status == expected_status


def test_stockout_adjustment_returns_baseline_when_no_stockout_occurred() -> None:
    result = calculate_stockout_adjustment(
        units_sold=Decimal("60"),
        lookback_days=30,
        in_stock_days=Decimal("30"),
        availability_fraction=Decimal("1"),
        history_complete=True,
    )

    assert result.average_daily_demand == Decimal("2")
    assert result.adjustment_factor == Decimal("1")
    assert result.status == "no_stockout"


def test_trailing_average_backtest_uses_chronological_folds() -> None:
    result = evaluate_trailing_average(
        daily_sales=[Decimal("2")] * 14 + [Decimal("4")] * 4,
        lookback_days=7,
        horizon_days=2,
        max_folds=2,
    )
    assert result.fold_count == 2
    assert result.mean_absolute_error_per_day == Decimal("2")
    assert result.weighted_absolute_percentage_error == Decimal("0.5")
    assert result.forecast_bias_fraction == Decimal("-0.5")


def test_trailing_average_backtest_includes_zero_sale_days() -> None:
    result = evaluate_trailing_average(
        daily_sales=[Decimal("0")] * 7 + [Decimal("7")],
        lookback_days=7,
        horizon_days=1,
    )
    assert result.mean_absolute_error_per_day == Decimal("1")
    assert result.weighted_absolute_percentage_error == Decimal("1")
    assert result.forecast_bias_fraction == Decimal("-1")


def test_trailing_average_backtest_handles_zero_actuals() -> None:
    result = evaluate_trailing_average(
        daily_sales=[Decimal("0")] * 14,
        lookback_days=7,
        horizon_days=7,
    )
    assert result.mean_absolute_error_per_day == Decimal("0")
    assert result.weighted_absolute_percentage_error is None
    assert result.forecast_bias_fraction is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"lookback_days": 0}, "lookback_days"),
        ({"horizon_days": 0}, "horizon_days"),
        ({"max_folds": 0}, "max_folds"),
        ({"daily_sales": [Decimal("1"), Decimal("-1")]}, "negative"),
    ],
)
def test_trailing_average_backtest_rejects_invalid_inputs(
    overrides: dict, message: str
) -> None:
    values = {
        "daily_sales": [Decimal("1")] * 14,
        "lookback_days": 7,
        "horizon_days": 7,
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        evaluate_trailing_average(**values)


def test_trailing_average_backtest_requires_one_complete_fold() -> None:
    with pytest.raises(ValueError, match="insufficient_history"):
        evaluate_trailing_average(
            daily_sales=[Decimal("1")] * 10,
            lookback_days=7,
            horizon_days=4,
        )
