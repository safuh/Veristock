"""Application factory and composition root."""

from collections.abc import Callable
from datetime import timedelta
from typing import cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ExceptionHandler

from .api.router import api_router
from .auth.application import AuthenticationApplication
from .auth.tokens import TokenService
from .core.config import Environment, Settings, get_settings
from .core.errors import (
    BackboneError,
    backbone_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from .core.lifespan import lifespan
from .core.logging import configure_logging
from .core.middleware import RequestContextMiddleware
from .identity import create_sqlalchemy_auth_application

AuthApplicationFactory = Callable[[AsyncSession], AuthenticationApplication]


def create_app(
    settings: Settings | None = None,
    auth_application_factory: AuthApplicationFactory | None = None,
    access_token_service: TokenService | None = None,
) -> FastAPI:
    """Create the API application with explicit authentication composition.

    When JWT settings are provided, the standard SQLAlchemy authentication
    application and access-token validator are composed automatically. Custom
    implementations can be injected for tests or alternate identity providers.
    """
    resolved = settings or get_settings()
    configure_logging(resolved)

    if resolved.jwt_secret_key is not None:
        secret_key = resolved.jwt_secret_key.get_secret_value()
        if auth_application_factory is None:
            auth_application_factory = lambda session: create_sqlalchemy_auth_application(
                session,
                secret_key=secret_key,
                access_token_lifetime=timedelta(
                    seconds=resolved.access_token_lifetime_seconds
                ),
                refresh_token_lifetime=timedelta(
                    seconds=resolved.refresh_token_lifetime_seconds
                ),
            )
        if access_token_service is None:
            access_token_service = TokenService(secret_key)
    elif resolved.environment is Environment.PRODUCTION and (
        auth_application_factory is None or access_token_service is None
    ):
        raise ValueError(
            "Production requires JWT_SECRET_KEY or explicit authentication services"
        )

    app = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        debug=resolved.debug,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.auth_application_factory = auth_application_factory
    app.state.access_token_service = access_token_service

    app.add_middleware(RequestContextMiddleware)
    if resolved.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_origins,
            allow_credentials=resolved.cors_allow_credentials,
            allow_methods=resolved.cors_allow_methods,
            allow_headers=resolved.cors_allow_headers,
        )

    app.add_exception_handler(
        BackboneError,
        cast(ExceptionHandler, backbone_error_handler),
    )
    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, validation_error_handler),
    )
    app.add_exception_handler(
        StarletteHTTPException,
        cast(ExceptionHandler, http_error_handler),
    )
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(api_router, prefix=resolved.api_prefix)
    return app
