"""Deterministic, explainable demand planning calculations.

These calculations are advisory planning signals, not purchase orders or stock
ledger commands. The caller must provide tenant-authorized sales and balances.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class DemandMetrics:
    """Demand and coverage metrics for one item in one reporting scope."""

    units_sold: Decimal
    average_daily_demand: Decimal
    days_of_cover: Decimal | None
    recommended_replenishment_quantity: Decimal


def calculate_demand_metrics(
    *,
    units_sold: Decimal,
    quantity_on_hand: Decimal,
    lookback_days: int,
    target_days: int,
) -> DemandMetrics:
    """Calculate a trailing-average forecast and target-stock gap.

    The average includes zero-sale days because it divides by the full lookback
    window. The replenishment suggestion is the non-negative gap between
    current stock and average demand over the target coverage horizon.
    """
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    if target_days <= 0:
        raise ValueError("target_days must be positive")
    if units_sold < 0:
        raise ValueError("units_sold cannot be negative")
    if quantity_on_hand < 0:
        raise ValueError("quantity_on_hand cannot be negative")

    average_daily = units_sold / Decimal(lookback_days)
    days_of_cover = (
        quantity_on_hand / average_daily if average_daily > 0 else None
    )
    target_stock = average_daily * Decimal(target_days)
    replenishment = max(target_stock - quantity_on_hand, Decimal("0"))

    return DemandMetrics(
        units_sold=units_sold,
        average_daily_demand=average_daily,
        days_of_cover=days_of_cover,
        recommended_replenishment_quantity=replenishment,
    )
