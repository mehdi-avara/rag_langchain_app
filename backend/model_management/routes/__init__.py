from fastapi import APIRouter

from .models import router as models
from .documents import router as documents_router
from .comments import router as comments_router
from .receipts import router as receipts_router
from .ask import router as ask_router

model_router = APIRouter(prefix="/models")
model_router.include_router(models)
model_router.include_router(documents_router)
model_router.include_router(comments_router)
model_router.include_router(receipts_router)
model_router.include_router(ask_router)

__all__ = ["model_router"]
