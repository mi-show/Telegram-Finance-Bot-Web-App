from __future__ import annotations

from fastapi import APIRouter

from .api_audit_export import router as audit_export_router
from .api_analytics import router as analytics_router
from .api_budget import router as budget_router
from .api_overview import router as overview_router
from .api_records import router as records_router
from .api_recurring import router as recurring_router
from .api_settings import router as settings_router

router = APIRouter()
router.include_router(overview_router)
router.include_router(records_router)
router.include_router(analytics_router)
router.include_router(budget_router)
router.include_router(settings_router)
router.include_router(recurring_router)
router.include_router(audit_export_router)

