import io
from typing import List, Tuple
import pytesseract
from pdfminer.high_level import extract_text
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
from PIL import Image
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import HuggingFaceEmbeddings
from sqlalchemy.orm import Session

from db.models import Document, Chunk
from settings import get_settings
from retrieval.vector.chroma_store import ChromaStore
from retrieval.keyword.es_bm25 import BM25Retriever

settings = get_settings()

async def detect_type(file_bytes: bytes) -> str:
    """Detect if file is PDF or image."""
    if file_bytes.startswith(b'%PDF'):
        return 'pdf'
    return 'image'

async def extract_text_from_pdf(file_bytes: bytes) -> Tuple[str, int]:
    """Extract text from PDF and return (text, page_count)."""
    parser = PDFParser(io.BytesIO(file_bytes))
    doc = PDFDocument(parser)
    text = extract_text(io.BytesIO(file_bytes))
    return text, len(doc.get_pages())

async def extract_text_from_image(file_bytes: bytes) -> Tuple[str, int]:
    """Extract text from image using OCR."""
    image = Image.open(io.BytesIO(file_bytes))
    text = pytesseract.image_to_string(image)
    return text, 1

async def extract_images_from_pdf(file_bytes: bytes) -> List[Image.Image]:
    """Extract images from PDF pages."""
    # Implementation depends on specific PDF library
    # This is a placeholder
    return []

async def caption_images(images: List[Image.Image]) -> List[str]:
    """Generate captions for images using GPT-4."""
    # Implementation using OpenAI API
    # This is a placeholder
    return []

def add_captions_to_text(text: str, captions: List[str]) -> str:
    """Add image captions to the text."""
    for i, caption in enumerate(captions, 1):
        text += f"\n\nFigure {i}: {caption}"
    return text

async def ingest_file(file_bytes: bytes, filename: str, user_id: int, db: Session) -> int:
    """Main ingestion pipeline."""
    # Detect file type and extract text
    file_type = await detect_type(file_bytes)
    if file_type == 'pdf':
        text, n_pages = await extract_text_from_pdf(file_bytes)
        images = await extract_images_from_pdf(file_bytes)
    else:
        text, n_pages = await extract_text_from_image(file_bytes)
        images = [Image.open(io.BytesIO(file_bytes))]

    # Generate image captions
    captions = await caption_images(images)
    text = add_captions_to_text(text, captions)

    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=50,
        length_function=len,
    )
    chunks = splitter.split_text(text)

    # Create document record
    doc = Document(
        owner_id=user_id,
        filename=filename,
        n_pages=n_pages,
        n_chunks=len(chunks),
    )
    db.add(doc)
    db.flush()  # Get doc.id

    # Create chunk records
    chunk_records = []
    for i, chunk_text in enumerate(chunks):
        chunk = Chunk(
            doc_id=doc.id,
            page_num=i // (len(chunks) // n_pages),  # Approximate page number
            token_count=len(chunk_text.split()),
            content=chunk_text,
        )
        chunk_records.append(chunk)
    db.bulk_save_objects(chunk_records)
    db.flush()

    # Generate embeddings and store in vector DB
    embeddings = HuggingFaceEmbeddings(
        model_name="jinaai/jina-embeddings-v3",
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': True}
    )
    
    # Store in Chroma
    chroma_store = ChromaStore()
    await chroma_store.add_texts(
        texts=[c.content for c in chunk_records],
        metadatas=[{"doc_id": doc.id, "chunk_id": c.id} for c in chunk_records],
        ids=[c.vdb_id for c in chunk_records]
    )

    # Store in Elasticsearch
    es_retriever = BM25Retriever()
    await es_retriever.add_texts(
        texts=[c.content for c in chunk_records],
        metadatas=[{"doc_id": doc.id, "chunk_id": c.id} for c in chunk_records],
        ids=[c.es_id for c in chunk_records]
    )

    db.commit()
    return doc.id 