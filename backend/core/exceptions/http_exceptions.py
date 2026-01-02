from fastapi import HTTPException
from core.exceptions.error_codes import (
    NOT_FOUND_STATUS_CODE,
    CHAT_NOT_FOUND,
)

def chat_not_found_exception() -> HTTPException:
    return HTTPException(
        status_code=NOT_FOUND_STATUS_CODE,
        detail=CHAT_NOT_FOUND,
    )

def document_not_found_exception():
    return HTTPException(
        status_code=NOT_FOUND_STATUS_CODE,
        detail=DOCUMENT_NOT_FOUND,
    )