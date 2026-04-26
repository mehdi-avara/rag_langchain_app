from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import require_permission
from Models import User, Document

from ..models import TagDocumentLink
from ..schemas import TagDocumentOut, TagDocLinkCreate, TagDocLinkOut
from routs.documents import upload_pdf_mineru
from ..services import get_tag_or_404, is_admin


router = APIRouter()


@router.post("/{tag_id}/documents", response_model=TagDocLinkOut, status_code=status.HTTP_201_CREATED)
def link_document(
    tag_id: int,
    payload: TagDocLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:documents")),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

    doc = db.query(Document).filter(Document.id == payload.document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not is_admin(current_user) and doc.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to link this document")

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


@router.post("/{tag_id}/documents/upload", response_model=TagDocLinkOut, status_code=status.HTTP_201_CREATED)
def upload_document_and_link(
    tag_id: int,
    file: UploadFile = File(...),
    link_description: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("tags:documents")),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

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
    _ = get_tag_or_404(db, tag_id, current_user.id)

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
    _ = get_tag_or_404(db, tag_id, current_user.id)

    query = (
        db.query(Document, TagDocumentLink)
        .join(TagDocumentLink, TagDocumentLink.document_id == Document.id)
        .filter(TagDocumentLink.tag_id == tag_id)
    )

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