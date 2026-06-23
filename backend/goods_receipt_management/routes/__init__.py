from fastapi import APIRouter

from ..search.routes import router as search_router
from .ask import router as ask_router
from .goods_receipts import router as goods_receipts_router

goods_receipt_router = APIRouter()
goods_receipt_router.include_router(
    goods_receipts_router,
    prefix="/goods-receipts",
)
goods_receipt_router.include_router(
    search_router,
    prefix="/goods-receipts",
)
goods_receipt_router.include_router(
    ask_router,
    prefix="/goods-receipts",
)
