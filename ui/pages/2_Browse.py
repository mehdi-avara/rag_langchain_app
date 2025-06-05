import streamlit as st
import requests
import os
from components.auth import require_auth, get_token

API_URL = os.getenv("API_URL", "http://localhost:8000")

# Require authentication
require_auth()

st.title("Browse Documents")

# Load documents if not in session state
if "docs" not in st.session_state:
    try:
        response = requests.get(
            f"{API_URL}/documents",
            headers={"Authorization": f"Bearer {get_token()}"}
        )
        response.raise_for_status()
        st.session_state["docs"] = response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to load documents: {str(e)}")
        st.session_state["docs"] = []

# Display documents in a table
if st.session_state["docs"]:
    # Create DataFrame-like display
    st.markdown("### Your Documents")
    
    for doc in st.session_state["docs"]:
        col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
        
        with col1:
            st.write(f"📝 {doc['filename']}")
        with col2:
            st.write(f"📄 {doc['n_pages']} pages")
        with col3:
            st.write(f"🧩 {doc['n_chunks']} chunks")
        with col4:
            if st.button("🗑️", key=f"delete_{doc['id']}"):
                try:
                    response = requests.delete(
                        f"{API_URL}/documents/{doc['id']}",
                        headers={"Authorization": f"Bearer {get_token()}"}
                    )
                    response.raise_for_status()
                    st.success("Document deleted!")
                    del st.session_state["docs"]
                    st.rerun()
                except requests.exceptions.RequestException as e:
                    st.error(f"Failed to delete: {str(e)}")
        with col5:
            if st.button("🛈", key=f"summary_{doc['id']}"):
                try:
                    response = requests.get(
                        f"{API_URL}/summary/{doc['id']}",
                        headers={"Authorization": f"Bearer {get_token()}"}
                    )
                    response.raise_for_status()
                    st.info(response.json()["abstract"])
                except requests.exceptions.RequestException as e:
                    st.error(f"Failed to get summary: {str(e)}")
        
        st.markdown("---")
else:
    st.info("No documents uploaded yet. Go to the Upload page to add some!")

# Navigation
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    if st.button("← Back to Upload"):
        st.switch_page("pages/1_Upload.py")
with col2:
    if st.button("Chat with Documents →"):
        st.switch_page("pages/3_Chat.py") 