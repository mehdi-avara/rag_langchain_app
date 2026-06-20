from fastapi import APIRouter

from .ask import router as ask_router
from .items import router as items_router
from ..search.routes import router as search_router

material_router = APIRouter()
material_router.include_router(items_router, prefix="/materials")
material_router.include_router(search_router, prefix="/materials")
material_router.include_router(ask_router, prefix="/materials")
