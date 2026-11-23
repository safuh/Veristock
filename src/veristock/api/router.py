"""Top-level API router."""

from fastapi import APIRouter

from .auth import router as auth_router
from .batches import router as batches_router
from .branch_assignments import router as branch_assignments_router
from .health import router as health_router
from .identity import router as identity_router
from .inventory import router as inventory_router
from .invitations import router as invitations_router
from .memberships import router as memberships_router
from .organization_enrollments import router as organization_enrollments_router
from .organizations import router as organizations_router
from .reconciliation import router as reconciliation_router
from .replenishment import router as replenishment_router
from .reports import router as reports_router
from .sales import router as sales_router
from .stocktake_evidence import router as stocktake_evidence_router
from .stocktaking import router as stocktaking_router
from .suppliers import router as suppliers_router
from .transfers import router as transfers_router
from .workforce import router as workforce_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(inventory_router)
api_router.include_router(batches_router)
api_router.include_router(transfers_router)
api_router.include_router(suppliers_router)
api_router.include_router(replenishment_router)
api_router.include_router(reports_router)
api_router.include_router(sales_router)
api_router.include_router(stocktaking_router)
api_router.include_router(reconciliation_router)
api_router.include_router(stocktake_evidence_router)
api_router.include_router(auth_router)
api_router.include_router(identity_router)
api_router.include_router(organizations_router)
api_router.include_router(workforce_router)
api_router.include_router(invitations_router)
api_router.include_router(memberships_router)
api_router.include_router(branch_assignments_router)
api_router.include_router(organization_enrollments_router)
