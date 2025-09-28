import streamlit as st
import requests
from typing import List, Dict, Any, Optional
import os
import re
import markdown

from settigs import get_settings

settings = get_settings()
API_URL = settings.API_URL

def render_message(
    role: str,
    content: str,
    retrieved_chunks: List[Dict] = None,
) -> None:
    """Render a chat message with optional citations and retrieved chunks."""
    with st.chat_message(role):
        if role == "assistant":
            # Render answer with clickable citations
            render_answer_with_citations(content)
            
            # Display retrieved chunks if available
            if retrieved_chunks:
                render_retrieved_chunks(retrieved_chunks)
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

def render_retrieved_chunks(retrieved_chunks: List[Dict]):
    """Render the retrieved chunks section with expandable content."""
    st.markdown("---")
    st.subheader("📚 Retrieved Sources")
    
    for i, chunk in enumerate(retrieved_chunks):
        chunk_id = chunk.get("chunk_id", f"unknown_{i}")
        doc_id = chunk.get("doc_id", "Unknown")
        content = chunk.get("content", "")
        
        # Create expandable section for each chunk
        with st.expander(f"📄 Source {i+1} (Chunk ID: {chunk_id}, Doc: {doc_id})", expanded=False):
            # Render markdown content
            render_markdown_content(content)
            
            # Show chunk metadata
            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"**Chunk ID:** {chunk_id}")
            with col2:
                st.caption(f"**Document ID:** {doc_id}")

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