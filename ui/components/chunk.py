import streamlit as st
import requests
from typing import Dict, Optional, List
import re
import markdown

from settigs import get_settings
from components.auth import get_token

settings = get_settings()
API_URL = settings.API_URL


def fetch_chunk(chunk_id: int, token: str) -> Optional[Dict]:
    """Fetch a single chunk by ID."""
    try:
        response = requests.get(
            f"{API_URL}/documents/chunks/{chunk_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None


def fetch_adjacent_chunks(doc_id: int, current_chunk_id: int, token: str) -> tuple[Optional[int], Optional[int]]:
    """
    Fetch adjacent chunk IDs for a given chunk.
    Returns (previous_chunk_id, next_chunk_id)
    """
    try:
        # Fetch all chunks for the document
        response = requests.get(
            f"{API_URL}/documents/{doc_id}/chunks/",
            headers={"Authorization": f"Bearer {token}"},
            params={"page": 1, "page_size": 1000}  # Get enough chunks
        )
        response.raise_for_status()
        chunks = response.json()
        
        # Find the current chunk index
        chunk_ids = [c["id"] for c in chunks]
        try:
            current_index = chunk_ids.index(current_chunk_id)
        except ValueError:
            return None, None
        
        # Get previous and next chunk IDs
        prev_id = chunk_ids[current_index - 1] if current_index > 0 else None
        next_id = chunk_ids[current_index + 1] if current_index < len(chunk_ids) - 1 else None
        
        return prev_id, next_id
        
    except requests.exceptions.RequestException:
        return None, None


def fetch_image(doc_id: int, image_path: str, token: str) -> Optional[bytes]:
    """Fetch an image from the API."""
    try:
        response = requests.get(
            f"{API_URL}/documents/{doc_id}/images/{image_path}",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException:
        return None

@st.cache_resource
def render_chunk_markdown(content: str, doc_id: int, token: str) -> None:
    """Render markdown content with proper image handling."""
    if not content:
        st.write("No content available")
        return
    
    # Find all image references
    image_pattern = r'!\[(.*?)\]\((.*?)\)'
    images = re.findall(image_pattern, content)
    
    # Split content by images to render text and images separately
    parts = re.split(image_pattern, content)
    
    # Process content in parts
    current_part = 0
    text_buffer = ""
    
    for i, part in enumerate(parts):
        # Every third element starting from 0 is text content
        if i % 3 == 0:
            text_buffer += part
        # Every third element starting from 2 is an image path
        elif i % 3 == 2:
            # Render accumulated text first
            if text_buffer.strip():
                render_text_markdown(text_buffer)
                text_buffer = ""
            
            image_path = part
            alt_text = parts[i-1] if i > 0 else ""
            
            # Skip if it's an external URL
            if image_path.startswith("http://") or image_path.startswith("https://"):
                st.markdown(f"![{alt_text}]({image_path})")
            else:
                # Fetch and display image
                image_data = fetch_image(doc_id, image_path, token)
                if image_data:
                    st.image(image_data, caption=alt_text if alt_text else None, use_container_width=True)
                else:
                    st.warning(f"⚠️ Failed to load image: {image_path}")
    
    # Render any remaining text
    if text_buffer.strip():
        render_text_markdown(text_buffer)


def render_text_markdown(text: str) -> None:
    """Render text markdown without images."""
    if not text.strip():
        return
    
    # Configure markdown with extensions for proper table support
    md = markdown.Markdown(
        extensions=[
            'tables',       # Enable table support
            'fenced_code',  # Enable fenced code blocks
            'codehilite',   # Enable code highlighting
        ]
    )
    
    # Convert markdown to HTML
    html_content = md.convert(text)
    
    # Reset the markdown instance to avoid state issues
    md.reset()
    
    # Add custom CSS for better formatting using st.html if available, otherwise st.markdown
    try:
        # Try using st.html for better HTML rendering (Streamlit >= 1.28)
        css_and_html = f"""
        <style>
            .markdown-content {{
                font-size: 1rem;
                line-height: 1.6;
            }}
            .markdown-content table {{
                width: 100%;
                border-collapse: collapse;
                margin: 1rem 0;
                background-color: rgba(255, 255, 255, 0.05);
            }}
            .markdown-content thead {{
                background-color: rgba(255, 255, 255, 0.1);
            }}
            .markdown-content th {{
                border: 1px solid rgba(255, 255, 255, 0.3);
                padding: 0.75rem;
                text-align: left;
                font-weight: bold;
            }}
            .markdown-content td {{
                border: 1px solid rgba(255, 255, 255, 0.2);
                padding: 0.75rem;
            }}
            .markdown-content tr:hover {{
                background-color: rgba(255, 255, 255, 0.05);
            }}
            .markdown-content code {{
                background-color: rgba(0, 0, 0, 0.3);
                padding: 0.2rem 0.4rem;
                border-radius: 0.25rem;
                font-family: monospace;
            }}
            .markdown-content pre {{
                background-color: rgba(0, 0, 0, 0.3);
                padding: 1rem;
                border-radius: 0.5rem;
                overflow-x: auto;
            }}
            .markdown-content pre code {{
                background-color: transparent;
                padding: 0;
            }}
            .markdown-content h1, .markdown-content h2, .markdown-content h3,
            .markdown-content h4, .markdown-content h5, .markdown-content h6 {{
                margin-top: 1.5rem;
                margin-bottom: 0.5rem;
            }}
            .markdown-content p {{
                margin: 0.5rem 0;
            }}
            .markdown-content ul, .markdown-content ol {{
                margin: 0.5rem 0;
                padding-left: 2rem;
            }}
            .markdown-content blockquote {{
                border-left: 4px solid rgba(255, 255, 255, 0.3);
                padding-left: 1rem;
                margin: 1rem 0;
                color: rgba(255, 255, 255, 0.7);
            }}
        </style>
        <div class="markdown-content">{html_content}</div>
        """
        st.html(css_and_html)
    except AttributeError:
        # Fallback to st.markdown for older Streamlit versions
        st.markdown(css_and_html, unsafe_allow_html=True)


def render_chunk_viewer(
    chunk_id: int,
    show_navigation: bool = True,
    show_metadata: bool = True,
    container_height: Optional[int] = None,
    key_prefix: str = "chunk_viewer"
) -> None:
    """
    Render a chunk viewer with navigation controls.
    
    Args:
        chunk_id: The ID of the chunk to display
        show_navigation: Whether to show previous/next navigation buttons
        show_metadata: Whether to show chunk metadata
        container_height: Optional height for the container (in pixels)
        key_prefix: Prefix for Streamlit component keys (for multiple viewers on same page)
    """
    token = get_token()
    if not token:
        st.error("Please log in to view chunks")
        return
    
    # Initialize session state for current chunk if not exists
    state_key = f"{key_prefix}_current_chunk_id"
    if state_key not in st.session_state:
        st.session_state[state_key] = chunk_id
    
    # Fetch current chunk
    current_chunk = fetch_chunk(st.session_state[state_key], token)
    if not current_chunk:
        st.error(f"Failed to load chunk {st.session_state[state_key]}")
        return
    
    doc_id = current_chunk.get("doc_id")
    
    # Fetch adjacent chunks
    prev_chunk_id, next_chunk_id = fetch_adjacent_chunks(doc_id, st.session_state[state_key], token)
    
    # Navigation buttons at the top
    if show_navigation:
        col_prev, col_info, col_next = st.columns([1, 3, 1])
        
        with col_prev:
            if prev_chunk_id:
                if st.button("⬆️ Previous", key=f"{key_prefix}_btn_prev_top", use_container_width=True):
                    st.session_state[state_key] = prev_chunk_id
                    st.rerun()
            else:
                st.button("⬆️ Previous", key=f"{key_prefix}_btn_prev_top_disabled", disabled=True, use_container_width=True)
        
        with col_info:
            st.markdown(f"<div style='text-align: center; padding: 0.5rem;'><b>Chunk {current_chunk['id']}</b></div>", unsafe_allow_html=True)
        
        with col_next:
            if next_chunk_id:
                if st.button("⬇️ Next", key=f"{key_prefix}_btn_next_top", use_container_width=True):
                    st.session_state[state_key] = next_chunk_id
                    st.rerun()
            else:
                st.button("⬇️ Next", key=f"{key_prefix}_btn_next_top_disabled", disabled=True, use_container_width=True)
        
        st.markdown("---")
    
    # Show metadata if requested
    if show_metadata:
        meta_cols = st.columns(4)
        with meta_cols[0]:
            st.caption(f"**Chunk ID:** {current_chunk['id']}")
        with meta_cols[1]:
            st.caption(f"**Document ID:** {doc_id}")
        with meta_cols[2]:
            if current_chunk.get('page_num'):
                st.caption(f"**Page:** {current_chunk['page_num']}")
        with meta_cols[3]:
            if current_chunk.get('chunk_type'):
                st.caption(f"**Type:** {current_chunk['chunk_type']}")
    
    # Create container for chunks
    if container_height:
        chunk_container = st.container(height=container_height)
    else:
        chunk_container = st.container()
    
    with chunk_container:
        # Show previous chunk (dimmed)
        if prev_chunk_id:
            prev_chunk = fetch_chunk(prev_chunk_id, token)
            if prev_chunk:
                with st.expander(f"📄 Previous Chunk ({prev_chunk_id})", expanded=False):
                    render_chunk_markdown(prev_chunk.get("content", ""), doc_id, token)
        
        # Show current chunk (highlighted)
        st.markdown("### 🎯 Current Chunk")
        render_chunk_markdown(current_chunk.get("content", ""), doc_id, token)
        
        # Show next chunk (dimmed)
        if next_chunk_id:
            next_chunk = fetch_chunk(next_chunk_id, token)
            if next_chunk:
                st.markdown("---")
                with st.expander(f"📄 Next Chunk ({next_chunk_id})", expanded=False):
                    render_chunk_markdown(next_chunk.get("content", ""), doc_id, token)
    
    # Navigation buttons at the bottom
    if show_navigation:
        st.markdown("---")
        col_prev_bottom, col_space, col_next_bottom = st.columns([1, 3, 1])
        
        with col_prev_bottom:
            if prev_chunk_id:
                if st.button("⬆️ Previous", key=f"{key_prefix}_btn_prev_bottom", use_container_width=True):
                    st.session_state[state_key] = prev_chunk_id
                    st.rerun()
            else:
                st.button("⬆️ Previous", key=f"{key_prefix}_btn_prev_bottom_disabled", disabled=True, use_container_width=True)
        
        with col_next_bottom:
            if next_chunk_id:
                if st.button("⬇️ Next", key=f"{key_prefix}_btn_next_bottom", use_container_width=True):
                    st.session_state[state_key] = next_chunk_id
                    st.rerun()
            else:
                st.button("⬇️ Next", key=f"{key_prefix}_btn_next_bottom_disabled", disabled=True, use_container_width=True)


def render_compact_chunk_viewer(
    chunk_id: int,
    max_height: int = 400,
    key_prefix: str = "compact_chunk_viewer"
) -> None:
    """
    Render a compact version of the chunk viewer suitable for small areas.
    
    Args:
        chunk_id: The ID of the chunk to display
        max_height: Maximum height for the viewer in pixels
        key_prefix: Prefix for Streamlit component keys
    """
    render_chunk_viewer(
        chunk_id=chunk_id,
        show_navigation=True,
        show_metadata=False,
        container_height=max_height,
        key_prefix=key_prefix
    )


def render_simple_chunk_content(chunk_id: int, doc_id: int) -> None:
    """
    Render just the chunk content without navigation (for embedding in other components).
    
    Args:
        chunk_id: The ID of the chunk to display
        doc_id: The document ID (for image rendering)
    """
    token = get_token()
    if not token:
        st.error("Please log in to view chunks")
        return
    
    chunk = fetch_chunk(chunk_id, token)
    if not chunk:
        st.error(f"Failed to load chunk {chunk_id}")
        return
    
    render_chunk_markdown(chunk.get("content", ""), doc_id, token)
