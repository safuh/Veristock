"""Authenticated identity and tenant-context dependencies for API routes."""

from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from veristock.auth import TokenError, TokenService
from veristock.core.errors import BackboneError

from .authorization import Organization
from .authorization_repository import AuthorizationRepository
from .models import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped database session."""
    session_factory = getattr(request.app.state, "db_session_factory", None)
    if session_factory is None:
        raise BackboneError(
            "database_not_configured",
            "Database is not configured",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    async with session_factory() as session:
        yield session


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Resolve the bearer token subject to an active persisted user."""
    token_service: TokenService | None = getattr(
        request.app.state, "access_token_service", None
    )
    if token_service is None:
        raise BackboneError(
            "authentication_not_configured",
            "Access-token validation is not configured",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = token_service.decode(
            credentials.credentials, expected_type="access"
        )
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await session.scalar(select(User).where(User.id == payload["sub"]))
    if user is None or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or unavailable",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_organization(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    organization_id: Annotated[str, Header(alias="X-Organization-ID")],
) -> Organization:
    """Resolve an organization only after verifying active membership."""
    organization = await session.get(Organization, organization_id)
    if organization is None or not await AuthorizationRepository(
        session
    ).has_active_membership(user.id, organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active organization membership required",
        )
    return organization


def require_permission(permission_code: str) -> Callable[..., object]:
    """Create a dependency that enforces a permission in the active organization."""

    async def permission_dependency(
        user: Annotated[User, Depends(get_current_user)],
        organization: Annotated[Organization, Depends(get_current_organization)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> Organization:
        allowed = await AuthorizationRepository(session).has_permission(
            user.id, organization.id, permission_code
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient organization permission",
            )
        return organization

    return permission_dependency
