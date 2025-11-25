# core/celery_app.py
from celery import Celery

celery_app = Celery(
    "porsa",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)

celery_app.conf.update(
    task_serializer="pickle",     # so we can pass bytes easily
    accept_content=["pickle"],    # match serializer
    result_serializer="pickle",
    timezone="Asia/Tehran",       # or your timezone
    enable_utc=True,
)