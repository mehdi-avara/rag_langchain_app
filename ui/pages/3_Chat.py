import streamlit as st
import requests
import os
from components.auth import require_auth, get_token
from components.chat_msg import render_message

API_URL = os.getenv("API_URL", "http://localhost:8000")

# Require authentication
require_auth()

st.title("Chat with Documents")

# Initialize chat history
if "history" not in st.session_state:
    st.session_state["history"] = []

# Display chat history
for msg in st.session_state["history"]:
    render_message(
        role=msg["role"],
        content=msg["content"],
        citations=msg.get("citations"),
        token=get_token()
    )

# Advanced options in sidebar
with st.sidebar:
    st.header("Advanced Options")
    
    # Query rewriting option
    rewrite_query = st.checkbox(
        "Rewrite query with LLM",
        help="Use AI to improve your question for better search results"
    )
    
    # Keyword extraction option
    extract_keywords_with_llm = st.checkbox(
        "Extract keywords with LLM",
        help="Use AI to extract key terms from your question"
    )
    
    # Chunking mode selection
    chunking_mode = st.selectbox(
        "Chunking strategy",
        ["sentence-3", "paragraph", "token-fixed"],
        help="""Choose how to split the document:
        - sentence-3: Groups text into chunks of 3 sentences
        - paragraph: Splits text by paragraphs
        - token-fixed: Splits text into fixed-size chunks"""
    )
    
    # Preview chunks option
    preview_chunks = st.checkbox(
        "Preview chunks only",
        help="Show only the retrieved chunks without AI processing"
    )

# Chat input
if prompt := st.chat_input("Ask a question about your documents"):
    # Add user message to history
    st.session_state["history"].append({
        "role": "user",
        "content": prompt
    })
    
    # Display user message
    render_message(role="user", content=prompt)
    
    # Prepare request data
    request_data = {
        "query": prompt,
        "rewrite_query": rewrite_query,
        "extract_keywords_with_llm": extract_keywords_with_llm,
        "chunking_mode": chunking_mode
    }
    
    # Select endpoint based on preview option
    endpoint = "/query/preview_chunks" if preview_chunks else "/query"
    
    # Get response from API
    try:
        response = requests.post(
            f"{API_URL}{endpoint}",
            json=request_data,
            headers={"Authorization": f"Bearer {get_token()}"}
        )
        response.raise_for_status()
        result = response.json()
        
        if preview_chunks:
            # Display chunks preview
            st.subheader("Retrieved Chunks")
            for chunk in result.get("retrieved_chunks", []):
                st.markdown(f"**Chunk from {chunk.get('filename', 'Unknown')} (Page {chunk.get('page_num', 'N/A')})**")
                st.markdown(chunk.get("content", ""))
                st.markdown("---")
        else:
            # Add assistant message to history
            st.session_state["history"].append({
                "role": "assistant",
                "content": result.get("answer", "Sorry, I couldn't process your request."),
                "citations": result.get("citations", [])
            })
            
            # Display assistant message
            render_message(
                role="assistant",
                content=result.get("answer", "Sorry, I couldn't process your request."),
                citations=result.get("citations", []),
                token=get_token()
            )
        
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to get response: {str(e)}")
        # Add error message to history
        st.session_state["history"].append({
            "role": "assistant",
            "content": f"Error: {str(e)}"
        })

# Navigation
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    if st.button("← Back to Browse"):
        st.switch_page("pages/2_Browse.py")
with col2:
    if st.button("Clear Chat"):
        st.session_state["history"] = []
        st.rerun() 