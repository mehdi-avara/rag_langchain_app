from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User, Document

from ..models import ModelDocumentLink
from ..schemas import ModelDocLinkCreate, ModelDocLinkOut, ModelDocumentOut
from routs.documents import upload_pdf_mineru, _get_accessible_document, _get_accessible_document_ids
from ..services import get_model_or_404


router = APIRouter()


@router.post("/{model_id}/documents", response_model=ModelDocLinkOut)
def link_document(
    model_id: int,
    payload: ModelDocLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:documents")),
):
    model = get_model_or_404(db, model_id, current_user)

    doc = _get_accessible_document(db, payload.document_id, current_user, "read")

    link = (
        db.query(ModelDocumentLink)
        .filter(
            ModelDocumentLink.model_id == model.id,
            ModelDocumentLink.document_id == doc.id,
        )
        .first()
    )
    if link:
        return link

    link = ModelDocumentLink(
        model_id=model.id,
        document_id=doc.id,
        linked_by_user_id=current_user.id,
        note=payload.note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.post("/{model_id}/documents/upload", response_model=ModelDocLinkOut, status_code=status.HTTP_201_CREATED)
def upload_document_and_link(
    model_id: int,
    file: UploadFile = File(...),
    link_description: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:documents")),
):
    _ = get_model_or_404(db, model_id, current_user)

    upload_result = upload_pdf_mineru(file=file, current_user=current_user, db=db)
    doc_id = upload_result.get("doc_id")
    if doc_id is None:
        raise HTTPException(status_code=500, detail="Document upload did not return doc_id")

    payload = ModelDocLinkCreate(document_id=doc_id, note=link_description)
    return link_document(model_id=model_id, payload=payload, db=db, current_user=current_user)


@router.delete("/{model_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_document(
    model_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:documents")),
):
    _ = get_model_or_404(db, model_id, current_user)
    _get_accessible_document(db, document_id, current_user, "read")

    link = (
        db.query(ModelDocumentLink)
        .filter(
            ModelDocumentLink.model_id == model_id,
            ModelDocumentLink.document_id == document_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    db.delete(link)
    db.commit()
    return None


@router.get("/{model_id}/documents", response_model=List[ModelDocumentOut])
def list_linked_documents(
    model_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("models:documents")),
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _ = get_model_or_404(db, model_id, current_user)

    query = (
        db.query(Document, ModelDocumentLink)
        .join(ModelDocumentLink, ModelDocumentLink.document_id == Document.id)
        .filter(ModelDocumentLink.model_id == model_id)
    )

    accessible_doc_ids = _get_accessible_document_ids(db, current_user, "read")
    if accessible_doc_ids is not None:
        if not accessible_doc_ids:
            return []
        query = query.filter(Document.id.in_(accessible_doc_ids))

    if search:
        query = query.filter(Document.filename.ilike(f"%{search}%"))
    if status_filter:
        query = query.filter(Document.status == status_filter)

    rows = (
        query
        .order_by(ModelDocumentLink.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results: List[ModelDocumentOut] = []
    for doc, link in rows:
        results.append(
            ModelDocumentOut(
                id=doc.id,
                filename=doc.filename,
                n_pages=doc.n_pages,
                n_chunks=doc.n_chunks,
                created_at=doc.created_at,
                status=doc.status,
                abstract=doc.abstract,
                file_path=doc.file_path,
                note=link.note,
                linked_at=link.created_at,
            )
        )

    return results