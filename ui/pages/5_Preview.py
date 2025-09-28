import streamlit as st
import requests
import os
from components.auth import require_auth, get_token
from components.chat_msg import render_markdown_content

from settigs import get_settings

settings = get_settings()
API_URL = settings.API_URL

# Require authentication
require_auth()

st.title("🔍 Document Preview")

# Initialize preview history
if "preview_history" not in st.session_state:
    st.session_state["preview_history"] = []

# Display preview history
for i, preview in enumerate(st.session_state["preview_history"]):
    with st.expander(f"🔍 Query {i+1}: {preview['query'][:50]}...", expanded=False):
        st.write(f"**Query:** {preview['query']}")
        st.write(f"**Timestamp:** {preview['timestamp']}")
        
        # Display retrieved chunks
        if preview.get("retrieved_chunks"):
            st.subheader("📚 Retrieved Chunks")
            for j, chunk in enumerate(preview["retrieved_chunks"]):
                chunk_id = chunk.get("chunk_id", f"unknown_{j}")
                doc_id = chunk.get("doc_id", "Unknown")
                content = chunk.get("content", "")
                
                with st.expander(f"📄 Chunk {j+1} (ID: {chunk_id}, Doc: {doc_id})", expanded=False):
                    render_markdown_content(content)
                    
                    # Show chunk metadata
                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption(f"**Chunk ID:** {chunk_id}")
                    with col2:
                        st.caption(f"**Document ID:** {doc_id}")

# Advanced options in sidebar
with st.sidebar:
    st.header("⚙️ Preview Options")
    
    # Query rewriting option
    rewrite_query = st.checkbox(
        "🔄 Rewrite query with LLM",
        help="Use AI to improve your question for better search results"
    )
    
    # Keyword extraction option
    extract_keywords_with_llm = st.checkbox(
        "🔍 Extract keywords with LLM",
        help="Use AI to extract key terms from your question"
    )
    
    # Search mode selection
    search_mode = st.selectbox(
        "🔎 Search Mode",
        options=["hybrid", "vector", "keyword"],
        index=0,
        help="Choose how to search through your documents"
    )

# Query input
if prompt := st.chat_input("Enter your search query to preview retrieved chunks..."):
    # Show loading spinner
    with st.spinner("🔍 Searching documents..."):
        # Prepare request data
        request_data = {
            "query": prompt,
            "rewrite_query": rewrite_query,
            "extract_keywords_with_llm": extract_keywords_with_llm,
        }
        
        # Get response from API (only /query/preview endpoint)
        try:
            response = requests.post(
                f"{API_URL}/query/preview",
                json=request_data,
                headers={"Authorization": f"Bearer {get_token()}"}
            )
            response.raise_for_status()
            result = response.json()
            
            # Add to preview history
            import datetime
            st.session_state["preview_history"].append({
                "query": prompt,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "retrieved_chunks": result.get("retrieved_chunks", [])
            })
            
            # Display current results
            st.subheader("📚 Retrieved Chunks")
            
            retrieved_chunks = result.get("retrieved_chunks", [])
            if not retrieved_chunks:
                st.warning("No chunks found for your query.")
            else:
                st.success(f"Found {len(retrieved_chunks)} chunks")
                
                for i, chunk in enumerate(retrieved_chunks):
                    chunk_id = chunk.get("chunk_id", f"unknown_{i}")
                    doc_id = chunk.get("doc_id", "Unknown")
                    content = chunk.get("content", "")
                    
                    # Create expandable section for each chunk
                    with st.expander(f"📄 Chunk {i+1} (ID: {chunk_id}, Doc: {doc_id})", expanded=True):
                        # Render markdown content
                        render_markdown_content(content)
                        
                        # Show chunk metadata
                        col1, col2 = st.columns(2)
                        with col1:
                            st.caption(f"**Chunk ID:** {chunk_id}")
                        with col2:
                            st.caption(f"**Document ID:** {doc_id}")
                        
                        # Add action buttons
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            if st.button(f"💬 Chat about this", key=f"chat_{chunk_id}"):
                                # Store the query for chat
                                st.session_state["chat_query"] = prompt
                                st.switch_page("pages/3_Chat.py")
                        with col2:
                            if st.button(f"📋 Copy ID", key=f"copy_{chunk_id}"):
                                st.write(f"Chunk ID: {chunk_id}")
                        with col3:
                            if st.button(f"📄 View Doc", key=f"doc_{chunk_id}"):
                                st.write(f"Document ID: {doc_id}")
            
        except requests.exceptions.RequestException as e:
            st.error(f"❌ Failed to get response: {str(e)}")

# Navigation and controls
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("← Back to Browse", use_container_width=True):
        st.switch_page("pages/2_Browse.py")
with col2:
    if st.button("🗑️ Clear History", use_container_width=True):
        st.session_state["preview_history"] = []
        st.rerun()
with col3:
    if st.button("💬 Go to Chat", use_container_width=True):
        st.switch_page("pages/3_Chat.py")

# Instructions
st.markdown("---")
st.info("""
**📖 How to use Preview Mode:**

1. **Enter your query** in the chat input above
2. **View retrieved chunks** that match your search
3. **Click on chunks** to expand and read the full content
4. **Use action buttons** to chat about specific chunks or view documents
5. **History is preserved** so you can review previous searches

This mode shows you exactly what documents and chunks the system finds for your query, without AI processing.
""")
