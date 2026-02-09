from fastapi import APIRouter

from .models import router as models_router
from .documents import router as documents_router
from .comments import router as comments_router
from .ask import router as ask_router

router = APIRouter(prefix="/models")
router.include_router(models_router)
router.include_router(documents_router)
router.include_router(comments_router)
router.include_router(ask_router)

__all__ = ["router"]
