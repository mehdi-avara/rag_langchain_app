import streamlit as st
import requests
from typing import List, Dict, Any, Optional
import os
import re
import markdown

from settigs import get_settings
from components.auth import get_token
from components.chunk import render_simple_chunk_content, fetch_adjacent_chunks, fetch_chunk, render_chunk_markdown
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

def download_document_button(doc_id: int, row_index: int, message_id: int = 0):
    """
    Render a download button for a document that fetches on-demand.
    
    Behavior:
    - First click: Fetches document and reloads page (happens once)
    - After cache: Direct download without reload
    """
    cache_key = f"doc_cache_{doc_id}"
    
    # Check if document is already cached
    if cache_key in st.session_state:
        # Document is cached - show download button
        # Clicking this will NOT cause a page reload
        doc_info = st.session_state[cache_key]
        st.download_button(
            label="📥",
            data=doc_info["data"],
            file_name=doc_info["filename"],
            mime="application/pdf",
            key=f"dl_{message_id}_{doc_id}_{row_index}",
            help=f"📄 {doc_info['filename']}"
        )
    else:
        # Document not cached - show fetch button
        # Clicking this WILL cause one reload to cache the document
        if st.button(
            "📥", 
            key=f"fetch_{message_id}_{doc_id}_{row_index}", 
            help="⚠️ First click will load document"
        ):
            with st.spinner(f"Fetching document {doc_id}..."):
                doc_data, filename = fetch_document_data(doc_id)
                if doc_data and filename:
                    st.session_state[cache_key] = {
                        "data": doc_data,
                        "filename": filename
                    }
                    # Rerun to show the download button
                    st.rerun()
                else:
                    st.error("❌ Failed to load document")

def render_retrieved_chunks(retrieved_chunks: List[Dict], message_id: int = 0):
    """Render the retrieved chunks section with expandable content."""
    st.markdown("---")
    st.subheader("📚 Retrieved Sources")
    
    # Render chunks with download buttons and navigation
    for i, chunk in enumerate(retrieved_chunks):
        chunk_id = chunk.get("chunk_id", f"unknown_{i}")
        doc_id = chunk.get("doc_id", "Unknown")
        content = chunk.get("content", "")
        
        # Initialize session state for this chunk's current view
        state_key = f"chat_chunk_{message_id}_{i}_current"
        if state_key not in st.session_state:
            st.session_state[state_key] = chunk_id
        
        current_viewing_chunk_id = st.session_state[state_key]
        
        # Create expandable section for each chunk
        with st.expander(f"📄 Source {i+1} (Chunk ID: {current_viewing_chunk_id}, Doc: {doc_id})", expanded=False):
            # Get adjacent chunk IDs
            token = get_token()
            prev_chunk_id, next_chunk_id = fetch_adjacent_chunks(doc_id, current_viewing_chunk_id, token) if token and doc_id != "Unknown" else (None, None)
            
            # Navigation buttons at the top
            nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
            with nav_col1:
                if prev_chunk_id:
                    if st.button("⬆️ Previous", key=f"chat_prev_{message_id}_{i}", use_container_width=True):
                        st.session_state[state_key] = prev_chunk_id
                        st.rerun()
                else:
                    st.button("⬆️ Previous", key=f"chat_prev_{message_id}_{i}_disabled", disabled=True, use_container_width=True)
            
            with nav_col2:
                st.markdown(f"<div style='text-align: center; padding: 0.3rem;'><small>Navigate chunks</small></div>", unsafe_allow_html=True)
            
            with nav_col3:
                if next_chunk_id:
                    if st.button("⬇️ Next", key=f"chat_next_{message_id}_{i}", use_container_width=True):
                        st.session_state[state_key] = next_chunk_id
                        st.rerun()
                else:
                    st.button("⬇️ Next", key=f"chat_next_{message_id}_{i}_disabled", disabled=True, use_container_width=True)
            
            st.markdown("---")
            
            # Render the chunk content
            try:
                render_chunk_markdown(content, doc_id, token)
            except Exception as e:
                st.error(f"Failed to render chunk {current_viewing_chunk_id}: {str(e)}")
                
            # Show chunk metadata and download button
            st.markdown("---")
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.caption(f"**Chunk ID:** {current_viewing_chunk_id}")
            with col2:
                st.caption(f"**Document ID:** {doc_id}")
            with col3:
                # Add on-demand download button
                if doc_id != "Unknown":
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