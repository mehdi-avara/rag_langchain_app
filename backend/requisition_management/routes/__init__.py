from fastapi import APIRouter

from ..search.routes import router as search_router
from .ask import router as ask_router
from .requisitions import router as requisitions_router

requisition_router = APIRouter()
requisition_router.include_router(
    requisitions_router,
    prefix="/requisitions",
)
requisition_router.include_router(
    search_router,
    prefix="/requisitions",
)
requisition_router.include_router(
    ask_router,
    prefix="/requisitions",
)
