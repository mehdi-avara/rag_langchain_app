from typing import Any, List, Optional

from langchain.chat_models import ChatOpenAI
from openai import AsyncOpenAI

from core.exceptions import AppException
from core.exceptions.error_codes import (
    GATEWAY_TIMEOUT_STATUS_CODE,
    LLM_REQUEST_TIMEOUT,
    LLM_SERVICE_UNAVAILABLE,
    SERVICE_UNAVAILABLE_STATUS_CODE,
)
from settings import get_settings

settings = get_settings()


def llm_exception_to_app_exception(exc: Exception, context: str) -> AppException:
    error_text = str(exc).lower()
    error_type = type(exc).__name__
    is_timeout = "timeout" in error_text or "timeout" in error_type.lower()

    if is_timeout:
        return AppException(
            status_code=GATEWAY_TIMEOUT_STATUS_CODE,
            code=LLM_REQUEST_TIMEOUT,
            message="LLM request timed out",
            details={
                "context": context,
                "error_type": error_type,
            },
        )

    return AppException(
        status_code=SERVICE_UNAVAILABLE_STATUS_CODE,
        code=LLM_SERVICE_UNAVAILABLE,
        message="LLM service is unavailable",
        details={
            "context": context,
            "error_type": error_type,
        },
    )


def raise_llm_exception(exc: Exception, context: str):
    raise llm_exception_to_app_exception(exc, context) from exc


class LLMClient:
    def __init__(self):
        self.settings = get_settings()
        self._langchain_llm = None
        self._async_openai_client = None

    @property
    def langchain_llm(self) -> ChatOpenAI:
        if self._langchain_llm is None:
            self._langchain_llm = ChatOpenAI(
                base_url=self.settings.openai_base_url,
                model=self.settings.llm_model,
                temperature=self.settings.llm_temperature,
                openai_api_key=self.settings.openai_api_key,
            )
        return self._langchain_llm

    @property
    def async_openai_client(self) -> AsyncOpenAI:
        if self._async_openai_client is None:
            self._async_openai_client = AsyncOpenAI(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
            )
        return self._async_openai_client

    async def rewrite_query(self, query: str) -> str:
        try:
            response = await self.async_openai_client.chat.completions.create(
                model=self.settings.llm_rewrite_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that improves search queries. Make the query more specific and effective for information retrieval while preserving the original intent.",
                    },
                    {
                        "role": "user",
                        "content": f"Improve this search query: {query}",
                    },
                ],
                max_tokens=self.settings.llm_max_tokens,
                temperature=self.settings.llm_rewrite_temperature,
            )
            return response.choices[0].message.content
        except AppException:
            raise
        except Exception as exc:
            raise_llm_exception(exc, "rewrite_query")

    async def extract_keywords(self, query: str) -> List[str]:
        try:
            response = await self.async_openai_client.chat.completions.create(
                model=self.settings.llm_rewrite_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that extracts key terms from queries. Return only the most important keywords or phrases, separated by commas.",
                    },
                    {
                        "role": "user",
                        "content": f"Extract key terms from this query: {query}",
                    },
                ],
                max_tokens=100,
                temperature=self.settings.llm_rewrite_temperature,
            )
            keywords = response.choices[0].message.content.split(",")
            return [k.strip() for k in keywords if k.strip()]
        except AppException:
            raise
        except Exception as exc:
            raise_llm_exception(exc, "extract_keywords")

    def get_langchain_llm_with_custom_params(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> ChatOpenAI:
        return ChatOpenAI(
            base_url=self.settings.openai_base_url,
            model=model or self.settings.llm_model,
            temperature=temperature or self.settings.llm_temperature,
            openai_api_key=self.settings.openai_api_key,
        )


llm_client = LLMClient()
