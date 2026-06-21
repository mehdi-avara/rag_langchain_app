from fastapi import APIRouter

from .goods_receipts import router as goods_receipts_router

goods_receipt_router = APIRouter()
goods_receipt_router.include_router(
    goods_receipts_router,
    prefix="/goods-receipts",
)
