import pytest
from fastapi.testclient import TestClient
from backend.api import app
from backend.db.models import User, Document
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

def test_upload_pdf(monkeypatch):
    db = init_db()
    user = create_user(db, "alice")
    token = get_token("alice", "test")
    with open("tests/sample.pdf", "rb") as f:
        response = client.post("/upload", files={"file": ("sample.pdf", f, "application/pdf")}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    doc_id = response.json()["doc_id"]
    doc = db.query(Document).filter(Document.id == doc_id).first()
    assert doc is not None
    assert doc.filename == "sample.pdf"

def test_delete_acl():
    db = init_db()
    user_a = create_user(db, "usera")
    user_b = create_user(db, "userb")
    token_a = get_token("usera", "test")
    token_b = get_token("userb", "test")
    # User A uploads a doc
    doc = Document(owner_id=user_a.id, filename="foo.pdf", n_pages=1, n_chunks=1)
    db.add(doc)
    db.commit()
    # User B tries to delete
    response = client.delete(f"/documents/{doc.id}", headers={"Authorization": f"Bearer {token_b}"})
    assert response.status_code == 404 