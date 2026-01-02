from .auth import router as auth_router
from .documents import router as document_router
from .comments import comment_router
from .users import router as user_router
from .chat_ai_models import router as chat_ai_models_router
from .system_tag import router as system_tag_router
from .chat import router as chat_router

__all__ = [
    "auth_router",
    "document_router",
    "user_router",
    "comment_router",
    "chat_ai_models_router",
    "system_tag_router",
    "chat_router",
]
