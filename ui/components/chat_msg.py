import streamlit as st
import requests
from typing import List, Dict, Any, Optional
import os
import re
import markdown

from settigs import get_settings
from components.auth import get_token
from components.chunk import render_simple_chunk_content
settings = get_settings()
API_URL = settings.API_URL

def render_message(
    role: str,
    content: str,
    retrieved_chunks: List[Dict] = None,
    message_id: int = 0,
) -> None:
    """Render a chat message with optional citations and retrieved chunks."""
    with st.chat_message(role):
        if role == "assistant":
            # Render answer with clickable citations
            render_answer_with_citations(content)
            
            # Display retrieved chunks if available
            if retrieved_chunks:
                render_retrieved_chunks(retrieved_chunks, message_id)
        else:
            st.write(content)

def render_answer_with_citations(content: str):
    """Render answer text with clickable citations that show previews on hover."""
    st.write(content)
    
def show_citation_preview(chunk_id: int, token: str):
    """Show a preview of the citation content."""
    try:
        response = requests.get(
            f"{API_URL}/documents/chunks/{chunk_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        chunk = response.json()
        
        # Create a highlighted section for the citation
        st.markdown("---")
        st.markdown(f"### 📄 Citation {chunk_id} Preview")
        
        # Show metadata first
        col1, col2 = st.columns(2)
        with col1:
            st.caption(f"**Chunk ID:** {chunk_id}")
        with col2:
            if chunk.get("doc_id"):
                st.caption(f"**Document ID:** {chunk['doc_id']}")
        
        # Render markdown content
        render_markdown_content(chunk.get("content", ""))
        
                
    except requests.exceptions.RequestException:
        st.error(f"Failed to fetch citation {chunk_id}")

def fetch_document_data(doc_id: int):
    """Fetch document data from backend and return content and filename."""
    try:
        token = get_token()
        response = requests.get(
            f"{API_URL}/documents/download/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
            stream=True
        )
        response.raise_for_status()
        
        # Get filename from content-disposition header or use default
        filename = f"document_{doc_id}.pdf"
        if 'content-disposition' in response.headers:
            content_disposition = response.headers['content-disposition']
            if 'filename=' in content_disposition:
                filename = content_disposition.split('filename=')[1].strip('"')
        
        return response.content, filename
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Failed to fetch document {doc_id}: {str(e)}")
        return None, None

def download_document_button(doc_id: int, row_index: int, message_id: int = 0, doc_data: bytes = None, filename: str = None):
    """Render a download button for a document."""
    if doc_data and filename:
        # Data is already available, show download button
        st.download_button(
            label="⬇️",
            data=doc_data,
            file_name=filename,
            mime="application/pdf",
            key=f"download_doc_{message_id}_{doc_id}_{row_index}",
            help=f"Download {filename}"
        )
    else:
        # Show a disabled button or loading state
        st.button("⬇️", key=f"download_doc_{message_id}_{doc_id}_{row_index}", disabled=True, help="Document not available")

def render_retrieved_chunks(retrieved_chunks: List[Dict], message_id: int = 0):
    """Render the retrieved chunks section with expandable content."""
    st.markdown("---")
    st.subheader("📚 Retrieved Sources")
    
    # Pre-fetch unique document data for all chunks
    unique_doc_ids = set()
    for chunk in retrieved_chunks:
        doc_id = chunk.get("doc_id", "Unknown")
        if doc_id != "Unknown":
            unique_doc_ids.add(doc_id)
    
    # Fetch documents if not already cached
    doc_cache = {}
    with st.spinner("Loading documents..."):
        for doc_id in unique_doc_ids:
            cache_key = f"doc_cache_{doc_id}"
            if cache_key not in st.session_state:
                doc_data, filename = fetch_document_data(doc_id)
                if doc_data:
                    st.session_state[cache_key] = {
                        "data": doc_data,
                        "filename": filename
                    }
            
            # Get from cache
            if cache_key in st.session_state:
                doc_cache[doc_id] = st.session_state[cache_key]
    
    # Render chunks with download buttons
    for i, chunk in enumerate(retrieved_chunks):
        chunk_id = chunk.get("chunk_id", f"unknown_{i}")
        doc_id = chunk.get("doc_id", "Unknown")
        
        # Create expandable section for each chunk
        with st.expander(f"📄 Source {i+1} (Chunk ID: {chunk_id}, Doc: {doc_id})", expanded=False):
            render_simple_chunk_content(chunk_id, doc_id)
            
            # Show chunk metadata and download button
            st.markdown("---")
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.caption(f"**Chunk ID:** {chunk_id}")
            with col2:
                st.caption(f"**Document ID:** {doc_id}")
            with col3:
                # Add download button with pre-fetched data
                if doc_id != "Unknown" and doc_id in doc_cache:
                    download_document_button(
                        doc_id, 
                        i,
                        message_id,
                        doc_cache[doc_id]["data"],
                        doc_cache[doc_id]["filename"]
                    )
                elif doc_id != "Unknown":
                    download_document_button(doc_id, i, message_id)

def render_markdown_content(content: str):
    """Render markdown content with proper formatting."""
    if not content:
        st.write("No content available")
        return
    
    # Configure markdown with extensions
    md = markdown.Markdown(
        extensions=[
            'codehilite',
            'fenced_code',
            'tables',
            'toc'
        ],
        extension_configs={
            'codehilite': {
                'css_class': 'highlight',
                'use_pygments': False
            }
        }
    )
    
    # Convert markdown to HTML
    html_content = md.convert(content)
    
    # Display the HTML content
    st.markdown(html_content, unsafe_allow_html=True) 