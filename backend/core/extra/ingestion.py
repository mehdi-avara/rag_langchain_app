# import io
# import base64
# from typing import List, Tuple, Dict
# from pdf2image import convert_from_bytes
# from PIL import Image
# from sqlalchemy.orm import Session
# from openai import AsyncOpenAI



# from settings import get_settings
# from Models import Document, Chunk
# from core.chunking import ChunkingMode, chunk_text
# from retrieval.vector.chroma_store import ChromaStore


# settings = get_settings()
# aclient = AsyncOpenAI(api_key=settings.openai_api_key)

# async def generate_image_caption(image: Image.Image) -> str:
#     """Generate caption for image using GPT-4 Vision."""
#     # Convert image to base64
#     img_byte_arr = io.BytesIO()
#     image.save(img_byte_arr, format='PNG')
#     img_byte_arr = img_byte_arr.getvalue()
#     img_base64 = base64.b64encode(img_byte_arr).decode()

#     # Call GPT-o4 Vision API
#     response = await aclient.chat.completions.create(model="gpt-4o",
#     messages=[
#         {
#             "role": "user",
#             "content": [
#                 {
#                     "type": "text",
#                     "text": """Describe this image in detail, focusing on its content, context, and any visible text. Be specific and thorough."""
#                 },
#                 {
#                     "type": "image_url",
#                     "image_url": {
#                         "url": f"data:image/png;base64,{img_base64}"
#                     }
#                 }
#             ]
#         }
#     ],
#     max_tokens=400)

#     return response.choices[0].message.content

# async def generate_image_persian_text(image: Image.Image) -> str:
#     """Generate caption for image using GPT-4 Vision."""
#     # Convert image to base64
#     img_byte_arr = io.BytesIO()
#     image.save(img_byte_arr, format='PNG')
#     img_byte_arr = img_byte_arr.getvalue()
#     img_base64 = base64.b64encode(img_byte_arr).decode()

#     # Call GPT-o4 Vision API
#     response = await aclient.chat.completions.create(model="gpt-4o",
#     messages=[
#         {
#             "role": "user",
#             "content": [
#                 {
#                     "type": "text",
#                     "text": """Extract and transcribe all Persian (Farsi) text visible in the image. Ignore any non-Persian text. Maintain the reading order as it appears visually, from top to bottom and left to right."""
#                 },
#                 {
#                     "type": "image_url",
#                     "image_url": {
#                         "url": f"data:image/png;base64,{img_base64}"
#                     }
#                 }
#             ]
#         }
#     ],
#     max_tokens=800)

#     return response.choices[0].message.content


# async def extract_text_from_image(file_bytes: bytes) -> Tuple[str, int, List[Dict]]:
#     """Extract text from image using OCR and generate caption."""
#     image = Image.open(io.BytesIO(file_bytes))

#     caption = await generate_image_caption(image)
#     caption2 = await generate_image_persian_text(image)


#     return f"{caption} {caption2}"


# async def ingest_pdf_as_single_document(file_bytes: bytes, filename: str, user_id: int, db: Session, chunking_mode: ChunkingMode = ChunkingMode.token_fixed) -> int:
#     """Ingest a PDF as a single document, processing all pages together."""

#     # Convert PDF to images
#     images = convert_from_bytes(file_bytes)
#     if not images:
#         raise ValueError("No pages found in PDF")
    
#     # Create a single document for all pages
#     doc = Document(
#         owner_id=user_id,
#         filename=filename,
#         n_pages=len(images),
#         n_chunks=0,  # Will be updated after processing
#     )
#     db.add(doc)
#     db.flush()
#     chunks_count = 0
            
#     # Create chunk records
#     # Process each page
#     for i, image in enumerate(images):

#         # Convert image to bytes
#         img_byte_arr = io.BytesIO()
#         image.save(img_byte_arr, format='PNG')
#         img_byte_arr = img_byte_arr.getvalue()
        
#         # Extract text and image info from this page
#         caption = await extract_text_from_image(img_byte_arr)

#         chunks = chunk_text(caption, chunking_mode)
#         if not chunks:
#             raise ValueError("No chunks could be created from the text")
#         chunks_count += len(chunks)
#         doc.n_chunks = chunks_count
#         texts, metadatas, ids = [], [], []
#         for j,chunck in enumerate(chunks):
#             holder = Chunk(
#                 doc_id=doc.id,
#                 page_num=i, 
#                 token_count=len(chunck.split()),
#                 start_pos=j,
#                 content=chunck,
#                 chunk_type="text"
#             )
#             texts.append(chunck)
#             metadatas.append({
#                 "doc_id": doc.id,
#                 "page_num": i,
#                 "token_count": len(chunck.split()),
#                 "chunk_type": "text",
#             })
#             ids.append(f"{doc.id},{i},{j}")
            
#             db.add_all([holder])
#             db.commit()
#             print(f"Added chunk {j+1}/{len(chunks)} for page {i+1}/{len(images)}")
        
#     batch_size = 700
#     for i in range(0, len(texts), batch_size):
#         chroma_store.add_texts(
#             texts=texts[i:i+batch_size],
#             metadatas=metadatas[i:i+batch_size],
#             ids=ids[i:i+batch_size]
#         )
        
    
#     # Update document with total chunk count

#     # # Add all chunks to database
#     # db.add_all(chunk_records)
#     # db.commit()
    
#     return doc.id
