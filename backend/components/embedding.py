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


def normalize_api_key(value: str | None) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    if value.lower() in ("", "none", "null", "false"):
        return ""
    return value


def normalize_embedding_url(value: str) -> str:
    url = str(value).strip().rstrip("/")
    if url.endswith("/embeddings"):
        return url
    if url.endswith("/v1"):
        return f"{url}/embeddings"
    return url


def extract_embeddings(result) -> list[list[float]]:
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, list):
            if not data:
                return []
            if isinstance(data[0], dict) and "embedding" in data[0]:
                return [item["embedding"] for item in data]
            if isinstance(data[0], list):
                return data

        nested = result.get("result")
        if isinstance(nested, dict):
            nested_data = nested.get("data")
            if isinstance(nested_data, list):
                if not nested_data:
                    return []
                if isinstance(nested_data[0], dict) and "embedding" in nested_data[0]:
                    return [item["embedding"] for item in nested_data]
                if isinstance(nested_data[0], list):
                    return nested_data

        embeddings = result.get("embeddings")
        if isinstance(embeddings, list):
            return embeddings

    raise ValueError("Unsupported embedding response format")


class JinaAPIEmbeddings(Embeddings):
    def __init__(self, fail_soft: bool = False):
        embedding_key = normalize_api_key(settings.embedding_api_key)
        jina_key = normalize_api_key(settings.jina_api_key)

        self.api_key = embedding_key or jina_key
        self.model = settings.embedding_model
        self.api_url = normalize_embedding_url(settings.embedding_base_url)
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
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "input": texts,
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            return extract_embeddings(result)
        except AppException:
            raise
        except Exception as exc:
            self._log_error(exc, "embed_documents")
            if self.fail_soft:
                print("Embedding failed softly:", repr(exc), flush=True)
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
                print("Embedding query failed softly:", repr(exc), flush=True)
                return []
            raise_embedding_exception(exc, "embed_query")

    @property
    def embedding(self):
        return self
