import streamlit as st
import requests
import os
from streamlit_pdf_viewer import pdf_viewer
from components.auth import require_auth, get_token
from components.chat_msg import render_message

from settigs import get_settings

settings = get_settings()
files_address = settings.FILES_ADDRESS


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
    }
    
    # Select endpoint based on preview option
    endpoint = "/query/preview" if preview_chunks else "/chat"
    
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
            for i, chunk in enumerate(result.get("retrieved_chunks", []), 1):
                doc_id = chunk.get('doc_id', 'Unknown')
                page_num = chunk.get('page_num', None)
                pdf_path = f"{files_address}/{doc_id}.pdf"

                with st.expander(f"📄 {doc_id} – Page {page_num + 1 if page_num is not None else 'N/A'}"):
                    st.markdown(chunk.get("content", ""), unsafe_allow_html=True)

                    if os.path.exists(pdf_path):
                        st.markdown("**Download PDF:**")
                        
                        # Read the PDF file and provide download button
                        with open(pdf_path, "rb") as pdf_file:
                            pdf_bytes = pdf_file.read()
                        
                        st.download_button(
                            label=f"📥 Download {doc_id}.pdf",
                            data=pdf_bytes,
                            file_name=f"{doc_id}.pdf",
                            mime="application/pdf",
                            key=f"download_{doc_id}_{i}"
                        )
                        
                        # Commented out PDF preview section
                        # st.markdown("**PDF Preview:**")
                        # # Display PDF with custom zoom, alignment, and separators
                        # pdf_viewer(
                        #     pdf_path,
                        #     scroll_to_page=page_num+1,
                        #     width=700,
                        #     height=1000,
                        #     zoom_level=1.2,                    # 120% zoom
                        #     viewer_align="center",             # Center alignment
                        #     show_page_separator=True,           # Show separators between pages
                        #     key=f"{pdf_path},{i}"
                        # )
                    else:
                        st.warning("PDF file not found.")
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