"""Tenant-scoped deterministic reporting and advisory AI narratives."""

from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.ai.context import AIExecutionContext
from veristock.ai.contracts import ReportNarrative
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
from veristock.inventory.models import InventoryItem, StockBalance
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
