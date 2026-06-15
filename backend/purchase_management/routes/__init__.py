"""purchase_management routes package."""
from fastapi import APIRouter

from .orders import router as orders_router
from .phases import router as phases_router
from .items import router as items_router
from .costs import router as costs_router
from ..search.routes import router as search_router

purchase_router = APIRouter()
purchase_router.include_router(orders_router)
purchase_router.include_router(phases_router)
purchase_router.include_router(items_router)
purchase_router.include_router(costs_router)
purchase_router.include_router(search_router)
