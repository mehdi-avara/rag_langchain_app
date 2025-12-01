from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from Models import User, SystemTag, Document
from db.init_db import get_db
from deps import get_current_user
from schemas.system_tag import (
    SystemTagOut,
    SystemTagCreate,
    SystemTagUpdate,
    SystemTagTreeOut,
)
from schemas.document import DocumentOut

router = APIRouter(
    prefix="",
    tags=["system_tags"],
)


# ---------- Helpers ----------

def _get_tag_for_user(
    db: Session,
    tag_id: int,
    user_id: int,
) -> SystemTag:
    tag = (
        db.query(SystemTag)
        .filter(SystemTag.id == tag_id, SystemTag.owner_id == user_id)
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="System tag not found")
    return tag


def _validate_parent_tag(
    db: Session,
    parent_id: Optional[int],
    user_id: int,
) -> Optional[SystemTag]:
    """
    Returns parent tag if parent_id is not None.
    Ensures parent exists and belongs to current user.
    """
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


def _check_no_cycle(
    db: Session,
    tag: SystemTag,
    new_parent_id: Optional[int],
    user_id: int,
):
    """
    Prevents making a tag a child of itself or one of its descendants.
    """
    if new_parent_id is None:
        return

    if new_parent_id == tag.id:
        raise HTTPException(
            status_code=400,
            detail="A tag cannot be its own parent",
        )

    # Walk up the parent chain from new_parent to root
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
            .filter(
                SystemTag.id == current.father_tag_id,
                SystemTag.owner_id == user_id,
            )
            .first()
        )


# ---------- CRUD Endpoints ----------

@router.get(
    "/",
    response_model=List[SystemTagOut],
    status_code=status.HTTP_200_OK,
)
async def list_system_tags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    root_only: bool = Query(False, description="If true, only return root tags"),
):
    """
    List all system tags for current user.
    If root_only=True, return only tags with no parent (father_tag_id is null).
    """
    query = db.query(SystemTag).filter(SystemTag.owner_id == current_user.id)
    if root_only:
        query = query.filter(SystemTag.father_tag_id.is_(None))

    return query.order_by(SystemTag.created_at).all()


@router.get(
    "/{tag_id}",
    response_model=SystemTagOut,
    status_code=status.HTTP_200_OK,
)
async def get_system_tag(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get a single system tag by id (must belong to current user).
    """
    tag = _get_tag_for_user(db, tag_id, current_user.id)
    return tag


@router.post(
    "/",
    response_model=SystemTagOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_system_tag(
    payload: SystemTagCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new system tag.
    - owner_id is taken from current user
    - father_tag_id is validated (must belong to user if provided)
    """
    # Validate parent if provided
    _ = _validate_parent_tag(db, payload.father_tag_id, current_user.id)

    tag = SystemTag(
        owner_id=current_user.id,
        father_tag_id=payload.father_tag_id,
        tag_name=payload.tag_name,
        description=payload.description,
    )

    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.put(
    "/{tag_id}",
    response_model=SystemTagOut,
    status_code=status.HTTP_200_OK,
)
async def update_system_tag(
    tag_id: int,
    payload: SystemTagUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update a system tag.
    - All fields are optional (partial update).
    - father_tag_id is validated and cycles are prevented.
    """
    tag = _get_tag_for_user(db, tag_id, current_user.id)

    # If father_tag_id is being changed, validate and ensure no cycles
    if payload.father_tag_id is not None or payload.father_tag_id is None:
        # Only check if field actually provided; in practice you may distinguish not-set vs explicitly-none
        new_parent_id = payload.father_tag_id
        if new_parent_id != tag.father_tag_id:
            # Check parent exists (unless None) + no cycle
            if new_parent_id is not None:
                _validate_parent_tag(db, new_parent_id, current_user.id)
            _check_no_cycle(db, tag, new_parent_id, current_user.id)
            tag.father_tag_id = new_parent_id

    if payload.tag_name is not None:
        tag.tag_name = payload.tag_name

    if payload.description is not None:
        tag.description = payload.description

    db.commit()
    db.refresh(tag)
    return tag


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_system_tag(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a system tag.
    - Cascades to child tags thanks to `cascade="all, delete-orphan"` on relationship.
    - Documents pointing to this tag will be detached (system_tag_id = NULL) to avoid FK issues.
    """
    tag = _get_tag_for_user(db, tag_id, current_user.id)

    # Detach documents from this tag (set system_tag_id to NULL)
    docs = (
        db.query(Document)
        .filter(
            Document.owner_id == current_user.id,
            Document.system_tag_id == tag.id,
        )
        .all()
    )
    for doc in docs:
        doc.system_tag_id = None

    db.delete(tag)
    db.commit()
    return None


# ---------- Extra: Children & Underlying Documents ----------

@router.get(
    "/{tag_id}/children",
    response_model=List[SystemTagOut],
    status_code=status.HTTP_200_OK,
)
async def list_child_tags(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List child system tags of a given system tag.
    """
    parent = _get_tag_for_user(db, tag_id, current_user.id)
    # children relationship is defined on the model
    # If you want them ordered, you can sort by created_at or tag_name.
    return sorted(parent.children, key=lambda t: t.created_at)


@router.get(
    "/{tag_id}/documents",
    response_model=List[DocumentOut],
    status_code=status.HTTP_200_OK,
)
async def list_tag_documents(
    tag_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """
    List documents directly associated with a given system tag.
    Paginated like your /{doc_id}/chunks endpoint.
    """
    # Ensure the tag belongs to this user
    _ = _get_tag_for_user(db, tag_id, current_user.id)

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


# ---------- Optional: Full Tree for Frontend ----------

# @router.get(
#     "/tree",
#     response_model=List[SystemTagTreeOut],
#     status_code=status.HTTP_200_OK,
# )
# async def get_system_tag_tree(
#     current_user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     """
#     Returns all system tags for the current user as a tree:
#     - top level: tags with no parent (father_tag_id is null)
#     - each node has `children: List[SystemTagTreeOut]`
#     Frontend can use this directly to show a nested tree.
#     """
#     tags = (
#         db.query(SystemTag)
#         .filter(SystemTag.owner_id == current_user.id)
#         .all()
#     )

#     # Build nodes
#     nodes = {
#         t.id: SystemTagTreeOut(
#             id=t.id,
#             tag_name=t.tag_name,
#             description=t.description,
#             father_tag_id=t.father_tag_id,
#             children=[],
#         )
#         for t in tags
#     }

#     roots: List[SystemTagTreeOut] = []

#     for t in tags:
#         node = nodes[t.id]
#         if t.father_tag_id is None or t.father_tag_id not in nodes:
#             roots.append(node)
#         else:
#             parent_node = nodes[t.father_tag_id]
#             parent_node.children.append(node)

#     return roots