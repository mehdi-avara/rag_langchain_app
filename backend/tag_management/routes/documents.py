from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from deps import get_current_user
from Models import User, Document

from ..schemas import TagDocumentOut
from ..services import get_tag_or_404


router = APIRouter()


@router.get("/{tag_id}/documents", response_model=List[TagDocumentOut], status_code=status.HTTP_200_OK)
async def list_tag_documents(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
):
    _ = get_tag_or_404(db, tag_id, current_user.id)

    offset = (page - 1) * page_size

    docs = (
        db.query(Document)
        .filter(
            Document.owner_id == current_user.id,
            Document.system_tag_id == tag_id,
        )
        .order_by(Document.created_at)
        .offset(offset)
        .limit(page_size)
        .all()
    )

    return docs
