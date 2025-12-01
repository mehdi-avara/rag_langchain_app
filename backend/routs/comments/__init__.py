from fastapi import APIRouter

from .comment import router as main_comment_router
from .files import router as files_router


router = APIRouter()

router.include_router(
    main_comment_router,
    prefix=""
)
router.include_router(
    files_router,
    prefix="/files"
)