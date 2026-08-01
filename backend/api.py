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
from routs.company import router as company_router
from routs.assets import router as asset_router
from routs.developer_docs import router as developer_docs_router
from model_management.routes import model_router
from tag_management.routes import tag_router
from document_intelligence.routes import router as di_router
from financial_management.routes import financial_router
from property_management.routes import property_router
# buying_management removed — Phase 0.2; replaced by purchase_management below
from purchase_management.routes import purchase_router
from supplier_management.routes import supplier_router
from material_management.routes import material_router
from requisition_management.routes import requisition_router
from rfq_management.routes import rfq_router
from goods_receipt_management.routes import goods_receipt_router
from warehouse_management.routes import warehouse_router
from business_management.routes import business_router
from organization_management.routes import organization_router
from workflow_management.routes import workflow_router
from shared.currency.routes import router as currency_router
from shared.export.routes import router as export_router
from shared.reporting.routes import router as reporting_router
from assistant.routes import router as assistant_router
from routs.tasks import router as tasks_router
from db.session import SessionLocal
from db.init_db import seed_default_user
from components.embedding_service import get_or_create_embedding_config, regenerate_missing_embeddings
from financial_management.services import safe_embed_text
from core.exceptions import register_exception_handlers

settings = get_settings()

app = FastAPI(title="Porsa Search system",
    docs_url=None,
    redoc_url=None,)

register_exception_handlers(app)

app.mount(
    "/static",
    StaticFiles(directory=str(settings.STATIC_DIR)),
    name="static",
)

app.add_middleware(LoggingMiddleware)

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
app.include_router(company_router, prefix="/company", tags=["company"])
app.include_router(asset_router, prefix="/assets", tags=["assets"])
app.include_router(developer_docs_router, tags=["developer_docs"])
app.include_router(chat_ai_models_router, prefix="/llm", tags=["llm"])
app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(stt_router, prefix="/audio", tags=["Audio"])
app.include_router(model_router, tags=["models"])
app.include_router(tag_router, tags=["system_tags"])
app.include_router(financial_router, tags=["financial_management"])
app.include_router(property_router, tags=["property_management"])
app.include_router(export_router, tags=["exports"])
app.include_router(reporting_router, tags=["reporting"])
app.include_router(purchase_router, tags=["purchase_management"])
app.include_router(supplier_router, tags=["supplier_management"])
app.include_router(material_router, tags=["material_management"])
app.include_router(requisition_router, tags=["requisition_management"])
app.include_router(rfq_router, tags=["rfq_management"])
app.include_router(goods_receipt_router, tags=["goods_receipt_management"])
app.include_router(warehouse_router, tags=["warehouse_management"])
app.include_router(business_router, tags=["business_management"])
app.include_router(organization_router)
app.include_router(workflow_router)
app.include_router(currency_router, prefix="/currencies", tags=["currencies"])
app.include_router(tasks_router, tags=["tasks"])
app.include_router(assistant_router, prefix="/assistant", tags=["assistant"])
app.include_router(di_router)



@app.on_event("startup")
def seed_default_user_on_startup() -> None:
    if settings.bootstrap_admin_enabled:
        seed_default_user()


@app.on_event("startup")
def sync_embedding_config() -> None:
    db = SessionLocal()
    try:
        get_or_create_embedding_config(db, settings.embedding_model, settings.embedding_base_url, settings.embedding_api_key or settings.jina_api_key)
        regenerate_missing_embeddings(db, safe_embed_text)
    finally:
        db.close()

# CORS must wrap the complete ASGI application so responses generated by
# Starlette's outer error middleware also receive CORS headers.
application = CORSMiddleware(
    app=app,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Content-Range",
        "Accept-Ranges",
        "Content-Length",
    ],
)
