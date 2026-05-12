from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
from Models import Chunk, Comment
from components.embedding import JinaAPIEmbeddings
from settings import get_settings


settings = get_settings()


class PostgresVectorStore:
    def __init__(self, db: Session):
        self.db = db
        self.embeddings = JinaAPIEmbeddings()

    def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str]
    ) -> None:
        embeddings_list = self.embeddings.embed_documents(texts)

        for i, (text, metadata, chunk_id) in enumerate(zip(texts, metadatas, ids)):
            chunk = self.db.query(Chunk).filter(Chunk.vdb_id == chunk_id).first()
            if chunk:
                chunk.embedding = embeddings_list[i]

        self.db.commit()

    def delete_by_doc_id(self, doc_id: str) -> None:
        pass

    def similarity_search(
        self,
        query: str,
        k: int = 6,
        doc_ids: Optional[List[int]] = None,
        company_id: Optional[int] = None,
    ) -> List[Tuple[Chunk, float]]:
        query_embedding = self.embeddings.embed_query(query)
        if not query_embedding:
            return []
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

        filters = ["c.embedding IS NOT NULL"]
        params: Dict[str, Any] = {"k": k, "query_vec": embedding_str}
        joins = ["JOIN documents d ON d.id = c.doc_id"]

        if company_id is not None:
            joins.append("JOIN users u ON u.id = d.owner_id")
            filters.append("u.company_id = :company_id")
            params["company_id"] = company_id

        if doc_ids is not None:
            if not doc_ids:
                return []
            placeholders = ", ".join(f":doc_id_{i}" for i in range(len(doc_ids)))
            filters.append(f"c.doc_id IN ({placeholders})")
            for i, did in enumerate(doc_ids):
                params[f"doc_id_{i}"] = did

        where_clause = " AND ".join(filters)
        join_clause = "\n".join(joins)

        sql = text(f"""
            SELECT c.id AS id,
                (1 - (c.embedding <=> (:query_vec)::vector)) AS similarity
            FROM chunks c
            {join_clause}
            WHERE {where_clause}
            ORDER BY similarity DESC
            LIMIT :k
        """)

        rows = self.db.execute(sql, params).fetchall()
        if not rows:
            return []

        ids_in_order = [r.id for r in rows]

        chunks = (
            self.db.query(Chunk)
            .filter(Chunk.id.in_(ids_in_order))
            .all()
        )
        chunks_by_id = {c.id: c for c in chunks}

        return [(chunks_by_id[r.id], r.similarity) for r in rows if r.id in chunks_by_id]

    def similarity_search_comments(
        self,
        query: str,
        k: int = 6,
        comment_ids: Optional[List[int]] = None,
        company_id: Optional[int] = None,
    ) -> List[Tuple[Comment, float]]:
        query_embedding = self.embeddings.embed_query(query)
        if not query_embedding:
            return []
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

        filters = ["c.embedding IS NOT NULL"]
        params: Dict[str, Any] = {
            "k": k,
            "query_vec": embedding_str,
        }
        joins = []

        if company_id is not None:
            joins.append("JOIN users u ON u.id = c.user_id")
            filters.append("u.company_id = :company_id")
            params["company_id"] = company_id

        if comment_ids is not None:
            if not comment_ids:
                return []
            placeholders = ", ".join(f":id_{i}" for i in range(len(comment_ids)))
            filters.append(f"c.id IN ({placeholders})")
            for i, comment_id in enumerate(comment_ids):
                params[f"id_{i}"] = comment_id

        where_clause = " AND ".join(filters)
        join_clause = "\n".join(joins)

        sql = text(f"""
            SELECT c.id AS id,
                (1 - (c.embedding <=> (:query_vec)::vector)) AS similarity
            FROM comments c
            {join_clause}
            WHERE {where_clause}
            ORDER BY similarity DESC
            LIMIT :k
        """)

        rows = self.db.execute(sql, params).fetchall()

        if not rows:
            return []

        ids_in_order = [r.id for r in rows]
        comments = (
            self.db.query(Comment)
            .filter(Comment.id.in_(ids_in_order))
            .all()
        )
        comments_by_id = {c.id: c for c in comments}

        out: List[Tuple[Comment, float]] = []
        for r in rows:
            comment = comments_by_id.get(r.id)
            if comment is not None:
                out.append((comment, r.similarity))

        return out

    def as_retriever(
        self,
        search_kwargs: Optional[Dict[str, Any]] = None,
        doc_ids: Optional[List[int]] = None,
        comment_ids: Optional[List[int]] = None,
        company_id: Optional[int] = None,
    ) -> "PostgresVectorRetriever":
        if search_kwargs is None:
            search_kwargs = {"k": 6}
        return PostgresVectorRetriever(
            vector_store=self,
            search_kwargs=search_kwargs,
            doc_ids=doc_ids,
            comment_ids=comment_ids,
            company_id=company_id,
        )


class PostgresVectorRetriever:
    def __init__(
        self,
        vector_store: PostgresVectorStore,
        search_kwargs: Dict[str, Any],
        doc_ids: Optional[List[int]] = None,
        comment_ids: Optional[List[int]] = None,
        company_id: Optional[int] = None,
        chunk_ids: Optional[List[int]] = None,
    ):
        self.vector_store = vector_store
        self.search_kwargs = search_kwargs
        self.doc_ids = doc_ids
        self.comment_ids = comment_ids
        self.company_id = company_id
        self.chunk_ids = chunk_ids

    def get_relevant_documents(self, query: str) -> List[Chunk]:
        k = self.search_kwargs.get("k", 6)
        results = self.vector_store.similarity_search(
            query=query,
            k=k,
            doc_ids=self.doc_ids,
            company_id=self.company_id,
        )

        chunks = []
        for chunk, similarity in results:
            chunks.append(chunk)
        return chunks

    def get_relevant_comments(self, query: str) -> List[Comment]:
        k = self.search_kwargs.get("k", 6)
        results = self.vector_store.similarity_search_comments(
            query=query,
            k=k,
            comment_ids=self.comment_ids,
            company_id=self.company_id,
        )

        comments = []
        for comment, similarity in results:
            comments.append(comment)
        return comments

    def invoke(self, query: str) -> Dict[str, Any]:
        return {
            "chunks": self.get_relevant_documents(query),
            "comments": self.get_relevant_comments(query),
        }
