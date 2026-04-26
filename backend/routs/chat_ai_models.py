from typing import List
from datetime import datetime

from fastapi import Depends, APIRouter, status, HTTPException
from sqlalchemy.orm import Session

from Models import ChatAIModels, User
from db.init_db import get_db
from schemas.chat_ai_models import ChatAIModelOut, ChatAIModelIn, ChatAIModelUpdate
from deps import require_permission


router = APIRouter()


@router.get("", response_model=List[ChatAIModelOut])
def list_chat_ai_models(
    current_user: User = Depends(require_permission("llm:read")),
    db: Session = Depends(get_db),
):
    return db.query(ChatAIModels).all()


@router.post("", response_model=ChatAIModelOut, status_code=status.HTTP_201_CREATED)
def create_chat_ai_model(
    payload: ChatAIModelIn,
    current_user: User = Depends(require_permission("llm:create")),
    db: Session = Depends(get_db),
):
    chat_ai_model = ChatAIModels(
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        url=payload.url,
        api_key=payload.api_key,
    )

    db.add(chat_ai_model)
    db.commit()
    db.refresh(chat_ai_model)

    return chat_ai_model


@router.put("/{chat_ai_model_id}", response_model=ChatAIModelOut)
def update_chat_ai_model(
    chat_ai_model_id: int,
    payload: ChatAIModelUpdate,
    current_user: User = Depends(require_permission("llm:update")),
    db: Session = Depends(get_db),
):
    chat_ai_model = db.query(ChatAIModels).filter(ChatAIModels.id == chat_ai_model_id).first()

    if not chat_ai_model:
        raise HTTPException(status_code=404, detail="Chat AI model not found")

    update_data = payload.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(chat_ai_model, key, value)

    chat_ai_model.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(chat_ai_model)

    return chat_ai_model


@router.delete("/{chat_ai_model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_ai_model(
    chat_ai_model_id: int,
    current_user: User = Depends(require_permission("llm:delete")),
    db: Session = Depends(get_db),
):
    chat_ai_model = db.query(ChatAIModels).filter(ChatAIModels.id == chat_ai_model_id).first()

    if not chat_ai_model:
        raise HTTPException(status_code=404, detail="Chat AI model not found")

    db.delete(chat_ai_model)
    db.commit()