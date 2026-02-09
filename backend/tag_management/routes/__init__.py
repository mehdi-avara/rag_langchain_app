from fastapi import APIRouter

from .tags import router as tags_router
from .documents import router as documents_router
from .models import router as models_router

router = APIRouter(prefix="/system_tags",tags=["system_tags"])
router.include_router(tags_router)
router.include_router(documents_router)
router.include_router(models_router)

__all__ = ["router"]
