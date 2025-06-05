import pytest
from fastapi.testclient import TestClient
from backend.api import app
from backend.db.models import User, Document, Chunk
from backend.db.init_db import init_db

client = TestClient(app)

def create_user(db, username, pw_hash="test", role="user"):
    user = User(username=username, pw_hash=pw_hash, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def get_token(username, password):
    response = client.post("/auth/login", json={"username": username, "password": password})
    return response.json()["access_token"]

def test_chat_semantic():
    db = init_db()
    user = create_user(db, "carol")
    token = get_token("carol", "test")
    # Add a document and chunk
    doc = Document(owner_id=user.id, filename="foo.pdf", n_pages=1, n_chunks=1)
    db.add(doc)
    db.commit()
    chunk = Chunk(doc_id=doc.id, page_num=1, token_count=5, content="The Eiffel Tower is in Paris.")
    db.add(chunk)
    db.commit()
    # Query
    response = client.post("/chat", json={"query": "Where is the Eiffel Tower?"}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "Paris" in data["answer"]
    assert isinstance(data["citations"], list) 