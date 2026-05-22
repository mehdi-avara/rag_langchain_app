from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.exceptions.app_exception import AppException
from core.exceptions.error_codes import (
    AUTH_REQUIRED,
    BAD_REQUEST,
    FORBIDDEN_STATUS_CODE,
    INTERNAL_ERROR_STATUS_CODE,
    INTERNAL_SERVER_ERROR,
    NOT_FOUND,
    PERMISSION_DENIED,
    UNAUTHORIZED_STATUS_CODE,
    VALIDATION_ERROR,
)


def error_payload(
    *,
    code: str,
    message: str,
    user_message: str,
    details=None,
    request_id: str | None = None,
):
    return {
        "error": {
            "code": code,
            "message": message,
            "user_message": user_message,
            "details": details,
            "request_id": request_id,
        }
    }


def get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(
            code=exc.code,
            message=exc.message,
            user_message=exc.user_message,
            details=exc.details,
            request_id=get_request_id(request),
        ),
        headers=exc.headers,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail

    if isinstance(detail, dict) and "code" in detail:
        code = detail.get("code") or BAD_REQUEST
        message = detail.get("message") or code
        user_message = detail.get("user_message") or message
        details = detail.get("details")
    else:
        message = str(detail)
        details = None

        if exc.status_code == UNAUTHORIZED_STATUS_CODE:
            code = AUTH_REQUIRED
            user_message = "برای ادامه باید وارد حساب کاربری شوید."
        elif exc.status_code == FORBIDDEN_STATUS_CODE:
            code = PERMISSION_DENIED
            user_message = "شما مجوز انجام این عملیات را ندارید."
        elif exc.status_code == 404:
            code = NOT_FOUND
            user_message = "مورد درخواستی پیدا نشد."
        else:
            code = BAD_REQUEST if exc.status_code < 500 else INTERNAL_SERVER_ERROR
            user_message = message

    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(
            code=code,
            message=message,
            user_message=user_message,
            details=details,
            request_id=get_request_id(request),
        ),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error_payload(
            code=VALIDATION_ERROR,
            message="Request validation failed",
            user_message="اطلاعات واردشده معتبر نیست.",
            details=exc.errors(),
            request_id=get_request_id(request),
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=INTERNAL_ERROR_STATUS_CODE,
        content=error_payload(
            code=INTERNAL_SERVER_ERROR,
            message="Internal server error",
            user_message="خطای داخلی سرور رخ داده است.",
            details=None,
            request_id=get_request_id(request),
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
