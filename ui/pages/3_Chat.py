import streamlit as st
import requests
import os
from components.auth import require_auth, get_token
from components.chat_msg import render_message

from settigs import get_settings

settings = get_settings()
API_URL = settings.API_URL

# Require authentication
require_auth()

st.title("💬 Chat with Documents")

# Initialize chat history
if "history" not in st.session_state:
    st.session_state["history"] = []

# Display chat history
for msg in st.session_state["history"]:
    render_message(
        role=msg["role"],
        content=msg["content"],
        retrieved_chunks=msg.get("retrieved_chunks"),
    )

# Advanced options in sidebar
with st.sidebar:
    st.header("⚙️ Chat Options")
    
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

# Chat input
if prompt := st.chat_input("Ask a question about your documents..."):
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
    }
    
    # Show loading spinner
    with st.spinner("🤔 Thinking..."):
        # Get response from API (only /chat endpoint)
        try:
            response = requests.post(
                f"{API_URL}/chat",
                json=request_data,
                headers={"Authorization": f"Bearer {get_token()}"}
            )
            response.raise_for_status()
            result = response.json()
            
            # Add assistant message to history
            st.session_state["history"].append({
                "role": "assistant",
                "content": result.get("answer", "Sorry, I couldn't process your request."),
                "citations": result.get("citations", []),
                "retrieved_chunks": result.get("retrieved_chunks", [])
            })
            
            # Display assistant message
            render_message(
                role="assistant",
                content=result.get("answer", "Sorry, I couldn't process your request."),
                retrieved_chunks=result.get("retrieved_chunks", []),
            )
            
        except requests.exceptions.RequestException as e:
            st.error(f"❌ Failed to get response: {str(e)}")
            # Add error message to history
            st.session_state["history"].append({
                "role": "assistant",
                "content": f"Error: {str(e)}"
            })

# Navigation and controls
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("← Back to Browse", use_container_width=True):
        st.switch_page("pages/2_Browse.py")
with col2:
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state["history"] = []
        st.rerun()
with col3:
    if st.button("📄 Preview Mode", use_container_width=True):
        st.switch_page("pages/5_Preview.py") 