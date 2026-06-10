from __future__ import annotations

from typing import Any, Dict, List, Optional

from Models.comment import CommentType

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from Models import Chunk, Comment, Document, User
from components.embedding import JinaAPIEmbeddings
from settings import get_settings


settings = get_settings()


def _embedding_client() -> JinaAPIEmbeddings:
    return JinaAPIEmbeddings()


def search_documents_text(
    db: Session,
    query_text: str,
    owner_id: Optional[int] = None,
    company_id: Optional[int] = None,
    doc_ids: Optional[List[int]] = None,
    limit: int = 50,
) -> List[Document]:
    pattern = f"%{query_text}%"
    chunk_match = (
        db.query(Chunk.id)
        .filter(
            Chunk.doc_id == Document.id,
            Chunk.document_version_id == Document.current_version_id,
            Chunk.content.ilike(pattern),
        )
        .exists()
    )

    query = db.query(Document)

    if company_id is not None:
        query = query.join(User, User.id == Document.owner_id).filter(User.company_id == company_id)
    elif owner_id is not None:
        query = query.filter(Document.owner_id == owner_id)

    if doc_ids is not None:
        if not doc_ids:
            return []
        query = query.filter(Document.id.in_(doc_ids))

    query = query.filter(
        or_(
            Document.filename.ilike(pattern),
            Document.status.ilike(pattern),
            Document.abstract.ilike(pattern),
            Document.file_path.ilike(pattern),
            chunk_match,
        )
    )
    return query.order_by(Document.created_at.desc()).limit(limit).all()


def search_comments_text(
    db: Session,
    query_text: str,
    user_id: Optional[int] = None,
    company_id: Optional[int] = None,
    comment_ids: Optional[List[int]] = None,
    limit: int = 50,
) -> List[Comment]:
    pattern = f"%{query_text}%"

    query = db.query(Comment)

    if company_id is not None:
        query = query.join(User, User.id == Comment.user_id).filter(User.company_id == company_id)
    elif user_id is not None:
        query = query.filter(Comment.user_id == user_id)

    if comment_ids is not None:
        if not comment_ids:
            return []
        query = query.filter(Comment.id.in_(comment_ids))

    query = query.filter(
        or_(
            Comment.title.ilike(pattern),
            Comment.content.ilike(pattern),
            Comment.type.ilike(pattern),
        )
    )
    return query.order_by(Comment.created_at.desc()).limit(limit).all()


def search_document_part_hits_semantic(
    db: Session,
    query_text: str,
    owner_id: Optional[int] = None,
    company_id: Optional[int] = None,
    doc_ids: Optional[List[int]] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    query_embedding = _embedding_client().embed_query(query_text)
    if not query_embedding:
        return []
    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

    filters = ["c.embedding IS NOT NULL"]
    params: Dict[str, Any] = {
        "query_vec": embedding_str,
        "limit": limit,
    }

    join_users = False

    if company_id is not None:
        join_users = True
        filters.append("u.company_id = :company_id")
        params["company_id"] = company_id
    elif owner_id is not None:
        filters.append("d.owner_id = :owner_id")
        params["owner_id"] = owner_id

    if doc_ids is not None:
        if not doc_ids:
            return []
        placeholders = ", ".join(f":doc_id_{i}" for i in range(len(doc_ids)))
        filters.append(f"d.id IN ({placeholders})")
        for i, doc_id in enumerate(doc_ids):
            params[f"doc_id_{i}"] = doc_id

    where_clause = " AND ".join(filters)
    user_join_sql = "JOIN users u ON u.id = d.owner_id" if join_users else ""

    sql = text(
        f"""
        SELECT
            d.id AS document_id,
            d.filename AS document_title,
            c.id AS part_id,
            c.content AS part_text,
            d.created_at AS document_created_at,
            d.status AS document_status,
            d.owner_id AS document_owner_id,
            (1 - (c.embedding <=> (:query_vec)::vector)) AS similarity
        FROM documents d
        JOIN chunks c ON c.doc_id = d.id
        {user_join_sql}
        WHERE c.document_version_id = d.current_version_id
          AND {where_clause}
        ORDER BY similarity DESC
        LIMIT :limit
        """
    )

    rows = db.execute(sql, params).fetchall()
    return [
        {
            "document_id": row.document_id,
            "document_title": row.document_title,
            "part_id": row.part_id,
            "part_text": row.part_text,
            "createdAt": row.document_created_at,
            "status": row.document_status,
            "owner_id": row.document_owner_id,
        }
        for row in rows
    ]


def search_comment_hits_semantic(
    db: Session,
    query_text: str,
    user_id: Optional[int] = None,
    company_id: Optional[int] = None,
    comment_ids: Optional[List[int]] = None,
    types: Optional[List[CommentType]] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    query_embedding = _embedding_client().embed_query(query_text)
    if not query_embedding:
        return []
    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

    filters = ["c.embedding IS NOT NULL"]
    params: Dict[str, Any] = {
        "query_vec": embedding_str,
        "limit": limit,
    }

    join_users = False

    if company_id is not None:
        join_users = True
        filters.append("u.company_id = :company_id")
        params["company_id"] = company_id
    elif user_id is not None:
        filters.append("c.user_id = :user_id")
        params["user_id"] = user_id

    if comment_ids is not None:
        if not comment_ids:
            return []
        placeholders = ", ".join(f":comment_id_{i}" for i in range(len(comment_ids)))
        filters.append(f"c.id IN ({placeholders})")
        for i, comment_id in enumerate(comment_ids):
            params[f"comment_id_{i}"] = comment_id

    if types:
        placeholders = ", ".join(f":comment_type_{i}" for i in range(len(types)))
        filters.append(f"c.type IN ({placeholders})")
        for i, comment_type in enumerate(types):
            params[f"comment_type_{i}"] = comment_type.value if hasattr(comment_type, "value") else str(comment_type)

    where_clause = " AND ".join(filters)
    user_join_sql = "JOIN users u ON u.id = c.user_id" if join_users else ""

    sql = text(
        f"""
        SELECT
            c.id AS comment_id,
            c.title AS comment_title,
            c.content AS comment_content,
            c.type AS comment_type,
            c.created_at AS comment_created_at,
            c.user_id AS comment_user_id,
            (1 - (c.embedding <=> (:query_vec)::vector)) AS similarity
        FROM comments c
        {user_join_sql}
        WHERE {where_clause}
        ORDER BY similarity DESC
        LIMIT :limit
        """
    )

    rows = db.execute(sql, params).fetchall()
    return [
        {
            "comment_id": row.comment_id,
            "comment_title": row.comment_title,
            "comment_content": row.comment_content,
            "type": row.comment_type,
            "createdAt": row.comment_created_at,
            "userId": row.comment_user_id,
        }
        for row in rows
    ]


def search_documents_semantic(
    db: Session,
    query_text: str,
    owner_id: Optional[int] = None,
    company_id: Optional[int] = None,
    doc_ids: Optional[List[int]] = None,
    limit: int = 50,
) -> List[Document]:
    part_hits = search_document_part_hits_semantic(
        db=db,
        query_text=query_text,
        owner_id=owner_id,
        company_id=company_id,
        doc_ids=doc_ids,
        limit=limit,
    )
    if not part_hits:
        return []

    seen: set[int] = set()
    ids_in_order: List[int] = []
    for hit in part_hits:
        doc_id = hit["document_id"]
        if doc_id not in seen:
            seen.add(doc_id)
            ids_in_order.append(doc_id)

    docs = db.query(Document).filter(Document.id.in_(ids_in_order)).all()
    docs_by_id = {doc.id: doc for doc in docs}
    return [docs_by_id[doc_id] for doc_id in ids_in_order if doc_id in docs_by_id]


def search_comments_semantic(
    db: Session,
    query_text: str,
    user_id: Optional[int] = None,
    company_id: Optional[int] = None,
    comment_ids: Optional[List[int]] = None,
    types: Optional[List[CommentType]] = None,
    limit: int = 50,
) -> List[Comment]:
    comment_hits = search_comment_hits_semantic(
        db=db,
        query_text=query_text,
        user_id=user_id,
        company_id=company_id,
        comment_ids=comment_ids,
        types=types,
        limit=limit,
    )
    if not comment_hits:
        return []

    ids_in_order = [hit["comment_id"] for hit in comment_hits]
    comments = db.query(Comment).filter(Comment.id.in_(ids_in_order)).all()
    comments_by_id = {comment.id: comment for comment in comments}
    return [comments_by_id[cid] for cid in ids_in_order if cid in comments_by_id]
