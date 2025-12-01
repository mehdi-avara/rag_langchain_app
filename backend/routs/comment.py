import os
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from Models import Comment, User, CommentFile
from deps import get_current_user
from schemas.comment import (
    CommentCreate,
    CommentFileOut,
    CommentFileUpload,
    CommentOut,
    CommentUpdate,
)


from components import generate_embeddings_for_chunks
from settings import get_settings

router = APIRouter(tags=["comments"])
settings = get_settings()


@router.get("/", response_model=List[CommentOut])
def list_comments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all comments."""
    comments = db.query(Comment).order_by(Comment.created_at.desc()).all()
    return comments


@router.get("/{comment_id}", response_model=CommentOut)
def get_comment_by_id(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a single comment by id."""
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.get("/by-doc/{doc_id}", response_model=List[CommentOut])
def get_comments_by_doc(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all comments for a specific document."""
    comments = (
        db.query(Comment)
        .filter(Comment.doc_id == doc_id)
        .order_by(Comment.created_at.desc())
        .all()
    )
    return comments


@router.get("/by-chunk/{chunk_id}", response_model=List[CommentOut])
def get_comments_by_chunk(
    chunk_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all comments for a specific chunk."""
    comments = (
        db.query(Comment)
        .filter(Comment.chunk_id == chunk_id)
        .order_by(Comment.created_at.desc())
        .all()
    )
    return comments


@router.post("/", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def create_comment(
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new comment.

    We also generate an embedding for the comment content and store it.
    """
    # generate embedding for this comment's text
    # your helper returns List[List[float]], so take the first
    embeddings = generate_embeddings_for_chunks([payload.content])
    embedding_vec = embeddings[0] if embeddings else None

    new_comment = Comment(
        user_id=current_user.id,
        system_tag_id=payload.system_tag_id,
        doc_id=payload.doc_id,
        chunk_id=payload.chunk_id,
        content=payload.content,
        type=payload.type,
        embedding=embedding_vec
    )
    if payload.media_addresses:
        new_comment.files = [
            CommentFile(
                media_address=addr,
                file_name=os.path.basename(addr),
                user_id=current_user.id,
            )
            for addr in payload.media_addresses
        ]

    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)

    return new_comment


@router.put("/{comment_id}", response_model=CommentOut)
async def update_comment_text(
    comment_id: int,
    payload: CommentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update comment content (and re-embed).
    """
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # regenerate embedding for new text
    embeddings = generate_embeddings_for_chunks([payload.content])
    embedding_vec = embeddings[0] if embeddings else None

    comment.content = payload.content
    comment.embedding = embedding_vec

    db.commit()
    db.refresh(comment)
    return comment


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a comment by id.
    """
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    db.delete(comment)
    db.commit()
    return None


def _parse_file_upload(file: UploadFile = File(...)) -> CommentFileUpload:
    return CommentFileUpload(file=file)


@router.post(
    "/add-files/{comment_id}",
    response_model=CommentFileOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_file_to_comment(
    comment_id: int,
    upload: CommentFileUpload = Depends(_parse_file_upload),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Attach a file to a comment and persist it to disk and DB.
    """
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    base_dir = os.path.join(settings.files_dir, "comments", str(comment_id))
    os.makedirs(base_dir, exist_ok=True)

    file_path = os.path.join(base_dir, upload.file.filename)
    file_bytes = await upload.file.read()
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    new_file = CommentFile(
        user_id=current_user.id,
        comment_id=comment_id,
        file_name=upload.file.filename,
        media_address=file_path,
    )
    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    return new_file
