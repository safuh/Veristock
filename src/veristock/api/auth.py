"""HTTP transport for the password authentication lifecycle."""

import hmac
import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..auth import (
    AuthenticationApplication,
    AuthenticationError,
    IdentifierAlreadyExistsError,
    LoginRequest,
    RegistrationError,
    RegistrationRequest,
    TokenError,
)
from ..core.config import Environment
from ..core.errors import BackboneError

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "veristock_refresh"
CSRF_COOKIE = "veristock_csrf"
CSRF_HEADER = "X-CSRF-Token"


class CredentialsRequest(BaseModel):
    """Credentials accepted by registration and login endpoints."""

    identifier: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenRequest(BaseModel):
    """Refresh token accepted by rotation and logout endpoints."""

    refresh_token: str = Field(min_length=1)


class RegistrationResponseModel(BaseModel):
    """Public registration response."""

    subject: str


class TokenResponseModel(BaseModel):
    """Public access/refresh token response."""

    subject: str
    access_token: str
    refresh_token: str


async def _session(request: Request) -> AsyncSession:
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    return session_factory()


def _application(request: Request, session: AsyncSession) -> AuthenticationApplication:
    factory: Callable[[AsyncSession], AuthenticationApplication] | None = getattr(
        request.app.state, "auth_application_factory", None
    )
    if factory is None:
        raise BackboneError(
            "auth_not_configured",
            "Authentication is not configured",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return factory(session)


@router.post("/register", response_model=RegistrationResponseModel, status_code=201)
async def register(
    request: Request,
    body: CredentialsRequest,
    session: Annotated[AsyncSession, Depends(_session)],
) -> RegistrationResponseModel:
    if not request.app.state.settings.allow_self_registration:
        raise BackboneError(
            "registration_disabled",
            "Self-registration is disabled; request an invitation",
            status.HTTP_403_FORBIDDEN,
        )
    try:
        result = await _application(request, session).register(
            RegistrationRequest(identifier=body.identifier, password=body.password)
        )
        await session.commit()
    except IdentifierAlreadyExistsError as exc:
        await session.rollback()
        raise BackboneError("identifier_exists", "Identifier is already registered", 409) from exc
    except RegistrationError as exc:
        await session.rollback()
        raise BackboneError("registration_error", str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return RegistrationResponseModel(subject=result.subject)


@router.post("/login", response_model=TokenResponseModel)
async def login(
    request: Request,
    body: CredentialsRequest,
    session: Annotated[AsyncSession, Depends(_session)],
) -> TokenResponseModel:
    try:
        result = await _application(request, session).login(
            LoginRequest(identifier=body.identifier, password=body.password)
        )
        await session.commit()
    except AuthenticationError as exc:
        await session.rollback()
        raise BackboneError(
            "invalid_credentials", "Invalid credentials", status.HTTP_401_UNAUTHORIZED
        ) from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return TokenResponseModel(
        subject=result.subject,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
    )


@router.post("/refresh", response_model=TokenResponseModel)
async def refresh(
    request: Request,
    body: TokenRequest,
    session: Annotated[AsyncSession, Depends(_session)],
) -> TokenResponseModel:
    try:
        result = await _application(request, session).refresh(body.refresh_token)
        await session.commit()
    except TokenError as exc:
        await session.rollback()
        raise BackboneError("invalid_refresh_token", "Invalid refresh token", 401) from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return TokenResponseModel(
        subject=result.subject,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    body: TokenRequest,
    session: Annotated[AsyncSession, Depends(_session)],
) -> Response:
    try:
        await _application(request, session).logout(body.refresh_token)
        await session.commit()
    except TokenError as exc:
        await session.rollback()
        raise BackboneError("invalid_refresh_token", "Invalid refresh token", 401) from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return Response(status_code=204)



class BrowserTokenResponseModel(BaseModel):
    """Browser login/refresh response; refresh token is cookie-only."""

    subject: str
    access_token: str


def _cookie_security(request: Request) -> bool:
    """Use Secure cookies in production; permit HTTP localhost development."""
    return request.app.state.settings.environment is Environment.PRODUCTION


def _set_browser_cookies(
    response: Response, request: Request, refresh_token: str
) -> None:
    """Set the HttpOnly refresh cookie and double-submit CSRF cookie."""
    settings = request.app.state.settings
    secure = _cookie_security(request)
    csrf_token = secrets.token_urlsafe(32)
    cookie_options = {
        "secure": secure,
        "samesite": "lax",
        "path": "/",
        "max_age": settings.refresh_token_lifetime_seconds,
    }
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        httponly=True,
        **cookie_options,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        **cookie_options,
    )


def _validate_browser_csrf(request: Request) -> None:
    """Validate the double-submit CSRF token for cookie-authenticated actions."""
    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get(CSRF_HEADER)
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise BackboneError(
            "csrf_validation_failed",
            "A valid CSRF token is required",
            status.HTTP_403_FORBIDDEN,
        )


def _clear_browser_cookies(response: Response, request: Request) -> None:
    """Clear browser authentication cookies after logout."""
    secure = _cookie_security(request)
    for name, httponly in ((REFRESH_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(
            name,
            path="/",
            secure=secure,
            httponly=httponly,
            samesite="lax",
        )


@router.post("/browser/login", response_model=BrowserTokenResponseModel)
async def browser_login(
    request: Request,
    body: CredentialsRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(_session)],
) -> BrowserTokenResponseModel:
    """Authenticate a browser and keep its refresh token out of JavaScript."""
    try:
        result = await _application(request, session).login(
            LoginRequest(identifier=body.identifier, password=body.password)
        )
        await session.commit()
    except AuthenticationError as exc:
        await session.rollback()
        raise BackboneError(
            "invalid_credentials", "Invalid credentials", status.HTTP_401_UNAUTHORIZED
        ) from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    _set_browser_cookies(response, request, result.refresh_token)
    return BrowserTokenResponseModel(
        subject=result.subject,
        access_token=result.access_token,
    )


@router.post("/browser/refresh", response_model=BrowserTokenResponseModel)
async def browser_refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(_session)],
) -> BrowserTokenResponseModel:
    """Rotate the HttpOnly refresh cookie after CSRF validation."""
    _validate_browser_csrf(request)
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise BackboneError(
            "refresh_cookie_missing",
            "Browser refresh session is unavailable",
            status.HTTP_401_UNAUTHORIZED,
        )
    try:
        result = await _application(request, session).refresh(refresh_token)
        await session.commit()
    except TokenError as exc:
        await session.rollback()
        raise BackboneError(
            "invalid_refresh_token", "Invalid refresh token", status.HTTP_401_UNAUTHORIZED
        ) from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

    _set_browser_cookies(response, request, result.refresh_token)
    return BrowserTokenResponseModel(
        subject=result.subject,
        access_token=result.access_token,
    )


@router.post("/browser/logout", status_code=204)
async def browser_logout(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(_session)],
) -> Response:
    """Revoke the HttpOnly refresh cookie and clear browser auth cookies."""
    _validate_browser_csrf(request)
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        try:
            await _application(request, session).logout(refresh_token)
            await session.commit()
        except TokenError as exc:
            await session.rollback()
            raise BackboneError(
                "invalid_refresh_token", "Invalid refresh token", status.HTTP_401_UNAUTHORIZED
            ) from exc
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    _clear_browser_cookies(response, request)
    return response
