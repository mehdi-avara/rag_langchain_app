from fastapi import APIRouter

from .tags import router as main_router
from .documents import router as documents_router
from .models import router as models_router
from .comments import router as comments_router
from .receipts import router as receipts_router
from .ask import router as ask_router

tag_router = APIRouter(prefix="/system_tags", tags=["system_tags"])
tag_router.include_router(main_router)
tag_router.include_router(documents_router)
tag_router.include_router(models_router)
tag_router.include_router(comments_router)
tag_router.include_router(receipts_router)
tag_router.include_router(ask_router)

__all__ = ["tag_router"]
