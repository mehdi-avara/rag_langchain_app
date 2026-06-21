from fastapi import APIRouter

from .rfqs import router as rfqs_router

rfq_router = APIRouter()
rfq_router.include_router(rfqs_router, prefix="/rfqs")
