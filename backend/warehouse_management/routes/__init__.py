from fastapi import APIRouter

from ..search.routes import router as search_router
from .ask import router as ask_router
from .warehouse import router as warehouse_routes_router

warehouse_router = APIRouter()
warehouse_router.include_router(warehouse_routes_router)
warehouse_router.include_router(search_router, prefix="/warehouse")
warehouse_router.include_router(ask_router, prefix="/warehouse")

__all__ = ["warehouse_router"]
