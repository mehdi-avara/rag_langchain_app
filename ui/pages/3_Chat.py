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

# Chat input
if prompt := st.chat_input("Ask a question about your documents"):
    # Add user message to history
    st.session_state["history"].append({
        "role": "user",
        "content": prompt
    })
    
    # Display user message
    render_message(role="user", content=prompt)
    
    # Get response from API
    try:
        response = requests.post(
            f"{API_URL}/chat",
            json={"query": prompt},
            headers={"Authorization": f"Bearer {get_token()}"}
        )
        response.raise_for_status()
        result = response.json()
        
        # Add assistant message to history
        st.session_state["history"].append({
            "role": "assistant",
            "content": result["answer"],
            "citations": result["citations"]
        })
        
        # Display assistant message
        render_message(
            role="assistant",
            content=result["answer"],
            citations=result["citations"],
            token=get_token()
        )
        
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to get response: {str(e)}")

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