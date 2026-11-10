"""Application factory and composition root."""

from collections.abc import Callable
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
from .core.config import Settings, get_settings
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

AuthApplicationFactory = Callable[[AsyncSession], AuthenticationApplication]


def create_app(
    settings: Settings | None = None,
    auth_application_factory: AuthApplicationFactory | None = None,
    access_token_service: TokenService | None = None,
) -> FastAPI:
    """Create the API application with explicit authentication composition.

    The authentication application issues tokens; the access-token service
    validates them on protected identity and business routes. Both are supplied
    by the consuming application so the same secret and algorithm are deliberate.
    """
    resolved = settings or get_settings()
    configure_logging(resolved)

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
