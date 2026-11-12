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
