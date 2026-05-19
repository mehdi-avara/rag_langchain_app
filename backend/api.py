from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html

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
from routs.assets import router as asset_router
from model_management.routes import model_router
from tag_management.routes import tag_router
from financial_management.routes import financial_router
from property_management.routes import property_router
from buying_management.routes import buying_router
from db.session import SessionLocal
from components.embedding_service import get_or_create_embedding_config, regenerate_missing_embeddings
from financial_management.services import safe_embed_text

settings = get_settings()

app = FastAPI(title="Porsa Search system",
    docs_url=None,
    redoc_url=None,)

app.mount(
    "/static",
    StaticFiles(directory=str(settings.STATIC_DIR)),
    name="static",
)

app.add_middleware(LoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
        swagger_favicon_url="/static/favicon.ico",
    )
    
@app.get("/redoc", include_in_schema=False)
async def custom_redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - ReDoc",
        redoc_js_url="/static/redoc.standalone.js",
        redoc_favicon_url="/static/favicon.ico",
        with_google_fonts=False,
    )

app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(document_router, prefix="/documents", tags=["document"])
app.include_router(comment_router, prefix="/comments", tags=["comments"])
app.include_router(user_router, prefix="/user", tags=["user"])
app.include_router(rbac_router, prefix="/rbac", tags=["rbac"])
app.include_router(asset_router, prefix="/assets", tags=["assets"])
app.include_router(chat_ai_models_router, prefix="/llm", tags=["llm"])
app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(stt_router, prefix="/audio", tags=["Audio"])
app.include_router(model_router, tags=["models"])
app.include_router(tag_router, tags=["system_tags"])
app.include_router(financial_router, tags=["financial_management"])
app.include_router(property_router, tags=["property_management"])
app.include_router(buying_router, tags=["buying_management"])


@app.on_event("startup")
def sync_embedding_config() -> None:
    db = SessionLocal()
    try:
        get_or_create_embedding_config(db, settings.embedding_model, settings.embedding_base_url, settings.embedding_api_key or settings.jina_api_key)
        regenerate_missing_embeddings(db, safe_embed_text)
    finally:
        db.close()
