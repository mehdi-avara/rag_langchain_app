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


def render_chunk_markdown(content: str, doc_id: int, token: str) -> None:
    """Render markdown content with proper image handling."""
    if not content:
        st.write("No content available")
        return
    
    # Replace markdown image references with proper URLs
    # Pattern: ![alt](images/hash.jpg)
    def replace_image_url(match):
        alt_text = match.group(1)
        image_path = match.group(2)
        
        # If it's already a full URL, leave it as is
        if image_path.startswith("http://") or image_path.startswith("https://"):
            return match.group(0)
        
        # Otherwise, construct the API URL
        api_image_url = f"{API_URL}/documents/{doc_id}/images/{image_path}"
        return f'<img src="{api_image_url}" alt="{alt_text}" style="max-width: 100%; height: auto;" />'
    
    # Replace image references
    content_with_images = re.sub(
        r'!\[(.*?)\]\((.*?)\)',
        replace_image_url,
        content
    )
    
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
    html_content = md.convert(content_with_images)
    
    # Add custom CSS for better formatting
    custom_css = """
    <style>
        .chunk-content {
            padding: 1rem;
            border-radius: 0.5rem;
            background-color: rgba(255, 255, 255, 0.05);
        }
        .chunk-content img {
            display: block;
            margin: 1rem auto;
            max-width: 100%;
            height: auto;
            border-radius: 0.5rem;
        }
        .chunk-content table {
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
        }
        .chunk-content th,
        .chunk-content td {
            border: 1px solid rgba(255, 255, 255, 0.2);
            padding: 0.5rem;
        }
        .chunk-content code {
            background-color: rgba(0, 0, 0, 0.3);
            padding: 0.2rem 0.4rem;
            border-radius: 0.25rem;
        }
        .chunk-content pre {
            background-color: rgba(0, 0, 0, 0.3);
            padding: 1rem;
            border-radius: 0.5rem;
            overflow-x: auto;
        }
    </style>
    """
    
    # Display the content
    st.markdown(custom_css + f'<div class="chunk-content">{html_content}</div>', unsafe_allow_html=True)


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


render_simple_chunk_content(16701, 103)
