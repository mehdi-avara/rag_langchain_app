from fastapi import HTTPException
from sqlalchemy.orm import Session

from Models import User, SystemTag


def is_admin(user: User) -> bool:
    return user.role == "admin"


def get_tag_or_404(db: Session, tag_id: int, user_id: int) -> SystemTag:
    tag = (
        db.query(SystemTag)
        .filter(SystemTag.id == tag_id, SystemTag.owner_id == user_id)
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="System tag not found")
    return tag


def validate_parent_tag(db: Session, parent_id: int | None, user_id: int) -> SystemTag | None:
    if parent_id is None:
        return None

    parent = (
        db.query(SystemTag)
        .filter(SystemTag.id == parent_id, SystemTag.owner_id == user_id)
        .first()
    )
    if not parent:
        raise HTTPException(status_code=404, detail="Parent tag not found")
    return parent


def check_no_cycle(db: Session, tag: SystemTag, new_parent_id: int | None, user_id: int) -> None:
    if new_parent_id is None:
        return

    if new_parent_id == tag.id:
        raise HTTPException(status_code=400, detail="A tag cannot be its own parent")

    current = (
        db.query(SystemTag)
        .filter(SystemTag.id == new_parent_id, SystemTag.owner_id == user_id)
        .first()
    )
    while current is not None:
        if current.id == tag.id:
            raise HTTPException(
                status_code=400,
                detail="Cannot set a descendant as parent (cycle detected)",
            )
        if current.father_tag_id is None:
            break
        current = (
            db.query(SystemTag)
            .filter(SystemTag.id == current.father_tag_id, SystemTag.owner_id == user_id)
            .first()
        )
