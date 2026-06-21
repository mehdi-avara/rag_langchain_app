from fastapi import APIRouter

from .requisitions import router as requisitions_router

requisition_router = APIRouter()
requisition_router.include_router(
    requisitions_router,
    prefix="/requisitions",
)
