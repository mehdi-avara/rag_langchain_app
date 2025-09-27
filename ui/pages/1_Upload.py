import streamlit as st
import requests
import os
from components.auth import require_auth, get_token

API_URL = os.getenv("API_URL", "http://localhost:8000")

# Require authentication
require_auth()

st.title("Upload Documents")

# Upload type selection
upload_type = st.radio(
    "Select upload type",
    ["Standard Upload"],
    # ["Standard Upload", "PDF as Images"],
    help="Standard Upload processes the document normally."
)

# Chunking mode selection (for both upload types)
chunking_mode = st.selectbox(
    "Select chunking strategy",
    ["sentence-3", "paragraph", "word-fixed"],
    help="""Choose how to split the document:
    - sentence-3: Groups text into chunks of 3 sentences
    - paragraph: Splits text by paragraphs
    - token-fixed: Splits text into fixed-size chunks"""
)

# File uploader
if upload_type == "Standard Upload":
    uploaded_file = st.file_uploader("Choose a PDF or image file", type=["pdf", "png", "jpg", "jpeg","txt",".md"])
# else:
#     uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"])

if uploaded_file:
    # Show progress
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        # Upload file
        status_text.text("Uploading file...")
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        
        # Select endpoint based on upload type
        endpoint = "/upload-pdf-as-images" if upload_type == "PDF as Images" else "/upload"
        
        # Prepare request data
        data = {"chunking_mode": chunking_mode}
        
        response = requests.post(
            f"{API_URL}{endpoint}",
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {get_token()}"}
        )
        response.raise_for_status()
        
        # Update progress
        progress_bar.progress(100)
        status_text.text("Upload complete!")
        
        # Show success message
        st.success(f"Document uploaded successfully! ID: {response.json()['doc_id']}")
        
        # Refresh document list
        if "docs" in st.session_state:
            del st.session_state["docs"]
            
    except requests.exceptions.RequestException as e:
        st.error(f"Upload failed: {str(e)}")
        progress_bar.empty()
        status_text.empty()

# Navigation
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    if st.button("← Back to Home"):
        st.switch_page("Home.py")
with col2:
    if st.button("Browse Documents →"):
        st.switch_page("pages/2_Browse.py") 