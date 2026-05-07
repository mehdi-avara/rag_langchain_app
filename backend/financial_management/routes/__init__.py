from fastapi import APIRouter

from .ask import router as ask_router
from .cards import router as cards_router
from .comments import router as comments_router
from .files import router as files_router
from .receipts import router as receipts_router
from ..search import search_router

financial_router = APIRouter(prefix="/financial_management", tags=["financial_management"])
financial_router.include_router(cards_router)
financial_router.include_router(ask_router)
financial_router.include_router(comments_router)
financial_router.include_router(files_router)
financial_router.include_router(receipts_router)
financial_router.include_router(search_router)

__all__ = ["financial_router"]
