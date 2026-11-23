"""Purchase requisition submission and segregated approval workflow."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from veristock.api.branch_access import require_branch_assignment
from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_current_user,
    get_db_session,
    require_permission,
)
from veristock.identity.models import User
from veristock.inventory.models import InventoryItem, Supplier
from veristock.inventory.procurement import (
    ProcurementApprovalRule,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    PurchaseRequisitionDecision,
    PurchaseRequisitionLine,
)

router = APIRouter(prefix="/procurement/requisitions", tags=["procurement"])
Manager = Annotated[Organization, Depends(require_permission("inventory.manage"))]
Reader = Annotated[Organization, Depends(require_permission("inventory.read"))]


class RequisitionLineInput(BaseModel):
    item_id: str
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    estimated_unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)


class RequisitionInput(BaseModel):
    reference: str = Field(min_length=2, max_length=80)
    branch_id: str
    justification: str = Field(min_length=5, max_length=1000)
    currency: str = Field(default="KES", pattern=r"^[A-Z]{3}$")
    idempotency_key: str = Field(min_length=8, max_length=128)
    lines: list[RequisitionLineInput] = Field(min_length=1, max_length=200)


class DecisionInput(BaseModel):
    reason: str | None = Field(default=None, min_length=3, max_length=1000)


def _read(record: PurchaseRequisition) -> dict[str, object]:
    return {
        "id": record.id,
        "reference": record.reference,
        "branch_id": record.branch_id,
        "status": record.status,
        "justification": record.justification,
        "currency": record.currency,
        "required_approvals": record.required_approvals,
        "approvals_received": sum(decision.decision == "approved" for decision in record.decisions),
        "requested_by_user_id": record.requested_by_user_id,
        "created_at": record.created_at,
        "submitted_at": record.submitted_at,
        "converted_purchase_order_id": record.converted_purchase_order_id,
        "lines": [
            {
                "id": line.id,
                "item_id": line.item_id,
                "quantity": line.quantity,
                "unit_code": line.unit_code,
                "estimated_unit_cost": line.estimated_unit_cost,
            }
            for line in record.lines
        ],
        "decisions": [
            {
                "id": decision.id,
                "decision": decision.decision,
                "actor_user_id": decision.actor_user_id,
                "reason": decision.reason,
                "created_at": decision.created_at,
            }
            for decision in record.decisions
        ],
    }


async def _load(
    session: AsyncSession, organization_id: str, requisition_id: str, *, lock: bool = False
) -> PurchaseRequisition:
    query = (
        select(PurchaseRequisition)
        .where(
            PurchaseRequisition.id == requisition_id,
            PurchaseRequisition.organization_id == organization_id,
        )
        .options(
            selectinload(PurchaseRequisition.lines),
            selectinload(PurchaseRequisition.decisions),
        )
    )
    if lock:
        query = query.with_for_update()
    record = await session.scalar(query)
    if record is None:
        raise HTTPException(status_code=404, detail="Purchase requisition not found")
    return record


@router.post("", status_code=201)
async def create_requisition(
    payload: RequisitionInput,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    await require_branch_assignment(session, user, organization, payload.branch_id)
    prior = await session.scalar(
        select(PurchaseRequisition)
        .where(
            PurchaseRequisition.organization_id == organization.id,
            PurchaseRequisition.idempotency_key == payload.idempotency_key,
        )
        .options(
            selectinload(PurchaseRequisition.lines), selectinload(PurchaseRequisition.decisions)
        )
    )
    normalized = sorted((x.item_id, x.quantity, x.estimated_unit_cost) for x in payload.lines)
    if prior:
        existing = sorted((x.item_id, x.quantity, x.estimated_unit_cost) for x in prior.lines)
        if (
            prior.reference != payload.reference.strip()
            or prior.branch_id != payload.branch_id
            or prior.justification != payload.justification.strip()
            or prior.currency != payload.currency
            or prior.requested_by_user_id != user.id
            or existing != normalized
        ):
            raise HTTPException(
                status_code=409, detail="Idempotency key belongs to another requisition"
            )
        return _read(prior)

    record = PurchaseRequisition(
        id=str(uuid4()),
        organization_id=organization.id,
        branch_id=payload.branch_id,
        reference=payload.reference.strip(),
        status="draft",
        justification=payload.justification.strip(),
        idempotency_key=payload.idempotency_key,
        requested_by_user_id=user.id,
    )
    seen: set[str] = set()
    for line in payload.lines:
        if line.item_id in seen:
            raise HTTPException(status_code=422, detail="Duplicate item in requisition")
        seen.add(line.item_id)
        item = await session.scalar(
            select(InventoryItem).where(
                InventoryItem.id == line.item_id,
                InventoryItem.organization_id == organization.id,
                InventoryItem.status == "active",
            )
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Active inventory item not found")
        record.lines.append(
            PurchaseRequisitionLine(
                id=str(uuid4()),
                organization_id=organization.id,
                item_id=item.id,
                quantity=line.quantity,
                unit_code=item.base_unit_code,
                estimated_unit_cost=line.estimated_unit_cost,
            )
        )
    session.add(record)
    await session.commit()
    await session.refresh(record, attribute_names=["lines", "decisions"])
    return _read(record)


@router.get("")
async def list_requisitions(
    organization: Reader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str | None = None,
) -> list[dict[str, object]]:
    query = (
        select(PurchaseRequisition)
        .where(PurchaseRequisition.organization_id == organization.id)
        .options(
            selectinload(PurchaseRequisition.lines), selectinload(PurchaseRequisition.decisions)
        )
        .order_by(PurchaseRequisition.created_at.desc())
    )
    if status:
        if status not in {"draft", "submitted", "approved", "rejected", "converted", "cancelled"}:
            raise HTTPException(status_code=422, detail="Invalid requisition status")
        query = query.where(PurchaseRequisition.status == status)
    return [_read(x) for x in (await session.scalars(query)).all()]


@router.post("/{requisition_id}/submit")
async def submit_requisition(
    requisition_id: str,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    record = await _load(session, organization.id, requisition_id, lock=True)
    await require_branch_assignment(session, user, organization, record.branch_id)
    if record.requested_by_user_id != user.id:
        raise HTTPException(
            status_code=403, detail="Only the requester can submit this requisition"
        )
    if record.status == "submitted":
        return _read(record)
    if record.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft requisitions can be submitted")
    rules_exist = await session.scalar(
        select(ProcurementApprovalRule.id)
        .where(
            ProcurementApprovalRule.organization_id == organization.id,
            ProcurementApprovalRule.currency == record.currency,
        )
        .limit(1)
    )
    if rules_exist and any(line.estimated_unit_cost is None for line in record.lines):
        raise HTTPException(
            status_code=422,
            detail=(
                "Estimated unit costs are required when value-based approval rules are configured"
            ),
        )
    total = sum(
        (line.quantity * (line.estimated_unit_cost or Decimal("0")) for line in record.lines),
        Decimal("0"),
    )
    rule = await session.scalar(
        select(ProcurementApprovalRule)
        .where(
            ProcurementApprovalRule.organization_id == organization.id,
            ProcurementApprovalRule.currency == record.currency,
            ProcurementApprovalRule.minimum_total <= total,
        )
        .order_by(ProcurementApprovalRule.minimum_total.desc())
    )
    record.required_approvals = rule.required_approvals if rule else 1
    record.status = "submitted"
    record.submitted_at = datetime.now(UTC)
    record.decisions.append(
        PurchaseRequisitionDecision(
            id=str(uuid4()),
            organization_id=organization.id,
            decision="submitted",
            actor_user_id=user.id,
            reason=None,
        )
    )
    await session.commit()
    await session.refresh(record, attribute_names=["lines", "decisions"])
    return _read(record)


async def _decide(
    requisition_id: str,
    payload: DecisionInput,
    decision: str,
    organization: Organization,
    user: User,
    session: AsyncSession,
) -> dict[str, object]:
    record = await _load(session, organization.id, requisition_id, lock=True)
    await require_branch_assignment(session, user, organization, record.branch_id)
    if record.requested_by_user_id == user.id:
        raise HTTPException(
            status_code=403, detail="Requester and approver must be different users"
        )
    if record.status != "submitted":
        raise HTTPException(status_code=409, detail="Only submitted requisitions can be decided")
    if decision == "rejected" and not payload.reason:
        raise HTTPException(status_code=422, detail="A rejection reason is required")
    if decision == "approved":
        prior_approval = await session.scalar(
            select(PurchaseRequisitionDecision).where(
                PurchaseRequisitionDecision.requisition_id == record.id,
                PurchaseRequisitionDecision.actor_user_id == user.id,
                PurchaseRequisitionDecision.decision == "approved",
            )
        )
        if prior_approval:
            raise HTTPException(
                status_code=409, detail="This user has already approved the requisition"
            )
        approvals_so_far = (
            await session.scalar(
                select(func.count())
                .select_from(PurchaseRequisitionDecision)
                .where(
                    PurchaseRequisitionDecision.requisition_id == record.id,
                    PurchaseRequisitionDecision.decision == "approved",
                )
            )
            or 0
        )
        record.status = (
            "approved" if approvals_so_far + 1 >= record.required_approvals else "submitted"
        )
    else:
        record.status = "rejected"
    record.decisions.append(
        PurchaseRequisitionDecision(
            id=str(uuid4()),
            organization_id=organization.id,
            decision=decision,
            actor_user_id=user.id,
            reason=payload.reason,
        )
    )
    await session.commit()
    await session.refresh(record, attribute_names=["lines", "decisions"])
    return _read(record)


@router.post("/{requisition_id}/approve")
async def approve_requisition(
    requisition_id: str,
    payload: DecisionInput,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    return await _decide(requisition_id, payload, "approved", organization, user, session)


@router.post("/{requisition_id}/reject")
async def reject_requisition(
    requisition_id: str,
    payload: DecisionInput,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    return await _decide(requisition_id, payload, "rejected", organization, user, session)


@router.get("/{requisition_id}/decisions")
async def requisition_decisions(
    requisition_id: str,
    organization: Reader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[dict[str, object]]:
    record = await _load(session, organization.id, requisition_id)
    return [
        {
            "id": x.id,
            "decision": x.decision,
            "actor_user_id": x.actor_user_id,
            "reason": x.reason,
            "created_at": x.created_at,
        }
        for x in record.decisions
    ]


class ApprovalRuleInput(BaseModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    minimum_total: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    required_approvals: int = Field(ge=1, le=5)


@router.put("/approval-rules")
async def replace_approval_rules(
    rules: list[ApprovalRuleInput],
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[dict[str, object]]:
    keys = [(rule.currency, rule.minimum_total) for rule in rules]
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=422, detail="Duplicate currency and threshold band")
    await session.execute(
        delete(ProcurementApprovalRule).where(
            ProcurementApprovalRule.organization_id == organization.id
        )
    )
    records = [
        ProcurementApprovalRule(
            id=str(uuid4()),
            organization_id=organization.id,
            currency=rule.currency,
            minimum_total=rule.minimum_total,
            required_approvals=rule.required_approvals,
            created_by_user_id=user.id,
        )
        for rule in rules
    ]
    session.add_all(records)
    await session.commit()
    return [
        {
            "currency": x.currency,
            "minimum_total": x.minimum_total,
            "required_approvals": x.required_approvals,
        }
        for x in records
    ]


@router.get("/approval-rules")
async def list_approval_rules(
    organization: Reader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[dict[str, object]]:
    records = (
        await session.scalars(
            select(ProcurementApprovalRule)
            .where(ProcurementApprovalRule.organization_id == organization.id)
            .order_by(ProcurementApprovalRule.currency, ProcurementApprovalRule.minimum_total)
        )
    ).all()
    return [
        {
            "currency": x.currency,
            "minimum_total": x.minimum_total,
            "required_approvals": x.required_approvals,
        }
        for x in records
    ]


class RequisitionConversionInput(BaseModel):
    supplier_id: str
    purchase_order_reference: str = Field(min_length=2, max_length=80)


@router.post("/{requisition_id}/convert-to-purchase-order", status_code=201)
async def convert_requisition_to_purchase_order(
    requisition_id: str,
    payload: RequisitionConversionInput,
    organization: Manager,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    record = await _load(session, organization.id, requisition_id, lock=True)
    await require_branch_assignment(session, user, organization, record.branch_id)
    if record.converted_purchase_order_id:
        return {
            "requisition_id": record.id,
            "requisition_status": record.status,
            "purchase_order_id": record.converted_purchase_order_id,
        }
    if record.status != "approved":
        raise HTTPException(status_code=409, detail="Only approved requisitions can be converted")
    if record.requested_by_user_id == user.id:
        raise HTTPException(
            status_code=403,
            detail="The requester cannot perform the purchasing conversion",
        )
    if any(
        decision.decision == "approved" and decision.actor_user_id == user.id
        for decision in record.decisions
    ):
        raise HTTPException(
            status_code=403,
            detail="A requisition approver cannot perform the purchasing conversion",
        )
    if any(line.estimated_unit_cost is None for line in record.lines):
        raise HTTPException(
            status_code=422,
            detail="Every requisition line needs an estimated unit cost before conversion",
        )
    supplier = await session.scalar(
        select(Supplier).where(
            Supplier.id == payload.supplier_id,
            Supplier.organization_id == organization.id,
            Supplier.status == "active",
        )
    )
    if supplier is None:
        raise HTTPException(status_code=404, detail="Active supplier not found")
    if supplier.default_currency != record.currency:
        raise HTTPException(
            status_code=422, detail="Supplier currency must match requisition currency"
        )
    purchase_order = PurchaseOrder(
        id=str(uuid4()),
        organization_id=organization.id,
        supplier_id=supplier.id,
        branch_id=record.branch_id,
        reference=payload.purchase_order_reference.strip(),
        status="draft",
        currency=supplier.default_currency,
        notes=f"Generated from requisition {record.reference}",
        idempotency_key=f"requisition:{record.id}",
        created_by_user_id=user.id,
    )
    for line in record.lines:
        purchase_order.lines.append(
            PurchaseOrderLine(
                id=str(uuid4()),
                organization_id=organization.id,
                item_id=line.item_id,
                ordered_quantity=line.quantity,
                received_quantity=Decimal("0"),
                unit_code=line.unit_code,
                unit_cost=line.estimated_unit_cost,
            )
        )
    session.add(purchase_order)
    record.status = "converted"
    record.converted_purchase_order_id = purchase_order.id
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Purchase order reference already exists or requisition was converted",
        ) from exc
    return {
        "requisition_id": record.id,
        "requisition_status": record.status,
        "purchase_order_id": purchase_order.id,
        "purchase_order_reference": purchase_order.reference,
        "purchase_order_status": purchase_order.status,
        "supplier_id": purchase_order.supplier_id,
        "branch_id": purchase_order.branch_id,
        "currency": purchase_order.currency,
        "lines": [
            {
                "item_id": line.item_id,
                "quantity": line.ordered_quantity,
                "unit_cost": line.unit_cost,
                "unit_code": line.unit_code,
            }
            for line in purchase_order.lines
        ],
    }
