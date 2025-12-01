import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from db.init_db import get_db
from Models import Comment, User, CommentFile
from deps import get_current_user
from schemas.comment import (
    CommentFileOut,
    CommentFileUpload,
)


from settings import get_settings


settings = get_settings()

router = APIRouter(tags=["comments files"])




def _parse_file_upload(file: UploadFile = File(...)) -> CommentFileUpload:
    return CommentFileUpload(file=file)


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
