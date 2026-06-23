from fastapi import APIRouter

from ..search.routes import router as search_router
from .ask import router as ask_router
from .rfqs import router as rfqs_router

rfq_router = APIRouter()
rfq_router.include_router(rfqs_router, prefix="/rfqs")
rfq_router.include_router(search_router, prefix="/rfqs")
rfq_router.include_router(ask_router, prefix="/rfqs")
