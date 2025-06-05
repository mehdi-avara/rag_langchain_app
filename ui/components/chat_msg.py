import streamlit as st
import requests
from typing import List, Dict, Any
import os

API_URL = os.getenv("API_URL", "http://localhost:8000")

def render_message(
    role: str,
    content: str,
    citations: List[int] = None,
    token: str = None
) -> None:
    """Render a chat message with optional citations."""
    with st.chat_message(role):
        st.write(content)
        
        if citations and token:
            with st.expander("View Citations"):
                for chunk_id in citations:
                    try:
                        response = requests.get(
                            f"{API_URL}/chunks/{chunk_id}",
                            headers={"Authorization": f"Bearer {token}"}
                        )
                        response.raise_for_status()
                        chunk = response.json()
                        st.markdown(f"**Chunk {chunk_id}:**")
                        st.text(chunk["content"])
                    except requests.exceptions.RequestException:
                        st.error(f"Failed to fetch chunk {chunk_id}") 