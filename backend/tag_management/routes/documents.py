from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User, Document

from ..models import TagDocumentLink
from ..schemas import TagDocumentOut, TagDocLinkCreate, TagDocLinkOut
from schemas.asset import AssetCompleteUploadIn, AssetUploadUrlCreate, AssetUploadUrlOut
from routs.documents import (
    upload_pdf_mineru,
    create_document_upload_url,
    complete_document_upload,
    _get_accessible_document,
    _get_accessible_document_ids,
)
from ..services import get_tag_or_404


router = APIRouter()


@router.post("/{tag_id}/documents", response_model=TagDocLinkOut, status_code=status.HTTP_201_CREATED)
def link_document(
    tag_id: int,
    payload: TagDocLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:documents")),
):
    _ = get_tag_or_404(db, tag_id, current_user)

    doc = _get_accessible_document(db, payload.document_id, current_user, "read")

    link = (
        db.query(TagDocumentLink)
        .filter(
            TagDocumentLink.tag_id == tag_id,
            TagDocumentLink.document_id == doc.id,
        )
        .first()
    )
    if link:
        link.start_page = payload.start_page
        link.end_page = payload.end_page
        link.note = payload.note
        db.commit()
        db.refresh(link)
        return link

    link = TagDocumentLink(
        tag_id=tag_id,
        document_id=doc.id,
        linked_by_user_id=current_user.id,
        start_page=payload.start_page,
        end_page=payload.end_page,
        note=payload.note,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.post("/{tag_id}/documents/upload-url", response_model=AssetUploadUrlOut, status_code=status.HTTP_201_CREATED)
def create_tag_document_upload_url(
    tag_id: int,
    payload: AssetUploadUrlCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:documents")),
):
    _ = get_tag_or_404(db, tag_id, current_user)

    return create_document_upload_url(
        payload=payload,
        db=db,
        current_user=current_user,
    )


@router.post("/{tag_id}/documents/complete-upload/{asset_id}", response_model=TagDocLinkOut, status_code=status.HTTP_201_CREATED)
def complete_tag_document_upload_and_link(
    tag_id: int,
    asset_id: int,
    payload: AssetCompleteUploadIn,
    link_description: Optional[str] = Query(None),
    start_page: Optional[int] = Query(None, ge=1),
    end_page: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:documents")),
):
    _ = get_tag_or_404(db, tag_id, current_user)

    upload_result = complete_document_upload(
        asset_id=asset_id,
        payload=payload,
        db=db,
        current_user=current_user,
    )

    doc_id = upload_result.get("doc_id") if isinstance(upload_result, dict) else getattr(upload_result, "doc_id", None)

    if doc_id is None:
        raise HTTPException(status_code=500, detail="Document upload did not return doc_id")

    payload = TagDocLinkCreate(
        document_id=doc_id,
        start_page=start_page,
        end_page=end_page,
        note=link_description,
    )
    return link_document(tag_id=tag_id, payload=payload, db=db, current_user=current_user)


@router.post("/{tag_id}/documents/upload", response_model=TagDocLinkOut, status_code=status.HTTP_201_CREATED)
def upload_document_and_link(
    tag_id: int,
    file: UploadFile = File(...),
    link_description: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:documents")),
):
    _ = get_tag_or_404(db, tag_id, current_user)

    upload_result = upload_pdf_mineru(file=file, current_user=current_user, db=db)
    doc_id = upload_result.get("doc_id")
    if doc_id is None:
        raise HTTPException(status_code=500, detail="Document upload did not return doc_id")

    payload = TagDocLinkCreate(document_id=doc_id, note=link_description)
    return link_document(tag_id=tag_id, payload=payload, db=db, current_user=current_user)


@router.delete("/{tag_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_document(
    tag_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:documents")),
):
    _ = get_tag_or_404(db, tag_id, current_user)
    _get_accessible_document(db, document_id, current_user, "read")

    link = (
        db.query(TagDocumentLink)
        .filter(
            TagDocumentLink.tag_id == tag_id,
            TagDocumentLink.document_id == document_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    db.delete(link)
    db.commit()
    return None


@router.get("/{tag_id}/documents", response_model=List[TagDocumentOut], status_code=status.HTTP_200_OK)
def list_tag_documents(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:documents")),
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _ = get_tag_or_404(db, tag_id, current_user)

    query = (
        db.query(Document, TagDocumentLink)
        .join(TagDocumentLink, TagDocumentLink.document_id == Document.id)
        .filter(TagDocumentLink.tag_id == tag_id)
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
        .order_by(TagDocumentLink.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results: List[TagDocumentOut] = []
    for doc, link in rows:
        results.append(
            TagDocumentOut(
                id=doc.id,
                filename=doc.filename,
                system_tag_id=link.tag_id,
                n_pages=doc.n_pages,
                n_chunks=doc.n_chunks,
                created_at=doc.created_at,
                status=doc.status,
                abstract=doc.abstract,
                file_path=doc.file_path,
                start_page=link.start_page,
                end_page=link.end_page,
                note=link.note,
                linked_at=link.created_at,
            )
        )

    return results