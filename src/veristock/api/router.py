"""Top-level API router."""
from fastapi import APIRouter

from .auth import router as auth_router
from .health import router as health_router
from .identity import router as identity_router
from .invitations import router as invitations_router
from .memberships import router as memberships_router
from .organizations import router as organizations_router\nfrom .organization_enrollments import router as organization_enrollments_router
from .workforce import router as workforce_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(identity_router)
api_router.include_router(organizations_router)
api_router.include_router(workforce_router)
api_router.include_router(invitations_router)
api_router.include_router(memberships_router)
\napi_router.include_router(organization_enrollments_router)\n