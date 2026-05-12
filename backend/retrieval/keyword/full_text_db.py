from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from langchain_core.documents import Document
from langchain_core.runnables import Runnable

from Models import Chunk


class FullTextRetrieverFromDB(Runnable):
    def __init__(self, db: Session):
        self.db = db

    async def ainvoke(self, query: str, **kwargs) -> List[Document]:
        doc_id = kwargs.get("doc_id")
        doc_ids: Optional[List[int]] = kwargs.get("doc_ids")
        company_id = kwargs.get("company_id")

        query_builder = self.db.query(Chunk).filter(
            func.to_tsvector("simple", Chunk.content)
            .op("@@")(func.plainto_tsquery("simple", query))
        )

        if company_id is not None:
            from Models import Document as DbDocument, User
            query_builder = (
                query_builder
                .join(DbDocument, DbDocument.id == Chunk.doc_id)
                .join(User, User.id == DbDocument.owner_id)
                .filter(User.company_id == company_id)
            )

        if doc_id is not None:
            query_builder = query_builder.filter(Chunk.doc_id == doc_id)

        if doc_ids is not None:
            if not doc_ids:
                return []
            query_builder = query_builder.filter(Chunk.doc_id.in_(doc_ids))

        results = query_builder.all()

        return [
            Document(
                page_content=chunk.content,
                metadata={
                    "id": chunk.id,
                    "doc_id": chunk.doc_id,
                    "page_num": chunk.page_num,
                    "chunk_type": chunk.chunk_type,
                    "vdb_id": chunk.vdb_id,
                    "created_at": chunk.created_at.isoformat(),
                }
            )
            for chunk in results
        ]

    def invoke(self, query: str):
        raise NotImplementedError("Use ainvoke(query) asynchronously.")
