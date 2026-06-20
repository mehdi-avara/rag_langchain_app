from fastapi import APIRouter

from ..search import search_router
from .ask import router as ask_router
from .suppliers import router as suppliers_router

supplier_router = APIRouter(prefix="/supplier_management", tags=["supplier_management"])
supplier_router.include_router(search_router)
supplier_router.include_router(ask_router)
supplier_router.include_router(suppliers_router)

__all__ = ["supplier_router"]
