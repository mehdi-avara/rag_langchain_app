import io
import base64
from typing import List, Tuple, Dict
import pytesseract
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTImage, LTTextBox
from pdf2image import convert_from_bytes
from PIL import Image
from sqlalchemy.orm import Session
from openai import AsyncOpenAI

import arabic_reshaper
from bidi.algorithm import get_display

from settings import get_settings
from db.models import Document, Chunk, ImageChunk
from retrieval.vector.chroma_store import ChromaStore
from retrieval.keyword.es_bm25 import get_bm25_retriever
from core.chunking import ChunkingMode, chunk_text

settings = get_settings()
aclient = AsyncOpenAI(api_key=settings.openai_api_key)

async def generate_image_caption(image: Image.Image) -> str:
    """Generate caption for image using GPT-4 Vision."""
    # Convert image to base64
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr = img_byte_arr.getvalue()
    img_base64 = base64.b64encode(img_byte_arr).decode()

    # Call GPT-o4 Vision API
    response = await aclient.chat.completions.create(model="gpt-4o",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Please describe this image in detail, focusing on its content, context, and any visible text. Be specific and thorough. Include any written text in persian exactly as it appears in the image."
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_base64}"
                    }
                }
            ]
        }
    ],
    max_tokens=300)

    return response.choices[0].message.content

async def detect_type(file_bytes: bytes) -> str:
    """Detect if file is PDF or image."""
    if file_bytes.startswith(b'%PDF'):
        return 'pdf'
    return 'image'

async def extract_text_and_images_from_pdf(file_bytes: bytes) -> Tuple[str, int, List[Dict]]:
    """Extract text and images from PDF and return (text, page_count, images_info)."""
    text = ""
    images_info = []
    current_pos = 0

    extracted_fields = {
        "product_name": None,
        "company": None,
        "product_type": None,
        "usage": None,
        "content_summary": None
    }

    async def extract_summary_info(text: str) -> Dict[str, str]:
        """Call LLM to extract structured info from text."""
        response = await aclient.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": f"""You are a smart assistant. Extract the following information from this text:
1. Product name
2. Company that made it
3. What product it is?
4. Where is it used?
5. What data is in this file

Only provide the values. If a value is missing, write 'Unknown'.

Text:
{text}"""
                }
            ],
            max_tokens=300
        )
        content = response.choices[0].message.content
        fields = content.strip().split('\n')
        result = {}
        for field in fields:
            if ':' in field:
                key, value = field.split(':', 1)
                result[key.strip().lower().replace(' ', '_')] = value.strip()
        return result

    for page_num, page_layout in enumerate(extract_pages(io.BytesIO(file_bytes))):
        if page_num >= 5:
            break
        page_text = ""
        for element in page_layout:
            if isinstance(element, LTTextBox):
                element_text = element.get_text()
                # Clean and fix Persian text
                element_text = get_display(arabic_reshaper.reshape(element_text))
                # Skip reshaping if libraries are not available
                page_text += element_text
                text += element_text
            elif isinstance(element, LTImage):
                # Convert PDF page to image
                pdf_images = convert_from_bytes(file_bytes, first_page=page_num+1, last_page=page_num+1)
                if pdf_images:
                    # Get image position
                    x0, y0, x1, y1 = element.bbox
                    position = "center"
                    if x0 < page_layout.width * 0.3:
                        position = "left"
                    elif x0 > page_layout.width * 0.7:
                        position = "right"
                    if y0 < page_layout.height * 0.3:
                        position = f"top-{position}"
                    elif y0 > page_layout.height * 0.7:
                        position = f"bottom-{position}"

                    # Convert image to base64
                    img_byte_arr = io.BytesIO()
                    pdf_images[0].save(img_byte_arr, format='PNG')
                    img_byte_arr = img_byte_arr.getvalue()
                    img_base64 = base64.b64encode(img_byte_arr).decode()

                    # Generate caption 
                    caption = await generate_image_caption(pdf_images[0])

                    images_info.append({
                        'page_num': page_num,
                        'position': position,
                        'image_data': img_base64,
                        'caption': caption
                    })
        if page_num < 5 and any(value is None for value in extracted_fields.values()):
            summary_info = await extract_summary_info(page_text)
            for key, val in summary_info.items():
                if extracted_fields.get(key) is None and val != 'Unknown':
                    extracted_fields[key] = val

    page_count = sum(1 for _ in extract_pages(io.BytesIO(file_bytes)))
    # Append extracted metadata
    return text, page_count, images_info

async def extract_text_from_image(file_bytes: bytes) -> Tuple[str, int, List[Dict]]:
    """Extract text from image using OCR and generate caption."""
    image = Image.open(io.BytesIO(file_bytes))
    text = pytesseract.image_to_string(image)

    caption = await generate_image_caption(image)

    # Convert image to base64
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr = img_byte_arr.getvalue()
    img_base64 = base64.b64encode(img_byte_arr).decode()

    images_info = [{
        'page_num': 0,
        'position': 'center',
        'image_data': img_base64,
        'caption': caption
    }]

    return text, 1, images_info


async def ingest_file(file_bytes: bytes, filename: str, user_id: int, db: Session, chunking_mode: ChunkingMode = ChunkingMode.sentence_3) -> int:
    """Main ingestion pipeline."""
    # Detect file type and extract text/images
    file_type = await detect_type(file_bytes)
    if file_type == 'pdf':
        text, n_pages, images_info = await extract_text_and_images_from_pdf(file_bytes)
    else:
        text, n_pages, images_info = await extract_text_from_image(file_bytes)

    # Split into chunks using specified mode
    chunks = chunk_text(text, chunking_mode)

    # Create document record
    doc = Document(
        owner_id=user_id,
        filename=filename,
        n_pages=n_pages,
        n_chunks=len(chunks) + len(images_info),
    )
    db.add(doc)
    db.flush()

    # Create chunk records
    chunk_records = []
    if len(chunks) > 0 and n_pages > 0:
        approx_chunks_per_page = max(1, len(chunks) // n_pages)
    else:
        approx_chunks_per_page = 1

    current_pos = 0
    # Add text chunks
    for i, chunk in enumerate(chunks):
        start_pos = text.find(chunk, current_pos)
        end_pos = start_pos + len(chunk)
        current_pos = end_pos

        holder = Chunk(
            doc_id=doc.id,
            page_num=i // (approx_chunks_per_page),  # Approximate page number
            token_count=len(chunk.split()),
            content=chunk,
            start_pos=start_pos,
            end_pos=end_pos,
            chunk_type="text"
        )
        chunk_records.append(holder)

    # Add image chunks
    for img_info in images_info:
        chunk = Chunk(
            doc_id=doc.id,
            page_num=img_info['page_num'],
            token_count=len(img_info['caption'].split()),
            content=img_info['caption'],
            chunk_type="image"
        )
        db.add(chunk)
        db.flush()  # Get chunk.id

        chunk_records.append(chunk)

        # Create image chunk record
        image_chunk = ImageChunk(
            chunk_id=chunk.id,
            image_data=img_info['image_data'],
            caption=img_info['caption'],
            position=img_info['position']
        )
        db.add(image_chunk)

    db.bulk_save_objects(chunk_records)
    db.flush()

    # Update chunk IDs
    for i, chunk in enumerate(chunk_records):
        chunk.vdb_id = f"{doc.id}_{i}"
        chunk.es_id = f"{doc.id}_{i}"

    db.flush()

    # Store in Chroma
    chroma_store = ChromaStore()
    chroma_store.add_texts(
        texts=[c.content for c in chunk_records],
        metadatas=[{
            "doc_id": doc.id,
            "chunk_id": c.id,
            "page_num": c.page_num,
            "chunk_type": c.chunk_type,
            "position": c.start_pos if c.chunk_type == "text" else None
        } for c in chunk_records],
        ids=[c.vdb_id for c in chunk_records]
    )
    chroma_store.store.persist()

    # Store in Elasticsearch
    bm25 = get_bm25_retriever()
    await bm25.add_texts(
        texts=[c.content for c in chunk_records],
        metadatas=[{
            "doc_id": doc.id,
            "chunk_id": c.id,
            "page_num": c.page_num,
            "chunk_type": c.chunk_type,
            "position": c.start_pos if c.chunk_type == "text" else None
        } for c in chunk_records],
        ids=[c.es_id for c in chunk_records]
    )
    bm25.save()

    db.commit()
    return doc.id 
