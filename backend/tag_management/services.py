from fastapi import HTTPException
from sqlalchemy.orm import Session

from Models import User

from .system_tag import SystemTag
from .models import TagDocumentLink, TagCommentLink


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



def get_descendant_tag_ids(db: Session, root_tag_id: int, user_id: int) -> list[int]:
    tags = db.query(SystemTag).filter(SystemTag.owner_id == user_id).all()
    children_map: dict[int | None, list[int]] = {}
    for tag in tags:
        children_map.setdefault(tag.father_tag_id, []).append(tag.id)

    discovered: list[int] = []
    stack = [root_tag_id]
    seen = set()

    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        discovered.append(current)
        stack.extend(children_map.get(current, []))

    return discovered

def get_doc_ids(db: Session, tag_id: int) -> list[int]:
    rows = (
        db.query(TagDocumentLink.document_id)
        .filter(TagDocumentLink.tag_id == tag_id)
        .all()
    )
    return [row[0] for row in rows]


def get_comment_ids(db: Session, tag_id: int) -> list[int]:
    rows = (
        db.query(TagCommentLink.comment_id)
        .filter(TagCommentLink.tag_id == tag_id)
        .all()
    )
    return [row[0] for row in rows]


def get_doc_ids_for_tags(db: Session, tag_ids: list[int]) -> list[int]:
    if not tag_ids:
        return []

    rows = (
        db.query(TagDocumentLink.document_id)
        .filter(TagDocumentLink.tag_id.in_(tag_ids))
        .all()
    )
    return list({row[0] for row in rows})


def get_comment_ids_for_tags(db: Session, tag_ids: list[int]) -> list[int]:
    if not tag_ids:
        return []

    rows = (
        db.query(TagCommentLink.comment_id)
        .filter(TagCommentLink.tag_id.in_(tag_ids))
        .all()
    )
    return list({row[0] for row in rows})
