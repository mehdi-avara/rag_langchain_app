from typing import List, Dict, Any
from elasticsearch import AsyncElasticsearch
from langchain.retrievers import ElasticsearchBM25Retriever
from ...settings import get_settings

settings = get_settings()

class BM25Retriever:
    def __init__(self, k: int = 6):
        self.es_client = AsyncElasticsearch(settings.elastic_host)
        self.index_name = "chunks"
        self.k = k
        self._retriever = None

    @property
    def retriever(self) -> ElasticsearchBM25Retriever:
        if self._retriever is None:
            self._retriever = ElasticsearchBM25Retriever(
                elasticsearch_url=settings.elastic_host,
                index_name=self.index_name,
                k=self.k
            )
        return self._retriever

    async def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str]
    ) -> None:
        """Add texts to Elasticsearch index."""
        # Create index if it doesn't exist
        if not await self.es_client.indices.exists(index=self.index_name):
            await self.es_client.indices.create(
                index=self.index_name,
                body={
                    "mappings": {
                        "properties": {
                            "content": {"type": "text"},
                            "doc_id": {"type": "integer"},
                            "chunk_id": {"type": "integer"}
                        }
                    }
                }
            )

        # Bulk index documents
        actions = []
        for text, metadata, doc_id in zip(texts, metadatas, ids):
            actions.append({
                "_index": self.index_name,
                "_id": doc_id,
                "_source": {
                    "content": text,
                    **metadata
                }
            })

        if actions:
            await self.es_client.bulk(operations=actions)

    async def invoke(self, query: str) -> List[Dict[str, Any]]:
        """Search documents using BM25."""
        return await self.retriever.ainvoke(query) 