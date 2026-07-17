from fastapi import APIRouter

from .definitions import router as definitions_router
from .instances import router as instances_router

workflow_router = APIRouter(
    prefix="/workflow",
    tags=["workflow_management"],
)
workflow_router.include_router(definitions_router)
workflow_router.include_router(instances_router)

__all__ = ["workflow_router"]
