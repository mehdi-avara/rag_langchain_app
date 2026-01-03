# speech to text service

import os
import httpx
from fastapi import APIRouter, UploadFile, File, Depends

from Models import User
from deps import get_current_user
from settings import get_settings

settings = get_settings()

router = APIRouter()



@router.post("/transcribe")
async def transcribe(
    current_user: User = Depends(get_current_user),
    file: UploadFile = File(...)
    ):
    async with httpx.AsyncClient(timeout=300) as client:
        files = {"file": (file.filename, await file.read(), file.content_type)}
        r = await client.post(f"{settings.STT_URL}/transcribe", files=files)
        r.raise_for_status()
        return r.json()