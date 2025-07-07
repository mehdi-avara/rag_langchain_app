import streamlit as st
import requests
from typing import Optional
import os

API_URL = os.getenv("API_URL", "http://localhost:8000")

def login(username: str, password: str) -> Optional[str]:
    """Attempt to log in and return JWT token if successful."""
    try:
        response = requests.post(
            f"{API_URL}/auth/login/",
            json={"username": username, "password": password}
        )
        response.raise_for_status()
        return response.json()["access_token"]
    except requests.exceptions.RequestException:
        return None

def get_token() -> Optional[str]:
    """Get JWT token from session state."""
    return st.session_state.get("token")

def require_auth():
    """Redirect to login if not authenticated."""
    if not get_token():
        st.switch_page("Home.py") 