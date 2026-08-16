from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.authorization import is_company_admin
from Models import Document, User, UserDocumentAccess


def has_document_access(
    db: Session,
    doc: Document,
    current_user: User,
    action: str,
) -> bool:
    if doc.owner_id == current_user.id:
        return True

    if is_company_admin(current_user):
        return True

    access = (
        db.query(UserDocumentAccess)
        .filter(
            UserDocumentAccess.document_id == doc.id,
            UserDocumentAccess.user_id == current_user.id,
        )
        .first()
    )

    if not access:
        return False

    return bool(
        {
            "read": access.can_read,
            "download": access.can_download,
            "ask": access.can_ask,
            "update": access.can_update,
            "delete": access.can_delete,
        }.get(action, False)
    )


def get_company_document(
    db: Session,
    doc_id: int,
    current_user: User,
) -> Document:
    if current_user.company_id is None:
        raise HTTPException(
            status_code=403,
            detail="User has no company",
        )

    doc = (
        db.query(Document)
        .join(User, User.id == Document.owner_id)
        .filter(
            Document.id == doc_id,
            User.company_id == current_user.company_id,
        )
        .first()
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    return doc


def get_accessible_document(
    db: Session,
    doc_id: int,
    current_user: User,
    action: str = "read",
) -> Document:
    doc = get_company_document(
        db,
        doc_id,
        current_user,
    )

    if not has_document_access(
        db,
        doc,
        current_user,
        action,
    ):
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        )

    return doc


def get_accessible_document_ids(
    db: Session,
    current_user: User,
    action: str = "read",
) -> list[int] | None:
    if current_user.company_id is None:
        raise HTTPException(
            status_code=403,
            detail="User has no company",
        )

    if is_company_admin(current_user):
        return None

    access_column = {
        "read": UserDocumentAccess.can_read,
        "download": UserDocumentAccess.can_download,
        "ask": UserDocumentAccess.can_ask,
        "update": UserDocumentAccess.can_update,
        "delete": UserDocumentAccess.can_delete,
    }.get(action)

    if access_column is None:
        return []

    owned_ids = [
        row[0]
        for row in (
            db.query(Document.id)
            .join(User, User.id == Document.owner_id)
            .filter(
                User.company_id == current_user.company_id,
                Document.owner_id == current_user.id,
            )
            .all()
        )
    ]

    granted_ids = [
        row[0]
        for row in (
            db.query(UserDocumentAccess.document_id)
            .join(
                Document,
                Document.id == UserDocumentAccess.document_id,
            )
            .join(
                User,
                User.id == Document.owner_id,
            )
            .filter(
                User.company_id == current_user.company_id,
                UserDocumentAccess.user_id == current_user.id,
                access_column.is_(True),
            )
            .all()
        )
    ]

    return list(
        dict.fromkeys(
            owned_ids + granted_ids
        )
    )
