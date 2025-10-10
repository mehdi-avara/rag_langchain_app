from sqlalchemy.orm import Session
from openai import AsyncOpenAI
from langchain.prompts import ChatPromptTemplate
from db.models import Document, Chunk
from settings import get_settings

settings = get_settings()

async def summarise_document(doc_id: int, db: Session, max_words: int = 120) -> str:
    """Generate a concise summary of the document using GPT-4."""
    # Get all chunks for the document
    chunks = db.query(Chunk).filter(Chunk.doc_id == doc_id).order_by(Chunk.page_num).all()
    if not chunks:
        return ""
    
    # Combine chunks into a single text
    full_text = "\n".join(chunk.content for chunk in chunks)
    
    # Create prompt template
    template = """Please provide a concise summary of the following text in {max_words} words or less:

{text}

Summary:"""
    
    prompt = ChatPromptTemplate.from_template(template)
    
    # Initialize LLM
    llm = AsyncOpenAI(
        model="gemma3:27b",
        temperature=0,
        openai_api_key=settings.openai_api_key,
        base_url=settings.openai_base_url
        
    )
    
    # Generate summary
    chain = prompt | llm
    result = await chain.ainvoke({
        "text": full_text,
        "max_words": max_words
    })
    
    return result.content.strip() 