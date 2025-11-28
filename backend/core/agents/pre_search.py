from openai import AsyncOpenAI
from typing import List


from settings import get_settings


settings = get_settings()


aclient = AsyncOpenAI(api_key=settings.openai_api_key,base_url=settings.openai_base_url)


async def call_llm_to_rewrite(query: str) -> str:
    """Use LLM to improve the query for better search performance."""
    response = await aclient.chat.completions.create(
        model="gpt-4o",
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
        max_tokens=150
    )
    return response.choices[0].message.content

async def call_llm_to_extract_keywords(query: str) -> List[str]:
    """Use LLM to extract keywords from the query."""
    response = await aclient.chat.completions.create(
        model="gpt-4o",
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
        max_tokens=100
    )
    keywords = response.choices[0].message.content.split(',')
    return [k.strip() for k in keywords if k.strip()]

