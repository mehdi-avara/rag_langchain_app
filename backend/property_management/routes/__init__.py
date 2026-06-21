from fastapi import APIRouter

from .properties import router as properties_router
from .summary import router as summary_router

property_router = APIRouter(
    prefix="/property_management",
    tags=["property_management"],
)
property_router.include_router(properties_router)
property_router.include_router(summary_router)

__all__ = ["property_router"]
