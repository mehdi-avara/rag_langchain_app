from fastapi import APIRouter

from .assignments import router as assignments_router
from .departments import router as departments_router
from .positions import router as positions_router

organization_router = APIRouter(
    prefix="/organization",
    tags=["organization_management"],
)
organization_router.include_router(departments_router)
organization_router.include_router(positions_router)
organization_router.include_router(assignments_router)

__all__ = ["organization_router"]
