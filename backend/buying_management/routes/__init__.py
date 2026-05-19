from fastapi import APIRouter

from .costs import router as costs_router
from .items import router as items_router
from .processes import router as processes_router
from .receipts import router as receipts_router
from .summary import router as summary_router

buying_router = APIRouter(prefix="/buying")
buying_router.include_router(processes_router)
buying_router.include_router(items_router)
buying_router.include_router(receipts_router)
buying_router.include_router(costs_router)
buying_router.include_router(summary_router)

__all__ = ["buying_router"]

