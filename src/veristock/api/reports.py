"""Tenant-scoped deterministic reporting and advisory AI narratives."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, and_, case, distinct, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from veristock.ai.context import AIExecutionContext
from veristock.ai.contracts import ReportNarrative
from veristock.ai.forecasting import calculate_demand_metrics
from veristock.ai.models import AIExecutionRecord
from veristock.ai.requests import ReportMetric, ReportNarrativeRequest
from veristock.ai.service import (
    AIProviderFailure,
    AIService,
    AIServiceUnavailable,
)
from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.inventory.availability import (
    StockAvailability,
    StockMovementEvent,
    calculate_stock_availability,
)
from veristock.inventory.models import (
    InventoryItem,
    Sale,
    SaleLine,
    StockBalance,
    StockMovement,
)
from veristock.inventory.policies import ReplenishmentPolicy
from veristock.organizations.models import Branch

router = APIRouter(prefix="/reports", tags=["reports"])
InventoryReporter = Annotated[
    Organization, Depends(require_permission("inventory.read"))
]


class InventoryReportMetric(BaseModel):
    """A deterministic report value suitable for display or later AI narration."""

    key: str
    label: str
    value: Decimal
    unit: str | None = None
    source_reference: str


class BranchInventoryReport(BaseModel):
    """Stock position for one active branch in the selected organization."""

    branch_id: str
    branch_code: str
    branch_name: str
    stocked_item_count: int
    total_units_on_hand: Decimal


class InventoryReportRead(BaseModel):
    """Tenant-scoped inventory snapshot with traceable source metrics."""

    model_config = ConfigDict(frozen=True)

    organization_id: str
    as_of: datetime
    active_item_count: int
    active_branch_count: int
    stocked_item_count: int
    zero_stock_item_count: int
    total_units_on_hand: Decimal
    branches: tuple[BranchInventoryReport, ...]
    metrics: tuple[InventoryReportMetric, ...]


class InventoryNarrativeRead(BaseModel):
    """Advisory AI narrative with its durable audit identifier."""

    audit_id: str
    report_as_of: datetime
    advisory_only: bool = True
    narrative: ReportNarrative


def get_ai_service(request: Request) -> AIService:
    """Resolve the application-configured provider-neutral AI service."""
    service = getattr(request.app.state, "ai_service", None)
    return service if service is not None else AIService()


@router.get("/inventory/summary", response_model=InventoryReportRead)
async def inventory_report(
    organization: InventoryReporter,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InventoryReportRead:
    """Return an auditable stock snapshot for the selected tenant only."""
    active_item_count = int(
        await session.scalar(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.organization_id == organization.id,
                InventoryItem.status == "active",
            )
        )
        or 0
    )
    active_branch_count = int(
        await session.scalar(
            select(func.count(Branch.id)).where(
                Branch.organization_id == organization.id,
                Branch.status == "active",
            )
        )
        or 0
    )

    stocked_item_count, total_units = (
        await session.execute(
            select(
                func.count(distinct(StockBalance.item_id)),
                func.coalesce(func.sum(StockBalance.quantity_on_hand), 0),
            )
            .join(
                InventoryItem,
                (InventoryItem.id == StockBalance.item_id)
                & (InventoryItem.organization_id == organization.id)
                & (InventoryItem.status == "active"),
            )
            .where(
                StockBalance.organization_id == organization.id,
                StockBalance.quantity_on_hand > 0,
            )
        )
    ).one()
    stocked_item_count = int(stocked_item_count or 0)
    total_units = Decimal(total_units or 0)

    active_stock_item = and_(
        InventoryItem.id.is_not(None),
        StockBalance.quantity_on_hand > 0,
    )
    branch_rows = (
        await session.execute(
            select(
                Branch.id,
                Branch.code,
                Branch.name,
                func.count(
                    distinct(
                        case(
                            (active_stock_item, StockBalance.item_id),
                            else_=None,
                        )
                    )
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                InventoryItem.id.is_not(None),
                                StockBalance.quantity_on_hand,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .outerjoin(
                StockBalance,
                (StockBalance.branch_id == Branch.id)
                & (StockBalance.organization_id == organization.id),
            )
            .outerjoin(
                InventoryItem,
                (InventoryItem.id == StockBalance.item_id)
                & (InventoryItem.organization_id == organization.id)
                & (InventoryItem.status == "active"),
            )
            .where(
                Branch.organization_id == organization.id,
                Branch.status == "active",
            )
            .group_by(Branch.id, Branch.code, Branch.name)
            .order_by(Branch.code)
        )
    ).all()

    branches = tuple(
        BranchInventoryReport(
            branch_id=branch_id,
            branch_code=branch_code,
            branch_name=branch_name,
            stocked_item_count=int(branch_stocked_count or 0),
            total_units_on_hand=Decimal(branch_total or 0),
        )
        for (
            branch_id,
            branch_code,
            branch_name,
            branch_stocked_count,
            branch_total,
        ) in branch_rows
    )
    zero_stock_item_count = max(active_item_count - stocked_item_count, 0)
    metrics = (
        InventoryReportMetric(
            key="inventory.active_items",
            label="Active catalogue items",
            value=Decimal(active_item_count),
            unit="items",
            source_reference="inventory:summary:active-items",
        ),
        InventoryReportMetric(
            key="inventory.active_branches",
            label="Active branches",
            value=Decimal(active_branch_count),
            unit="branches",
            source_reference="inventory:summary:active-branches",
        ),
        InventoryReportMetric(
            key="inventory.stocked_items",
            label="Items with stock",
            value=Decimal(stocked_item_count),
            unit="items",
            source_reference="inventory:summary:stocked-items",
        ),
        InventoryReportMetric(
            key="inventory.zero_stock_items",
            label="Active items with no stock in any branch",
            value=Decimal(zero_stock_item_count),
            unit="items",
            source_reference="inventory:summary:zero-stock-items",
        ),
        InventoryReportMetric(
            key="inventory.total_units",
            label="Total units on hand across branches",
            value=total_units,
            unit="base units",
            source_reference="inventory:summary:total-units",
        ),
    )
    return InventoryReportRead(
        organization_id=organization.id,
        as_of=datetime.now(UTC),
        active_item_count=active_item_count,
        active_branch_count=active_branch_count,
        stocked_item_count=stocked_item_count,
        zero_stock_item_count=zero_stock_item_count,
        total_units_on_hand=total_units,
        branches=branches,
        metrics=metrics,
    )


@router.post(
    "/inventory/narrative",
    response_model=InventoryNarrativeRead,
    status_code=status.HTTP_200_OK,
)
async def generate_inventory_narrative(
    request: Request,
    organization: InventoryReporter,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    ai_service: Annotated[AIService, Depends(get_ai_service)],
) -> InventoryNarrativeRead:
    """Generate an advisory narrative from this tenant's authorized snapshot."""
    report = await inventory_report(organization, session)
    narrative_request = ReportNarrativeRequest(
        period_start=report.as_of.date(),
        period_end=report.as_of.date(),
        metrics=tuple(
            ReportMetric(
                key=metric.key,
                label=metric.label,
                value=metric.value,
                unit=metric.unit,
                source_reference=metric.source_reference,
            )
            for metric in report.metrics
        ),
    )
    request_id = getattr(request.state, "request_id", None)
    context = AIExecutionContext(
        organization_id=organization.id,
        user_id=user.id,
        request_id=request_id,
    )
    started = perf_counter()

    try:
        narrative = await ai_service.generate_report_narrative(
            narrative_request,
            context,
        )
    except AIServiceUnavailable as exc:
        record = AIExecutionRecord(
            id=str(uuid4()),
            organization_id=organization.id,
            user_id=user.id,
            status="unavailable",
            provider=ai_service.provider_name,
            model=ai_service.model_name,
            latency_ms=int((perf_counter() - started) * 1000),
            request_id=request_id,
            source_references=[
                metric.source_reference for metric in narrative_request.metrics
            ],
            failure_code="provider_not_configured",
        )
        session.add(record)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI narrative generation is not configured",
        ) from exc
    except AIProviderFailure as exc:
        record = AIExecutionRecord(
            id=str(uuid4()),
            organization_id=organization.id,
            user_id=user.id,
            status="failed",
            provider=ai_service.provider_name,
            model=ai_service.model_name,
            latency_ms=int((perf_counter() - started) * 1000),
            request_id=request_id,
            source_references=[
                metric.source_reference for metric in narrative_request.metrics
            ],
            failure_code="provider_failure",
        )
        session.add(record)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI provider could not complete the narrative request",
        ) from exc

    record = AIExecutionRecord(
        id=str(uuid4()),
        organization_id=organization.id,
        user_id=user.id,
        status="succeeded",
        provider=narrative.run.provider,
        model=narrative.run.model,
        model_version=narrative.run.model_version,
        latency_ms=int((perf_counter() - started) * 1000),
        request_id=request_id,
        source_references=list(narrative.source_references),
    )
    session.add(record)
    await session.commit()
    return InventoryNarrativeRead(
        audit_id=record.id,
        report_as_of=report.as_of,
        narrative=narrative,
    )

class AIProviderStatusRead(BaseModel):
    """Safe configuration status; never includes endpoint or credential data."""

    configured: bool
    provider: str | None = None
    model: str | None = None


@router.get("/ai-provider/status", response_model=AIProviderStatusRead)
async def ai_provider_status(
    organization: InventoryReporter,
    ai_service: Annotated[AIService, Depends(get_ai_service)],
) -> AIProviderStatusRead:
    """Report whether AI execution is configured for this authorized tenant.

    This is a configuration check, not a remote provider health probe. It does
    not make an external request and never returns the provider URL or API key.
    """
    if not ai_service.is_configured:
        return AIProviderStatusRead(configured=False)
    return AIProviderStatusRead(
        configured=True,
        provider=ai_service.provider_name,
        model=ai_service.model_name,
    )


class DemandForecastItemRead(BaseModel):
    """Explainable demand and stock coverage estimate for one catalogue item."""

    item_id: str
    sku: str | None
    item_name: str
    unit_code: str
    units_sold_in_window: Decimal
    sales_activity_days: int
    sales_activity_fraction: Decimal
    average_daily_demand: Decimal
    quantity_on_hand: Decimal
    days_of_cover: Decimal | None
    reorder_point_quantity: Decimal
    days_until_reorder: Decimal | None
    recommended_replenishment_quantity: Decimal
    lead_time_days: int
    safety_stock_days: int
    planning_policy_source: str
    sales_source_reference: str
    stock_source_reference: str
    stock_availability_fraction: Decimal | None
    stock_availability_coverage_fraction: Decimal | None
    stock_availability_status: str
    stock_availability_source_reference: str | None


class DemandForecastRead(BaseModel):
    """Tenant-scoped deterministic replenishment planning snapshot."""

    generated_at: datetime
    branch_id: str | None
    lookback_days: int
    target_days: int
    lead_time_days: int | None
    safety_stock_days: int | None
    methodology: str
    items: tuple[DemandForecastItemRead, ...]


@router.get("/inventory/demand-forecast", response_model=DemandForecastRead)
async def inventory_demand_forecast(
    organization: InventoryReporter,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    branch_id: str | None = None,
    lookback_days: int = Query(default=30, ge=7, le=365),
    target_days: int = Query(default=14, ge=1, le=180),
    lead_time_days: int | None = Query(default=None, ge=0, le=180),
    safety_stock_days: int | None = Query(default=None, ge=0, le=180),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> DemandForecastRead:
    """Return explainable sales-velocity forecasts for the selected tenant.

    A branch forecast uses saved branch/item policies unless a request-level
    override is supplied. All-branch forecasts do not merge branch policies:
    explicit shared overrides are accepted, otherwise zero-day defaults apply.
    This endpoint never creates or posts replenishment transactions.
    """
    if branch_id is not None:
        branch = await session.scalar(
            select(Branch.id).where(
                Branch.id == branch_id,
                Branch.organization_id == organization.id,
                Branch.status == "active",
            )
        )
        if branch is None:
            raise HTTPException(status_code=404, detail="Active branch not found")

    generated_at = datetime.now(UTC)
    window_start = generated_at - timedelta(days=lookback_days)

    sales_statement = (
        select(
            SaleLine.item_id.label("item_id"),
            func.coalesce(func.sum(SaleLine.quantity), 0).label("units_sold"),
            func.count(distinct(func.date(Sale.posted_at))).label("sales_activity_days"),
        )
        .join(
            Sale,
            (Sale.id == SaleLine.sale_id)
            & (Sale.organization_id == organization.id)
            & (Sale.status == "posted"),
        )
        .where(
            SaleLine.organization_id == organization.id,
            Sale.posted_at >= window_start,
        )
        .group_by(SaleLine.item_id)
    )
    stock_statement = (
        select(
            StockBalance.item_id.label("item_id"),
            func.coalesce(func.sum(StockBalance.quantity_on_hand), 0).label(
                "quantity_on_hand"
            ),
        )
        .where(StockBalance.organization_id == organization.id)
        .group_by(StockBalance.item_id)
    )
    if branch_id is not None:
        sales_statement = sales_statement.where(Sale.branch_id == branch_id)
        stock_statement = stock_statement.where(StockBalance.branch_id == branch_id)

    sales_totals = sales_statement.subquery()
    stock_totals = stock_statement.subquery()
    units_sold_expression = func.coalesce(sales_totals.c.units_sold, 0)
    stock_expression = func.coalesce(stock_totals.c.quantity_on_hand, 0)

    saved_lead_expression: ColumnElement[int]
    saved_safety_expression: ColumnElement[int]
    if branch_id is not None:
        policy_join = and_(
            ReplenishmentPolicy.organization_id == organization.id,
            ReplenishmentPolicy.branch_id == branch_id,
            ReplenishmentPolicy.item_id == InventoryItem.id,
        )
        saved_lead_expression = cast(ColumnElement[int], ReplenishmentPolicy.lead_time_days)
        saved_safety_expression = cast(ColumnElement[int], ReplenishmentPolicy.safety_stock_days)
        lead_expression = (
            literal(lead_time_days)
            if lead_time_days is not None
            else func.coalesce(saved_lead_expression, 0)
        )
        safety_expression = (
            literal(safety_stock_days)
            if safety_stock_days is not None
            else func.coalesce(saved_safety_expression, 0)
        )
    else:
        saved_lead_expression = literal(None, type_=Integer)
        saved_safety_expression = literal(None, type_=Integer)
        lead_expression = literal(lead_time_days or 0)
        safety_expression = literal(safety_stock_days or 0)

    target_stock_expression = (
        units_sold_expression
        * (target_days + lead_expression + safety_expression)
        / lookback_days
    )
    replenishment_priority = case(
        (
            target_stock_expression > stock_expression,
            target_stock_expression - stock_expression,
        ),
        else_=0,
    )

    statement = (
        select(
            InventoryItem,
            units_sold_expression,
            sales_totals.c.sales_activity_days,
            stock_expression,
            lead_expression.label("lead_time_days"),
            safety_expression.label("safety_stock_days"),
            saved_lead_expression.label("saved_lead_time_days"),
            saved_safety_expression.label("saved_safety_stock_days"),
        )
        .outerjoin(sales_totals, sales_totals.c.item_id == InventoryItem.id)
        .outerjoin(stock_totals, stock_totals.c.item_id == InventoryItem.id)
        .where(
            InventoryItem.organization_id == organization.id,
            InventoryItem.status == "active",
        )
    )
    if branch_id is not None:
        statement = statement.outerjoin(ReplenishmentPolicy, policy_join)

    rows = (
        await session.execute(
            statement.order_by(
                replenishment_priority.desc(),
                units_sold_expression.desc(),
                InventoryItem.name.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()

    availability_by_item: dict[str, StockAvailability | None] = {}
    if branch_id is not None and rows:
        movement_rows = (
            await session.execute(
                select(
                    StockMovement.item_id,
                    StockMovement.quantity_delta,
                    StockMovement.source_type,
                    StockMovement.occurred_at,
                )
                .where(
                    StockMovement.organization_id == organization.id,
                    StockMovement.branch_id == branch_id,
                    StockMovement.item_id.in_([row[0].id for row in rows]),
                    StockMovement.occurred_at <= generated_at,
                )
                .order_by(StockMovement.item_id, StockMovement.occurred_at)
            )
        ).all()
        events_by_item: dict[str, list[StockMovementEvent]] = {}
        for item_id, quantity_delta, source_type, occurred_at in movement_rows:
            events_by_item.setdefault(item_id, []).append(
                StockMovementEvent(
                    occurred_at=occurred_at,
                    quantity_delta=Decimal(quantity_delta),
                    source_type=source_type,
                )
            )
        for item in (row[0] for row in rows):
            availability_by_item[item.id] = calculate_stock_availability(
                movements=events_by_item.get(item.id, []),
                window_start=window_start,
                window_end=generated_at,
            )

    forecasts: list[DemandForecastItemRead] = []
    for (
        item,
        raw_units_sold,
        raw_sales_activity_days,
        raw_on_hand,
        raw_lead_time,
        raw_safety_stock,
        saved_lead_time,
        saved_safety_stock,
    ) in rows:
        units_sold = Decimal(raw_units_sold or 0)
        on_hand = Decimal(raw_on_hand or 0)
        item_lead_time = int(raw_lead_time or 0)
        item_safety_stock = int(raw_safety_stock or 0)
        policy_source = (
            "request_override"
            if lead_time_days is not None or safety_stock_days is not None
            else "saved_policy"
            if branch_id is not None
            and (saved_lead_time is not None or saved_safety_stock is not None)
            else "default"
        )
        availability = availability_by_item.get(item.id)
        metrics = calculate_demand_metrics(
            units_sold=units_sold,
            quantity_on_hand=on_hand,
            lookback_days=lookback_days,
            target_days=target_days,
            lead_time_days=item_lead_time,
            safety_stock_days=item_safety_stock,
        )
        forecasts.append(
            DemandForecastItemRead(
                item_id=item.id,
                sku=item.sku,
                item_name=item.name,
                unit_code=item.base_unit_code,
                units_sold_in_window=metrics.units_sold,
                sales_activity_days=int(raw_sales_activity_days or 0),
                sales_activity_fraction=(
                    Decimal(raw_sales_activity_days or 0) / Decimal(lookback_days)
                ),
                average_daily_demand=metrics.average_daily_demand,
                quantity_on_hand=on_hand,
                days_of_cover=metrics.days_of_cover,
                reorder_point_quantity=metrics.reorder_point_quantity,
                days_until_reorder=metrics.days_until_reorder,
                recommended_replenishment_quantity=(
                    metrics.recommended_replenishment_quantity
                ),
                lead_time_days=item_lead_time,
                safety_stock_days=item_safety_stock,
                planning_policy_source=policy_source,
                sales_source_reference=f"sales:posted:{item.id}:{lookback_days}d",
                stock_source_reference=(
                    f"stock:balance:{item.id}:{branch_id or 'all-branches'}"
                ),
                stock_availability_fraction=(
                    availability.availability_fraction
                    if availability is not None
                    else None
                ),
                stock_availability_coverage_fraction=(
                    availability.coverage_fraction
                    if availability is not None
                    else None
                ),
                stock_availability_status=(
                    "branch_required"
                    if branch_id is None
                    else "unavailable"
                    if availability is None
                    else "complete"
                    if availability.history_complete
                    else "partial"
                ),
                stock_availability_source_reference=(
                    f"stock-movements:{item.id}:{branch_id}"
                    if branch_id is not None
                    else None
                ),
            )
        )

    return DemandForecastRead(
        generated_at=generated_at,
        branch_id=branch_id,
        lookback_days=lookback_days,
        target_days=target_days,
        lead_time_days=(
            lead_time_days
            if lead_time_days is not None
            else 0 if branch_id is None else None
        ),
        safety_stock_days=(
            safety_stock_days
            if safety_stock_days is not None
            else 0 if branch_id is None else None
        ),
        methodology=(
            "Average daily demand equals posted units sold divided by every "
            "calendar day in the lookback window. Sales activity days count "
            "distinct dates with at least one posted sale; they do not measure "
            "product availability or days with zero demand. Reorder point equals average "
            "daily demand multiplied by supplier lead-time days plus safety-stock "
            "days. Suggested replenishment raises stock to cover lead time, "
            "safety stock and the requested post-replenishment target horizon. "
            "Branch forecasts use saved branch/item policies unless explicitly "
            "overridden. All-branch forecasts use shared request overrides or "
            "zero-day defaults because branch policies may differ. Branch-scoped "
            "availability exposure is reconstructed from opening-balance-anchored "
            "stock movements; incomplete history is marked unavailable or partial. "
            "This evidence is not yet used to adjust demand. Seasonality, "
            "stockout-censored demand and supplier constraints are not inferred."
        ),
        items=tuple(forecasts),
    )
