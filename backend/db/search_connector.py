from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from Models import Chunk, Comment, Document
from components.embedding import JinaAPIEmbeddings
from settings import get_settings


settings = get_settings()


def _embedding_client() -> JinaAPIEmbeddings:
    return JinaAPIEmbeddings(api_key=settings.jina_api_key)


def _attach_document_tag_ids(db: Session, documents: List[Document], tag_scope_ids: Optional[List[int]] = None) -> None:
    if not documents:
        return

    doc_ids = [doc.id for doc in documents]
    sql = text(
        """
        SELECT document_id, tag_id
        FROM tag_document_links
        WHERE document_id = ANY(:doc_ids)
        """
    )
    rows = db.execute(sql, {"doc_ids": doc_ids}).fetchall()

    tags_by_doc: Dict[int, List[int]] = {doc_id: [] for doc_id in doc_ids}
    scope = set(tag_scope_ids or [])
    for row in rows:
        if not scope or row.tag_id in scope:
            tags_by_doc.setdefault(row.document_id, []).append(row.tag_id)

    for doc in documents:
        setattr(doc, "tag_ids", sorted(set(tags_by_doc.get(doc.id, []))))


def _attach_comment_tag_ids(db: Session, comments: List[Comment], tag_scope_ids: Optional[List[int]] = None) -> None:
    if not comments:
        return

    comment_ids = [comment.id for comment in comments]
    sql = text(
        """
        SELECT comment_id, tag_id
        FROM tag_comment_links
        WHERE comment_id = ANY(:comment_ids)
        """
    )
    rows = db.execute(sql, {"comment_ids": comment_ids}).fetchall()

    tags_by_comment: Dict[int, List[int]] = {comment_id: [] for comment_id in comment_ids}
    scope = set(tag_scope_ids or [])
    for row in rows:
        if not scope or row.tag_id in scope:
            tags_by_comment.setdefault(row.comment_id, []).append(row.tag_id)

    for comment in comments:
        setattr(comment, "tag_ids", sorted(set(tags_by_comment.get(comment.id, []))))


def search_documents_text(
    db: Session,
    query_text: str,
    owner_id: int,
    doc_ids: Optional[List[int]] = None,
    limit: int = 50,
    tag_scope_ids: Optional[List[int]] = None,
) -> List[Document]:
    pattern = f"%{query_text}%"
    chunk_match = (
        db.query(Chunk.id)
        .filter(Chunk.doc_id == Document.id, Chunk.content.ilike(pattern))
        .exists()
    )

    query = db.query(Document).filter(Document.owner_id == owner_id)
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
    docs = query.order_by(Document.created_at.desc()).limit(limit).all()
    _attach_document_tag_ids(db, docs, tag_scope_ids)
    return docs


def search_comments_text(
    db: Session,
    query_text: str,
    user_id: int,
    comment_ids: Optional[List[int]] = None,
    limit: int = 50,
    tag_scope_ids: Optional[List[int]] = None,
) -> List[Comment]:
    pattern = f"%{query_text}%"

    query = db.query(Comment).filter(Comment.user_id == user_id)
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
    comments = query.order_by(Comment.created_at.desc()).limit(limit).all()
    _attach_comment_tag_ids(db, comments, tag_scope_ids)
    return comments


def search_documents_semantic(
    db: Session,
    query_text: str,
    owner_id: int,
    doc_ids: Optional[List[int]] = None,
    limit: int = 50,
    min_similarity: float = 0.5,
    tag_scope_ids: Optional[List[int]] = None,
) -> List[Document]:
    query_embedding = _embedding_client().embed_query(query_text)
    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

    filters = ["d.owner_id = :owner_id", "c.embedding IS NOT NULL"]
    params: Dict[str, Any] = {
        "owner_id": owner_id,
        "query_vec": embedding_str,
        "limit": limit,
        "min_similarity": min_similarity,
    }

    if doc_ids is not None:
        if not doc_ids:
            return []
        placeholders = ", ".join(f":doc_id_{i}" for i in range(len(doc_ids)))
        filters.append(f"d.id IN ({placeholders})")
        for i, doc_id in enumerate(doc_ids):
            params[f"doc_id_{i}"] = doc_id

    where_clause = " AND ".join(filters)
    sql = text(
        f"""
        WITH ranked AS (
            SELECT
                d.id AS doc_id,
                c.id AS chunk_id,
                c.content AS chunk_content,
                (1 - (c.embedding <=> (:query_vec)::vector)) AS similarity,
                ROW_NUMBER() OVER (
                    PARTITION BY d.id
                    ORDER BY (1 - (c.embedding <=> (:query_vec)::vector)) DESC
                ) AS rn
            FROM documents d
            JOIN chunks c ON c.doc_id = d.id
            WHERE {where_clause}
        )
        SELECT doc_id, chunk_id, chunk_content, similarity
        FROM ranked
        WHERE rn = 1 AND similarity >= :min_similarity
        ORDER BY similarity DESC
        LIMIT :limit
        """
    )

    rows = db.execute(sql, params).fetchall()
    if not rows:
        return []

    ids_in_order = [row.doc_id for row in rows]
    docs = db.query(Document).filter(Document.id.in_(ids_in_order)).all()
    docs_by_id = {doc.id: doc for doc in docs}

    ordered_docs: List[Document] = []
    for row in rows:
        doc = docs_by_id.get(row.doc_id)
        if not doc:
            continue
        setattr(doc, "part_id", row.chunk_id)
        setattr(doc, "part_text", row.chunk_content)
        setattr(doc, "similarity", float(row.similarity))
        ordered_docs.append(doc)

    _attach_document_tag_ids(db, ordered_docs, tag_scope_ids)
    return ordered_docs


def search_comments_semantic(
    db: Session,
    query_text: str,
    user_id: int,
    comment_ids: Optional[List[int]] = None,
    limit: int = 50,
    comment_type: Optional[str] = None,
    min_similarity: float = 0.5,
    tag_scope_ids: Optional[List[int]] = None,
) -> List[Comment]:
    query_embedding = _embedding_client().embed_query(query_text)
    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

    filters = ["c.user_id = :user_id", "c.embedding IS NOT NULL"]
    params: Dict[str, Any] = {
        "user_id": user_id,
        "query_vec": embedding_str,
        "limit": limit,
        "min_similarity": min_similarity,
    }

    if comment_type:
        filters.append("c.type = :comment_type")
        params["comment_type"] = comment_type

    if comment_ids is not None:
        if not comment_ids:
            return []
        placeholders = ", ".join(f":comment_id_{i}" for i in range(len(comment_ids)))
        filters.append(f"c.id IN ({placeholders})")
        for i, comment_id in enumerate(comment_ids):
            params[f"comment_id_{i}"] = comment_id

    where_clause = " AND ".join(filters)
    sql = text(
        f"""
        SELECT
            c.id AS id,
            c.content AS content,
            (1 - (c.embedding <=> (:query_vec)::vector)) AS similarity
        FROM comments c
        WHERE {where_clause}
        AND (1 - (c.embedding <=> (:query_vec)::vector)) >= :min_similarity
        ORDER BY similarity DESC
        LIMIT :limit
        """
    )

    rows = db.execute(sql, params).fetchall()
    if not rows:
        return []

    ids_in_order = [row.id for row in rows]
    comments = db.query(Comment).filter(Comment.id.in_(ids_in_order)).all()
    comments_by_id = {comment.id: comment for comment in comments}

    ordered_comments: List[Comment] = []
    for row in rows:
        comment = comments_by_id.get(row.id)
        if not comment:
            continue
        setattr(comment, "part_id", row.id)
        setattr(comment, "part_text", row.content)
        setattr(comment, "similarity", float(row.similarity))
        ordered_comments.append(comment)

    _attach_comment_tag_ids(db, ordered_comments, tag_scope_ids)
    return ordered_comments
