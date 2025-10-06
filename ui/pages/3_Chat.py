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

# Initialize document IDs list
if "selected_doc_ids" not in st.session_state:
    st.session_state["selected_doc_ids"] = []

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

# Document ID input section
st.markdown("### 📄 Document Filter")
if st.session_state["selected_doc_ids"]:
    st.info(f"🔍 Filtering to {len(st.session_state['selected_doc_ids'])} document(s). Leave empty to search all documents.")
else:
    st.info("🔍 Searching all documents. Add document IDs below to filter to specific documents.")

col1, col2 = st.columns([3, 1])

with col1:
    doc_id_input = st.text_input(
        "Add Document ID(s)",
        placeholder="Enter document ID(s) (e.g., 1, 2, 3 or 1,2,3)",
        help="Enter document ID(s) to filter search to specific documents. You can enter multiple IDs separated by commas. Leave empty to search all documents.",
        key="doc_id_input"
    )

with col2:
    if st.button("➕ Add", use_container_width=True):
        if doc_id_input.strip():
            try:
                # Split by comma and clean up whitespace
                doc_ids_str = [id_str.strip() for id_str in doc_id_input.split(',')]
                doc_ids = [int(id_str) for id_str in doc_ids_str if id_str]
                
                added_count = 0
                for doc_id in doc_ids:
                    if doc_id not in st.session_state["selected_doc_ids"]:
                        st.session_state["selected_doc_ids"].append(doc_id)
                        added_count += 1
                
                if added_count > 0:
                    st.session_state["doc_id_input"] = ""  # Clear input
                    st.rerun()
                else:
                    st.warning("All document IDs are already added.")
                    
            except ValueError:
                st.error("Please enter valid numbers for document IDs (e.g., 1, 2, 3).")
        else:
            st.warning("Please enter a document ID.")

# Display selected document IDs as removable tags
if st.session_state["selected_doc_ids"]:
    st.markdown("**Selected Documents:**")
    
    # Sort document IDs for better organization
    sorted_doc_ids = sorted(st.session_state["selected_doc_ids"])
    
    cols = st.columns(min(len(sorted_doc_ids), 5))  # Max 5 columns
    
    for i, doc_id in enumerate(sorted_doc_ids):
        with cols[i % 5]:
            if st.button(f"❌ {doc_id}", key=f"remove_doc_{doc_id}", help=f"Remove document {doc_id}"):
                st.session_state["selected_doc_ids"].remove(doc_id)
                st.rerun()
    
    # Clear all button
    if st.button("🗑️ Clear All Documents", type="secondary"):
        st.session_state["selected_doc_ids"] = []
        st.rerun()

st.markdown("---")

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
        "doc_ids": st.session_state["selected_doc_ids"] if st.session_state["selected_doc_ids"] else None,
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