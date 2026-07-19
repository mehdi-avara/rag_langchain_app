"""purchase_management routes package."""
from fastapi import APIRouter

from .orders import router as orders_router
from .lines import router as lines_router
from .phases import router as phases_router
from .costs import router as costs_router
from .splits import router as splits_router
from .amendments import router as amendments_router
from ..search.routes import router as search_router

purchase_router = APIRouter()
purchase_router.include_router(orders_router)
purchase_router.include_router(lines_router)
purchase_router.include_router(phases_router)
purchase_router.include_router(costs_router)
purchase_router.include_router(splits_router)
purchase_router.include_router(amendments_router)
purchase_router.include_router(search_router)
