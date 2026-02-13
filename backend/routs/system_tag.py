from fastapi import APIRouter

from tag_management.routes.tags import router as tags_router
from tag_management.routes.documents import router as documents_router
from tag_management.routes.models import router as models_router
from tag_management.routes.comments import router as comments_router


router = APIRouter(prefix="", tags=["system_tags"])
router.include_router(tags_router)
router.include_router(documents_router)
router.include_router(models_router)
router.include_router(comments_router)

__all__ = ["router"]
