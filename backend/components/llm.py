from typing import List, Optional
from langchain.chat_models import ChatOpenAI
from openai import AsyncOpenAI
from settings import get_settings

settings = get_settings()


class LLMClient:
    """Centralized LLM client for all LLM operations."""
    
    def __init__(self):
        self.settings = get_settings()
        self._langchain_llm = None
        self._async_openai_client = None
    
    @property
    def langchain_llm(self) -> ChatOpenAI:
        """Get LangChain ChatOpenAI instance for answer generation."""
        if self._langchain_llm is None:
            self._langchain_llm = ChatOpenAI(
                base_url=self.settings.openai_base_url,
                model=self.settings.llm_model,
                temperature=self.settings.llm_temperature,
                openai_api_key=self.settings.openai_api_key
            )
        return self._langchain_llm
    
    @property
    def async_openai_client(self) -> AsyncOpenAI:
        """Get AsyncOpenAI client for direct API calls."""
        if self._async_openai_client is None:
            self._async_openai_client = AsyncOpenAI(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url
            )
        return self._async_openai_client
    
    async def rewrite_query(self, query: str) -> str:
        """Use LLM to improve the query for better search performance."""
        response = await self.async_openai_client.chat.completions.create(
            model=self.settings.llm_rewrite_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that improves search queries. Make the query more specific and effective for information retrieval while preserving the original intent."
                },
                {
                    "role": "user",
                    "content": f"Improve this search query: {query}"
                }
            ],
            max_tokens=self.settings.llm_max_tokens,
            temperature=self.settings.llm_rewrite_temperature
        )
        return response.choices[0].message.content
    
    async def extract_keywords(self, query: str) -> List[str]:
        """Use LLM to extract keywords from the query."""
        response = await self.async_openai_client.chat.completions.create(
            model=self.settings.llm_rewrite_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that extracts key terms from queries. Return only the most important keywords or phrases, separated by commas."
                },
                {
                    "role": "user",
                    "content": f"Extract key terms from this query: {query}"
                }
            ],
            max_tokens=100,
            temperature=self.settings.llm_rewrite_temperature
        )
        keywords = response.choices[0].message.content.split(',')
        return [k.strip() for k in keywords if k.strip()]
    
    def get_langchain_llm_with_custom_params(
        self, 
        model: Optional[str] = None, 
        temperature: Optional[float] = None
    ) -> ChatOpenAI:
        """Get LangChain LLM with custom parameters."""
        return ChatOpenAI(
            base_url=self.settings.openai_base_url,
            model=model or self.settings.llm_model,
            temperature=temperature or self.settings.llm_temperature,
            openai_api_key=self.settings.openai_api_key
        )


# Global instance
llm_client = LLMClient()
