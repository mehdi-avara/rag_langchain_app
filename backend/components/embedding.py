import requests
from langchain.embeddings.base import Embeddings
from settings import get_settings

from components.errors import (
    EmbeddingErrorRecord,
    EmbeddingErrorRegistry,
    log_embedding_error,
)
from core.exceptions import AppException
from core.exceptions.error_codes import (
    EMBEDDING_BAD_RESPONSE,
    EMBEDDING_SERVICE_UNAVAILABLE,
    SERVICE_UNAVAILABLE_STATUS_CODE,
)

settings = get_settings()


def embedding_exception_to_app_exception(exc: Exception, context: str) -> AppException:
    error_type = type(exc).__name__
    error_code = EMBEDDING_SERVICE_UNAVAILABLE

    if isinstance(exc, (KeyError, TypeError, ValueError)):
        error_code = EMBEDDING_BAD_RESPONSE

    return AppException(
        status_code=SERVICE_UNAVAILABLE_STATUS_CODE,
        code=error_code,
        message="Embedding service is unavailable" if error_code == EMBEDDING_SERVICE_UNAVAILABLE else "Embedding service returned a bad response",
        details={
            "context": context,
            "error_type": error_type,
        },
    )


def raise_embedding_exception(exc: Exception, context: str):
    raise embedding_exception_to_app_exception(exc, context) from exc


class JinaAPIEmbeddings(Embeddings):
    def __init__(self, fail_soft: bool = False):
        self.api_key = settings.embedding_api_key or settings.jina_api_key
        self.model = settings.embedding_model
        self.api_url = settings.embedding_base_url
        self.task = "text-matching"
        self.fail_soft = fail_soft

    def _log_error(self, exc: Exception, context: str) -> None:
        log_embedding_error(
            EmbeddingErrorRecord(
                error_code=EmbeddingErrorRegistry.EMBEDDING_UNAVAILABLE,
                error_type=type(exc).__name__,
                error_text=str(exc),
                context=context,
            )
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "input": texts}

        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=20)
            response.raise_for_status()
            result = response.json()
            return result["result"]["data"]
        except AppException:
            raise
        except Exception as exc:
            self._log_error(exc, "embed_documents")
            if self.fail_soft:
                return []
            raise_embedding_exception(exc, "embed_documents")

    def embed_query(self, text: str) -> list[float]:
        try:
            embedded = self.embed_documents([text])
            return embedded[0] if embedded else []
        except AppException:
            raise
        except Exception as exc:
            self._log_error(exc, "embed_query")
            if self.fail_soft:
                return []
            raise_embedding_exception(exc, "embed_query")

    @property
    def embedding(self):
        return self
