import streamlit as st
import requests
import os
from components.auth import require_auth, get_token

API_URL = os.getenv("API_URL", "http://localhost:8000")

# Require authentication
require_auth()

st.title("Browse Documents")

# Initialize session state for chunks
if "viewing_chunks" not in st.session_state:
    st.session_state["viewing_chunks"] = None
if "chunks_page" not in st.session_state:
    st.session_state["chunks_page"] = 1
if "chunks" not in st.session_state:
    st.session_state["chunks"] = []

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

# Function to load chunks
def load_chunks(doc_id, page=1):
    try:
        response = requests.get(
            f"{API_URL}/documents/{doc_id}/chunks",
            params={"page": page, "page_size": 10},
            headers={"Authorization": f"Bearer {get_token()}"}
        )
        response.raise_for_status()
        st.session_state["chunks"] = response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to load chunks: {str(e)}")
        st.session_state["chunks"] = []

# Display chunks if viewing
if st.session_state["viewing_chunks"]:
    st.markdown("### Document Chunks")
    doc = next((d for d in st.session_state["docs"] if d["id"] == st.session_state["viewing_chunks"]), None)
    if doc:
        st.write(f"📝 {doc['filename']}")
        
        # Load chunks if not loaded or page changed
        if not st.session_state["chunks"] or st.session_state["chunks_page"] != st.session_state.get("current_page", 1):
            load_chunks(doc["id"], st.session_state["chunks_page"])
            st.session_state["current_page"] = st.session_state["chunks_page"]
        
        # Display chunks
        for chunk in st.session_state["chunks"]:
            with st.expander(f"Page {chunk['page_num']} - {chunk['chunk_type']}"):
                st.write(chunk["content"])
                if chunk["start_pos"] is not None:
                    st.caption(f"Position: {chunk['start_pos']} - {chunk['end_pos']}")
        
        # Pagination controls
        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("← Previous", disabled=st.session_state["chunks_page"] == 1):
                st.session_state["chunks_page"] -= 1
                st.rerun()
        with col2:
            st.write(f"Page {st.session_state['chunks_page']}")
        with col3:
            if st.button("Next →", disabled=len(st.session_state["chunks"]) < 10):
                st.session_state["chunks_page"] += 1
                st.rerun()
        
        if st.button("← Back to Documents"):
            st.session_state["viewing_chunks"] = None
            st.session_state["chunks_page"] = 1
            st.session_state["chunks"] = []
            st.rerun()

# Display documents in a table
elif st.session_state["docs"]:
    st.markdown("### Your Documents")
    
    for doc in st.session_state["docs"]:
        col1, col2, col3, col4, col5, col6 = st.columns([3, 1, 1, 1, 1, 1])
        
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
        with col6:
            if st.button("📑", key=f"chunks_{doc['id']}"):
                st.session_state["viewing_chunks"] = doc["id"]
                st.session_state["chunks_page"] = 1
                st.rerun()
        
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