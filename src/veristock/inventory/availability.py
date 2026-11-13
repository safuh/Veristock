"""Historical stock-availability evidence reconstructed from the append-only ledger.

The reconstruction is deliberately conservative: an item/branch history is
usable only when its first recorded movement is an opening balance. Current
stock balances are never used to backfill missing history.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class StockMovementEvent:
    """Minimal immutable movement data required for availability reconstruction."""

    occurred_at: datetime
    quantity_delta: Decimal
    source_type: str


@dataclass(frozen=True, slots=True)
class StockAvailability:
    """Observed stock exposure within a requested time window."""

    observed_days: Decimal
    in_stock_days: Decimal
    out_of_stock_days: Decimal
    availability_fraction: Decimal
    coverage_fraction: Decimal
    history_complete: bool


def calculate_stock_availability(
    *,
    movements: list[StockMovementEvent],
    window_start: datetime,
    window_end: datetime,
) -> StockAvailability | None:
    """Reconstruct time spent in and out of stock from a complete ledger anchor.

    Returns None when the ledger cannot establish a trustworthy opening
    quantity. A history beginning after the requested window is not treated as
    evidence for the earlier period. Movement deltas at identical timestamps
    are applied together, avoiding arbitrary ordering of simultaneous events.
    """
    if window_start.tzinfo is None or window_start.utcoffset() is None:
        raise ValueError("window_start must be timezone-aware")
    if window_end.tzinfo is None or window_end.utcoffset() is None:
        raise ValueError("window_end must be timezone-aware")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    if not movements:
        return None

    if any(
        movement.occurred_at.tzinfo is None
        or movement.occurred_at.utcoffset() is None
        for movement in movements
    ):
        raise ValueError("movement timestamps must be timezone-aware")
    ordered = sorted(
        movements,
        key=lambda movement: movement.occurred_at.astimezone(UTC),
    )

    first_at = ordered[0].occurred_at.astimezone(UTC)
    first_group = [
        movement
        for movement in ordered
        if movement.occurred_at.astimezone(UTC) == first_at
    ]
    if len(first_group) != 1 or first_group[0].source_type != "opening_balance":
        return None

    start = window_start.astimezone(UTC)
    end = window_end.astimezone(UTC)
    if first_at >= end:
        return None

    quantity = first_group[0].quantity_delta
    if quantity < 0:
        return None

    observed_start = max(start, first_at)
    observed_seconds = Decimal(str((end - observed_start).total_seconds()))
    if observed_seconds <= 0:
        return None

    in_stock_seconds = Decimal("0")
    out_of_stock_seconds = Decimal("0")
    cursor = first_at
    index = 1

    while index < len(ordered):
        event_at = ordered[index].occurred_at.astimezone(UTC)
        if event_at > end:
            break

        interval_start = max(cursor, observed_start)
        interval_end = min(event_at, end)
        if interval_end > interval_start:
            seconds = Decimal(str((interval_end - interval_start).total_seconds()))
            if quantity > 0:
                in_stock_seconds += seconds
            elif quantity == 0:
                out_of_stock_seconds += seconds
            else:
                return None

        delta = Decimal("0")
        while index < len(ordered):
            current = ordered[index]
            current_at = current.occurred_at.astimezone(UTC)
            if current_at != event_at:
                break
            delta += current.quantity_delta
            index += 1
        quantity += delta
        if quantity < 0:
            return None
        cursor = event_at

    interval_start = max(cursor, observed_start)
    if end > interval_start:
        seconds = Decimal(str((end - interval_start).total_seconds()))
        if quantity > 0:
            in_stock_seconds += seconds
        elif quantity == 0:
            out_of_stock_seconds += seconds
        else:
            return None

    seconds_per_day = Decimal("86400")
    observed_days = observed_seconds / seconds_per_day
    in_stock_days = in_stock_seconds / seconds_per_day
    out_of_stock_days = out_of_stock_seconds / seconds_per_day
    return StockAvailability(
        observed_days=observed_days,
        in_stock_days=in_stock_days,
        out_of_stock_days=out_of_stock_days,
        availability_fraction=in_stock_seconds / observed_seconds,
        coverage_fraction=observed_seconds
        / Decimal(str((end - start).total_seconds())),
        history_complete=observed_start == start,
    )
