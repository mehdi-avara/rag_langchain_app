from core.exceptions.app_exception import AppException
from core.exceptions.error_codes import (
    CHAT_NOT_FOUND,
    DOCUMENT_NOT_FOUND,
    NOT_FOUND_STATUS_CODE,
)


def chat_not_found_exception() -> AppException:
    return AppException(
        status_code=NOT_FOUND_STATUS_CODE,
        code=CHAT_NOT_FOUND,
        message="Chat not found",
    )


def document_not_found_exception() -> AppException:
    return AppException(
        status_code=NOT_FOUND_STATUS_CODE,
        code=DOCUMENT_NOT_FOUND,
        message="Document not found",
    )
