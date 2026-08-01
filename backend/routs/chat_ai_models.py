from datetime import datetime
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from Models import ChatAIModels, User
from core.exceptions.error_codes import (
    LLM_ENDPOINT_NOT_ALLOWED,
)
from core.llm_security import (
    LLMEndpointSecurityError,
    validate_llm_base_url,
)
from db.init_db import get_db
from deps import require_platform_permission
from schemas.chat_ai_models import (
    ChatAIModelIn,
    ChatAIModelOut,
    ChatAIModelUpdate,
)
from settings import get_settings


router = APIRouter()
settings = get_settings()


def _validated_endpoint(
    value: str,
) -> str:
    try:
        return validate_llm_base_url(
            value,
            settings,
        )

    except LLMEndpointSecurityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": LLM_ENDPOINT_NOT_ALLOWED,
                "message": (
                    "The LLM endpoint is not allowed"
                ),
            },
        ) from exc


@router.get(
    "",
    response_model=List[ChatAIModelOut],
)
def list_chat_ai_models(
    current_user: User = Depends(
        require_platform_permission(
            "llm:read"
        )
    ),
    db: Session = Depends(get_db),
):
    return db.query(
        ChatAIModels
    ).all()


@router.post(
    "",
    response_model=ChatAIModelOut,
    status_code=status.HTTP_201_CREATED,
)
def create_chat_ai_model(
    payload: ChatAIModelIn,
    current_user: User = Depends(
        require_platform_permission(
            "llm:create"
        )
    ),
    db: Session = Depends(get_db),
):
    chat_ai_model = ChatAIModels(
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        url=_validated_endpoint(
            payload.url
        ),
        api_key=payload.api_key,
    )

    db.add(
        chat_ai_model
    )

    db.commit()
    db.refresh(
        chat_ai_model
    )

    return chat_ai_model


@router.put(
    "/{chat_ai_model_id}",
    response_model=ChatAIModelOut,
)
def update_chat_ai_model(
    chat_ai_model_id: int,
    payload: ChatAIModelUpdate,
    current_user: User = Depends(
        require_platform_permission(
            "llm:update"
        )
    ),
    db: Session = Depends(get_db),
):
    chat_ai_model = (
        db.query(
            ChatAIModels
        )
        .filter(
            ChatAIModels.id
            == chat_ai_model_id
        )
        .first()
    )

    if not chat_ai_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat AI model not found",
        )

    update_data = payload.model_dump(
        exclude_unset=True
    )

    if "url" in update_data:
        update_data["url"] = (
            _validated_endpoint(
                update_data["url"]
            )
        )

    for key, value in update_data.items():
        setattr(
            chat_ai_model,
            key,
            value,
        )

    chat_ai_model.updated_at = (
        datetime.utcnow()
    )

    db.commit()
    db.refresh(
        chat_ai_model
    )

    return chat_ai_model


@router.delete(
    "/{chat_ai_model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_chat_ai_model(
    chat_ai_model_id: int,
    current_user: User = Depends(
        require_platform_permission(
            "llm:delete"
        )
    ),
    db: Session = Depends(get_db),
):
    chat_ai_model = (
        db.query(
            ChatAIModels
        )
        .filter(
            ChatAIModels.id
            == chat_ai_model_id
        )
        .first()
    )

    if not chat_ai_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat AI model not found",
        )

    db.delete(
        chat_ai_model
    )

    db.commit()
