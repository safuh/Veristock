"""Authenticated identity and organization-context endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .authorization import Organization, User
from .authorization_dependencies import get_current_organization, get_current_user, get_db_session
from .authorization_repository import AuthorizationRepository

router = APIRouter(prefix="/identity", tags=["identity"])


class OrganizationSummary(BaseModel):
    id: str
    kind: str
    legal_name: str
    trading_name: str | None
    timezone: str


class CurrentUserResponse(BaseModel):
    id: str
    identifier: str
    status: str
    organizations: list[OrganizationSummary]


class OrganizationContextResponse(BaseModel):
    id: str
    kind: str
    legal_name: str
    timezone: str


@router.get("/me", response_model=CurrentUserResponse)
async def current_user(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CurrentUserResponse:
    """Return the authenticated user and organizations they may select."""
    organizations = await AuthorizationRepository(session).list_active_organizations(
        user.id
    )
    return CurrentUserResponse(
        id=user.id,
        identifier=user.identifier,
        status=user.status,
        organizations=[
            OrganizationSummary(
                id=organization.id,
                kind=organization.kind,
                legal_name=organization.legal_name,
                trading_name=organization.trading_name,
                timezone=organization.timezone,
            )
            for organization in organizations
        ],
    )


@router.get("/context", response_model=OrganizationContextResponse)
async def organization_context(
    organization: Annotated[Organization, Depends(get_current_organization)],
) -> OrganizationContextResponse:
    """Return the active organization context after membership validation."""
    return OrganizationContextResponse(
        id=organization.id,
        kind=organization.kind,
        legal_name=organization.legal_name,
        timezone=organization.timezone,
    )
