from sqlalchemy.orm import Session
from db.models import Document, Chunk
from settings import get_settings
from components.llm import llm_client

settings = get_settings()

async def summarise_document(doc_id: int, db: Session, max_words: int = 120) -> str:
    """Generate a concise summary of the document using GPT-4."""
    # Get all chunks for the document
    chunks = db.query(Chunk).filter(Chunk.doc_id == doc_id).order_by(Chunk.page_num).all()
    if not chunks:
        return ""
    
    # Combine chunks into a single text
    full_text = "\n".join(chunk.content for chunk in chunks)
    
    # Build messages and call AsyncOpenAI directly
    system_prompt = (
        "You are a helpful assistant that writes concise summaries. "
        "Respect the word limit and do not add extra commentary."
    )
    user_prompt = (
        f"Please provide a concise summary of the following text in {max_words} words or less:\n\n"
        f"{full_text}\n\nSummary:"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    response = await llm_client.async_openai_client.chat.completions.create(
        model=llm_client.settings.llm_model,
        temperature=0,
        max_tokens=llm_client.settings.llm_max_tokens,
        messages=messages
    )
    return response.choices[0].message.content.strip()