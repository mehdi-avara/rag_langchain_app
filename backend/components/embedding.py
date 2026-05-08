import requests
from langchain.embeddings.base import Embeddings
from settings import get_settings

from components.errors import (
    EmbeddingErrorRecord,
    EmbeddingErrorRegistry,
    log_embedding_error,
)

settings = get_settings()


class JinaAPIEmbeddings(Embeddings):
    def __init__(self):
        self.api_key = settings.embedding_api_key or settings.jina_api_key
        self.model = settings.embedding_model
        self.api_url = settings.embedding_base_url
        self.task = "text-matching"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "input": texts}

        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=20)
            response.raise_for_status()
            result = response.json()
            return result["result"]["data"]
        except Exception as exc:
            log_embedding_error(
                EmbeddingErrorRecord(
                    error_code=EmbeddingErrorRegistry.EMBEDDING_UNAVAILABLE,
                    error_type=type(exc).__name__,
                    error_text=str(exc),
                    context="embed_documents",
                )
            )
            return []

    def embed_query(self, text: str) -> list[float]:
        embedded = self.embed_documents([text])
        return embedded[0] if embedded else []

    @property
    def embedding(self):
        return self
