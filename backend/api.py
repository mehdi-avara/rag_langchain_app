from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from settings import get_settings
from middlewares.logging import LoggingMiddleware

from routs.auth import router as auth_router
from routs.documents import router as document_router
from routs.comments import comment_router
from routs.users import router as user_router
from routs.chat_ai_models import router as chat_ai_models_router
from routs.chat import router as chat_router
from routs.stt import router as stt_router
from routs.rbac import router as rbac_router
from model_management.routes import model_router
from tag_management.routes import tag_router


settings = get_settings()

app = FastAPI(title="Porsa Search system")

app.add_middleware(LoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(document_router, prefix="/documents", tags=["document"])
app.include_router(comment_router, prefix="/comments", tags=["comments"])
app.include_router(user_router, prefix="/user", tags=["user"])
app.include_router(rbac_router, prefix="/rbac", tags=["rbac"])
app.include_router(chat_ai_models_router, prefix="/llm", tags=["llm"])
app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(stt_router, prefix="/audio", tags=["Audio"])
app.include_router(model_router, tags=["models"])
app.include_router(tag_router, tags=["system_tags"])