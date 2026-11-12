"""Top-level API router."""

from fastapi import APIRouter

from .ai_audit import router as ai_audit_router
from .auth import router as auth_router
from .health import router as health_router
from .identity import router as identity_router
from .inventory import router as inventory_router
from .invitations import router as invitations_router
from .memberships import router as memberships_router
from .organization_enrollments import router as organization_enrollments_router
from .organizations import router as organizations_router
from .reports import router as reports_router
from .replenishment import router as replenishment_router
from .sales import router as sales_router
from .stocktaking import router as stocktaking_router
from .workforce import router as workforce_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(inventory_router)
api_router.include_router(replenishment_router)
api_router.include_router(reports_router)
api_router.include_router(ai_audit_router)
api_router.include_router(sales_router)
api_router.include_router(stocktaking_router)
api_router.include_router(auth_router)
api_router.include_router(identity_router)
api_router.include_router(organizations_router)
api_router.include_router(workforce_router)
api_router.include_router(invitations_router)
api_router.include_router(memberships_router)

api_router.include_router(organization_enrollments_router)
