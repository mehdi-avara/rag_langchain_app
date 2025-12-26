import logging
import time
from logging.handlers import RotatingFileHandler
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from settings import get_settings

settings = get_settings()

LOG_FILE = settings.request_log_file
MAX_LOG_CHARS = settings.request_log_max_chars
MAX_LOG_FILE_SIZE = settings.request_log_max_file_size
BACKUP_COUNT = settings.request_log_backup_count

IGNORED_CONTENT_TYPES = [
    "multipart/form-data",
    "application/octet-stream",
    "application/pdf",
]

IGNORED_PATHS = {
    "/docs",
    "/openapi.json",
    "/redoc",
}

SENSITIVE_PATHS = {
    "/auth/login",
    "/auth/refresh",
}

SENSITIVE_HEADERS = [
    "X-Sensitive",
    "X-Secret",
]


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("api_logger")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger  # avoid duplicate handlers

    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_LOG_FILE_SIZE,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )
    handler.setFormatter(formatter)

    logger.addHandler(handler)
    return logger


logger = setup_logger()


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in IGNORED_PATHS:
            return await call_next(request)
        
        start_time = time.time()

        is_sensitive_path = request.url.path in SENSITIVE_PATHS
        is_sensitive_header = any(
            request.headers.get(header, "").lower() == "true"
            for header in SENSITIVE_HEADERS
        )
        is_sensitive = is_sensitive_path or is_sensitive_header
        
        content_type = request.headers.get("content-type", "").lower()

        should_ignore_body = any(
            ignored in content_type for ignored in IGNORED_CONTENT_TYPES
        )
        
        body_bytes = b""
        body_text = ""
        
        try:
            body_bytes = await request.body()
        except Exception:
            body_bytes = b""
        
        if should_ignore_body:
            body_text = "<body skipped>"
        elif is_sensitive:
            body_text = "<sensitive body redacted>"
        else:
            try:
                body_text = body_bytes.decode("utf-8", errors="ignore")
            except Exception:
                body_text = "<unreadable>"

        body_text = body_text[:MAX_LOG_CHARS]

        async def receive():
            return {"type": "http.request", "body": body_bytes}

        request._receive = receive

        # -------- Process request --------
        response = await call_next(request)

        # -------- Response body --------
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        response_text = response_body.decode("utf-8", errors="ignore")
       
        content_type = response.headers.get("content-type", "").lower()
        
        should_ignore_body = any(
            ignored in content_type for ignored in IGNORED_CONTENT_TYPES
        )
        
        if should_ignore_body:
            response_text = "<body skipped>"
        elif is_sensitive:
            response_text = "<sensitive response redacted>"
        else:
            response_text = response_text[:MAX_LOG_CHARS]

        process_time = round(time.time() - start_time, 3)

        logger.info(
            f"{request.method} {request.url.path} | "
            f"Status: {response.status_code} | "
            f"Time: {process_time}s | "
            f"Request: {body_text} | "
            f"Response: {response_text}"
        )

        # IMPORTANT: recreate response (body was consumed)
        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
