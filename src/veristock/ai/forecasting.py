"""Deterministic, explainable demand planning calculations.

These calculations are advisory planning signals, not purchase orders or stock
ledger commands. The caller must provide tenant-authorized sales and balances.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DemandMetrics:
    """Demand, coverage and reorder metrics for one item in one scope."""

    units_sold: Decimal
    average_daily_demand: Decimal
    days_of_cover: Decimal | None
    reorder_point_quantity: Decimal
    days_until_reorder: Decimal | None
    recommended_replenishment_quantity: Decimal


def calculate_demand_metrics(
    *,
    units_sold: Decimal,
    quantity_on_hand: Decimal,
    lookback_days: int,
    target_days: int,
    lead_time_days: int = 0,
    safety_stock_days: int = 0,
) -> DemandMetrics:
    """Calculate a trailing-average forecast and lead-time-aware stock target.

    Reorder point is average daily demand multiplied by supplier lead time plus
    safety-stock days. Target stock adds the requested post-replenishment
    coverage horizon. Zero-sale days remain included in the trailing average.
    """
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if target_days <= 0:
        raise ValueError("target_days must be positive")
    if lead_time_days < 0:
        raise ValueError("lead_time_days cannot be negative")
    if safety_stock_days < 0:
        raise ValueError("safety_stock_days cannot be negative")
    if units_sold < 0:
        raise ValueError("units_sold cannot be negative")
    if quantity_on_hand < 0:
        raise ValueError("quantity_on_hand cannot be negative")

    average_daily = units_sold / Decimal(lookback_days)
    days_of_cover = (
        quantity_on_hand / average_daily if average_daily > 0 else None
    )
    reorder_horizon = Decimal(lead_time_days + safety_stock_days)
    reorder_point = average_daily * reorder_horizon
    target_stock = average_daily * Decimal(
        lead_time_days + safety_stock_days + target_days
    )
    days_until_reorder = (
        max(quantity_on_hand - reorder_point, Decimal("0")) / average_daily
        if average_daily > 0
        else None
    )
    replenishment = max(target_stock - quantity_on_hand, Decimal("0"))

    return DemandMetrics(
        units_sold=units_sold,
        average_daily_demand=average_daily,
        days_of_cover=days_of_cover,
        reorder_point_quantity=reorder_point,
        days_until_reorder=days_until_reorder,
        recommended_replenishment_quantity=replenishment,
    )



@dataclass(frozen=True, slots=True)
class StockoutDemandAdjustment:
    """Conservative stock-availability-adjusted demand evidence."""

    average_daily_demand: Decimal | None
    adjustment_factor: Decimal | None
    status: str


def calculate_stockout_adjustment(
    *,
    units_sold: Decimal,
    lookback_days: int,
    in_stock_days: Decimal | None,
    availability_fraction: Decimal | None,
    history_complete: bool,
    minimum_in_stock_days: Decimal = Decimal("7"),
    minimum_availability_fraction: Decimal = Decimal("0.5"),
    maximum_adjustment_factor: Decimal = Decimal("2"),
) -> StockoutDemandAdjustment:
    """Estimate sales velocity during available exposure without replacing baseline.

    The adjustment is deliberately unavailable unless the stock ledger covers
    the full lookback, availability is at least 50%, and at least seven
    in-stock days are observed. Uplift is capped at 2x the trailing baseline.
    The result is an evidence signal only; callers must not silently substitute
    it for the baseline replenishment forecast.
    """
    if units_sold < 0:
        raise ValueError("units_sold cannot be negative")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if minimum_in_stock_days <= 0:
        raise ValueError("minimum_in_stock_days must be positive")
    if not Decimal("0") < minimum_availability_fraction <= Decimal("1"):
        raise ValueError("minimum_availability_fraction must be between 0 and 1")
    if maximum_adjustment_factor < 1:
        raise ValueError("maximum_adjustment_factor must be at least 1")

    if in_stock_days is None or availability_fraction is None:
        return StockoutDemandAdjustment(None, None, "unavailable")
    if not history_complete:
        return StockoutDemandAdjustment(None, None, "partial_history")
    if in_stock_days <= 0:
        return StockoutDemandAdjustment(None, None, "no_in_stock_exposure")
    if units_sold == 0:
        return StockoutDemandAdjustment(None, None, "no_observed_sales")
    if in_stock_days < minimum_in_stock_days:
        return StockoutDemandAdjustment(None, None, "insufficient_in_stock_history")
    if availability_fraction < minimum_availability_fraction:
        return StockoutDemandAdjustment(None, None, "low_availability")

    baseline = units_sold / Decimal(lookback_days)
    factor = min(
        Decimal(lookback_days) / in_stock_days,
        maximum_adjustment_factor,
    )
    adjusted = min(baseline * factor, baseline * maximum_adjustment_factor)
    status = "adjusted" if factor > 1 else "no_stockout"
    return StockoutDemandAdjustment(adjusted, factor, status)
