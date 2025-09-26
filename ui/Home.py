import streamlit as st
from components.auth import login

st.title("Industorial search engine")

# Check if already logged in
if "token" in st.session_state:
    st.switch_page("pages/1_Upload.py")

# Login form
with st.form("login_form"):
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    submit = st.form_submit_button("Login")

    if submit:
        token = login(username, password)
        if token:
            st.session_state["token"] = token
            st.success("Login successful!")
            st.switch_page("pages/1_Upload.py")
        else:
            st.error("Invalid username or password") 