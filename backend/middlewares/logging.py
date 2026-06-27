import logging
import time
import json
from logging.handlers import RotatingFileHandler
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

SENSITIVE_FIELDS = {
    "password",
    "pass",
    "pwd",
    "token",
    "refresh_token",
    "access_token",
    "notification_token",
}

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


def sanitize_body(body_bytes: b"", content_type: str) -> str:
    try:
        # JSON body
        if "application/json" in content_type:
            data = json.loads(body_bytes.decode("utf-8"))
            if isinstance(data, dict):
                for field in SENSITIVE_FIELDS:
                    if field in data:
                        data[field] = "***REDACTED***"
            return json.dumps(data)

        # Form-urlencoded body
        if "application/x-www-form-urlencoded" in content_type:
            body_str = body_bytes.decode("utf-8")
            parts = body_str.split("&")
            sanitized = []
            for part in parts:
                key, _, value = part.partition("=")
                if key.lower() in SENSITIVE_FIELDS:
                    sanitized.append(f"{key}=***REDACTED***")
                else:
                    sanitized.append(part)
            return "&".join(sanitized)

    except Exception:
        pass

    return "<unreadable or unsupported body>"

def _header(scope_headers, name: str) -> str:
    target = name.lower().encode()
    for key, value in scope_headers or []:
        if key.lower() == target:
            try:
                return value.decode("latin-1")
            except Exception:
                return ""
    return ""


class LoggingMiddleware:
    """Pure-ASGI request/response logger.

    Implemented as raw ASGI (NOT ``BaseHTTPMiddleware``) because
    ``BaseHTTPMiddleware`` is incompatible with streaming responses (SSE): its
    ``receive_or_disconnect`` task-group machinery raises
    ``RuntimeError: Unexpected message received: http.request`` for any
    ``StreamingResponse``. A pure ASGI middleware streams responses through
    untouched and never wraps ``receive`` in a way that breaks disconnect
    listening.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") in IGNORED_PATHS:
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        path = scope.get("path", "")
        method = scope.get("method", "")
        req_headers = scope.get("headers", [])

        is_sensitive_path = path in SENSITIVE_PATHS
        is_sensitive_header = any(
            _header(req_headers, header).lower() == "true" for header in SENSITIVE_HEADERS
        )
        is_sensitive = is_sensitive_path or is_sensitive_header

        req_content_type = _header(req_headers, "content-type").lower()
        should_ignore_req_body = any(ignored in req_content_type for ignored in IGNORED_CONTENT_TYPES)

        # ---- buffer the request body, then replay it downstream ----
        body_chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.request":
                body_chunks.append(message.get("body", b""))
                more_body = message.get("more_body", False)
            elif message["type"] == "http.disconnect":
                more_body = False
        body_bytes = b"".join(body_chunks)

        if should_ignore_req_body:
            body_text = "<body skipped>"
        elif is_sensitive:
            body_text = sanitize_body(body_bytes, req_content_type)
        else:
            body_text = body_bytes.decode("utf-8", errors="ignore")
        body_text = body_text[:MAX_LOG_CHARS]

        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            # Body already delivered — defer to the real transport so the app can
            # observe a genuine http.disconnect (required by streaming responses).
            return await receive()

        # ---- capture the response (skip buffering for streaming) ----
        status_code = {"code": 0}
        is_stream = {"flag": False}
        resp_content_type = {"value": ""}
        captured: list[bytes] = []

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                status_code["code"] = message["status"]
                resp_content_type["value"] = _header(message.get("headers", []), "content-type").lower()
                is_stream["flag"] = "text/event-stream" in resp_content_type["value"]
            elif message["type"] == "http.response.body":
                if not is_stream["flag"]:
                    captured.append(message.get("body", b""))
            await send(message)

        await self.app(scope, replay_receive, wrapped_send)

        process_time = round(time.time() - start_time, 3)

        if is_stream["flag"]:
            response_text = "<streaming>"
        else:
            response_body = b"".join(captured)
            ct = resp_content_type["value"]
            if any(ignored in ct for ignored in IGNORED_CONTENT_TYPES):
                response_text = "<body skipped>"
            elif is_sensitive:
                response_text = sanitize_body(response_body, ct)
            else:
                response_text = response_body.decode("utf-8", errors="ignore")[:MAX_LOG_CHARS]

        logger.info(
            f"{method} {path} | "
            f"Status: {status_code['code']} | "
            f"Time: {process_time}s | "
            f"Request: {body_text} | "
            f"Response: {response_text}"
        )
