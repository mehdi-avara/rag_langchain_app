# core/celery_app.py
from celery import Celery
from settings import get_settings

settings = get_settings()
redis_url = settings.redis_url

celery_app = Celery(
    "porsa",
    broker=redis_url,
    include=["core.celery.tasks"],
)

celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    timezone="Asia/Tehran",
    enable_utc=True,
    task_time_limit=10000,      # kill task after 10 minutes
    task_soft_time_limit=9000  # warn 1 minute earlier
)