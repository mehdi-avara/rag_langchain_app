import os
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from db.init_db import get_db
from Models import Comment, User, CommentFile
from deps import get_current_user
from schemas.comment import CommentFileName, CommentFileOut, CommentFileUpload

from settings import get_settings

settings = get_settings()

router = APIRouter(tags=["comments files"])


def _parse_file_upload(file: UploadFile = File(...),index: bool = False) -> CommentFileUpload:
    return CommentFileUpload(file=file,index=index)


@router.get("/{comment_id}", response_model=List[CommentFileName])
def list_comment_files(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all files attached to a comment.
    """
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    files = (
        db.query(CommentFile)
        .filter(CommentFile.comment_id == comment_id)
        .order_by(CommentFile.id.desc())
        .all()
    )
    return files


@router.get("/{comment_id}/{file_id}/download")
def download_comment_file(
    comment_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Download a single file attached to a comment.
    """
    file_rec = (
        db.query(CommentFile)
        .filter(CommentFile.id == file_id, CommentFile.comment_id == comment_id)
        .first()
    )
    if not file_rec:
        raise HTTPException(status_code=404, detail="File not found for this comment")

    if not os.path.isfile(file_rec.media_address):
        raise HTTPException(status_code=404, detail="Stored file is missing")

    return FileResponse(
        path=file_rec.media_address,
        filename=file_rec.file_name,
        media_type="application/octet-stream",
    )


@router.post(
    "/add/{comment_id}",
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


@router.delete(
    "/{comment_id}/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_comment_file(
    comment_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a file record and remove it from disk if present.
    """
    file_rec = (
        db.query(CommentFile)
        .filter(CommentFile.id == file_id, CommentFile.comment_id == comment_id)
        .first()
    )
    if not file_rec:
        raise HTTPException(status_code=404, detail="File not found for this comment")


    if os.path.isfile(file_rec.media_address):
        os.remove(file_rec.media_address)
    db.delete(file_rec)
    db.commit()

    return None
