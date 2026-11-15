"""Tenant-scoped read API for AI execution audit metadata."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.ai.models import AIExecutionRecord
from veristock.identity.authorization import Organization
from veristock.identity.authorization_dependencies import (
    get_db_session,
    require_permission,
)

router = APIRouter(prefix="/reports", tags=["reports"])
AIExecutionReader = Annotated[
    Organization, Depends(require_permission("inventory.read"))
]


class AIExecutionRecordRead(BaseModel):
    """Safe operational metadata for one AI execution."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    operation: str
    status: str
    provider: str | None
    model: str | None
    model_version: str | None
    latency_ms: int | None
    request_id: str | None
    source_references: list[str]
    failure_code: str | None
    created_at: datetime


@router.get("/ai-executions", response_model=list[AIExecutionRecordRead])
async def list_ai_executions(
    organization: AIExecutionReader,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AIExecutionRecordRead]:
    """List recent AI activity for the selected tenant, never across tenants."""
    statement = (
        select(AIExecutionRecord)
        .where(AIExecutionRecord.organization_id == organization.id)
        .order_by(AIExecutionRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    records = list((await session.scalars(statement)).all())
    return [AIExecutionRecordRead.model_validate(record) for record in records]
