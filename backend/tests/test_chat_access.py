import os
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_IP", "localhost")
os.environ.setdefault("default_username", "admin")
os.environ.setdefault("default_password", "admin123456")
os.environ.setdefault("default_firstname", "Admin")
os.environ.setdefault("jwt_secret", "test-secret")
os.environ.setdefault("openai_api_key", "test")
os.environ.setdefault("jina_api_key", "test")

from Models import Chat, ChatMessage, Comment, Document
from Models.chat import ChatRole
from routs import chat as chat_routes
from schemas.chat import ChatRequest


class FakeQuery:
    def __init__(self, db, target):
        self.db = db
        self.target = target
        self.filters = []
        self.ordered = False
        self.deleted = False

    def filter(self, *args, **kwargs):
        self.filters.extend(args)
        return self

    def order_by(self, *args, **kwargs):
        self.ordered = True
        return self

    def join(self, *args, **kwargs):
        return self

    def first(self):
        if self.target is Chat:
            return self.db.chat_result
        return None

    def all(self):
        key = getattr(self.target, "key", "")

        if self.target is Chat:
            return self.db.chat_rows

        if self.target is ChatMessage:
            return self.db.message_rows

        if key == "id":
            return [(item_id,) for item_id in self.db.comment_ids]

        if isinstance(self.target, tuple):
            if len(self.target) == 2 and self.target[0] is Chat.id and self.target[1] is Chat.name:
                return self.db.chat_rows
            return self.db.doc_rows

        return []

    def delete(self):
        self.deleted = True
        self.db.query_deleted = True
        return 1


class FakeDB:
    def __init__(
        self,
        chat_result=None,
        chat_rows=None,
        message_rows=None,
        doc_rows=None,
        comment_ids=None,
    ):
        self.chat_result = chat_result
        self.chat_rows = chat_rows or []
        self.message_rows = message_rows or []
        self.doc_rows = doc_rows or []
        self.comment_ids = comment_ids or []
        self.added = []
        self.deleted = []
        self.committed = False
        self.refreshed = []
        self.queries = []
        self.query_deleted = False

    def query(self, *targets):
        target = targets[0] if len(targets) == 1 else targets
        query = FakeQuery(self, target)
        self.queries.append(query)
        return query

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 100 + len(self.added)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime(2026, 5, 16, 10, 0, 0)
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed.append(obj)


class FakeGraph:
    def __init__(self, captured):
        self.captured = captured

    async def ainvoke(self, state):
        self.captured["state"] = state
        return {
            "answer": "answer",
            "chunks": [],
            "comments": [],
        }


def make_user(user_id=3, company_id=1):
    return SimpleNamespace(id=user_id, company_id=company_id, role="user", roles=[])


def make_chat(chat_id=10, user_id=3, company_id=1, name="Chat"):
    return SimpleNamespace(
        id=chat_id,
        user_id=user_id,
        company_id=company_id,
        name=name,
        created_at=datetime(2026, 5, 16, 10, 0, 0),
    )


def make_message(message_id=1, chat_id=10, role=ChatRole.user, content="hello"):
    return SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        role=role,
        content=content,
        citations=[],
        retrieved_chunks=[],
        created_at=datetime(2026, 5, 16, 10, 0, 0),
    )


def test_get_or_create_chat_rejects_user_without_company():
    db = FakeDB()
    user = make_user(company_id=None)

    with pytest.raises(HTTPException) as exc:
        chat_routes.get_or_create_chat(db, chat_id=None, user=user)

    assert exc.value.status_code == 403
    assert exc.value.detail == "User has no company"


def test_get_or_create_chat_creates_chat_for_current_user_company():
    db = FakeDB()
    user = make_user(user_id=7, company_id=4)

    chat, created = chat_routes.get_or_create_chat(db, chat_id=None, user=user)

    assert created is True
    assert chat.name == "New Chat"
    assert chat.user_id == 7
    assert chat.company_id == 4
    assert db.committed is True
    assert db.refreshed == [chat]


def test_get_or_create_chat_returns_existing_owned_chat():
    existing_chat = make_chat(chat_id=12, user_id=7, company_id=4)
    db = FakeDB(chat_result=existing_chat)
    user = make_user(user_id=7, company_id=4)

    chat, created = chat_routes.get_or_create_chat(db, chat_id=12, user=user)

    assert created is False
    assert chat is existing_chat


@pytest.mark.asyncio
async def test_chat_passes_only_accessible_doc_ids_and_current_user_comment_ids(monkeypatch):
    captured = {}
    db = FakeDB(comment_ids=[31, 32])
    current_user = make_user(user_id=7, company_id=4)

    monkeypatch.setattr(chat_routes, "_get_accessible_document_ids", lambda db, current_user, action: [1, 3, 5])
    monkeypatch.setattr(chat_routes, "build_answer_graph", lambda: FakeGraph(captured))
    monkeypatch.setattr(chat_routes.chat_generate_title, "delay", lambda *_args, **_kwargs: None)

    request = ChatRequest(
        query="question",
        doc_ids=[3, 4, 5],
        preview=False,
    )

    response = await chat_routes.chat(request=request, current_user=current_user, db=db)

    assert response.answer == "answer"
    assert captured["state"]["company_id"] == 4
    assert captured["state"]["doc_ids"] == [3, 5]
    assert captured["state"]["comment_ids"] == [31, 32]
    assert captured["state"]["scope"] == "both"


@pytest.mark.asyncio
async def test_chat_passes_empty_doc_ids_when_user_has_no_access(monkeypatch):
    captured = {}
    db = FakeDB(comment_ids=[])
    current_user = make_user(user_id=7, company_id=4)

    monkeypatch.setattr(chat_routes, "_get_accessible_document_ids", lambda db, current_user, action: [])
    monkeypatch.setattr(chat_routes, "build_answer_graph", lambda: FakeGraph(captured))
    monkeypatch.setattr(chat_routes.chat_generate_title, "delay", lambda *_args, **_kwargs: None)

    request = ChatRequest(query="question", doc_ids=None, preview=True)

    response = await chat_routes.chat(request=request, current_user=current_user, db=db)

    assert response.answer == "answer"
    assert captured["state"]["doc_ids"] == []
    assert captured["state"]["comment_ids"] == []


@pytest.mark.asyncio
async def test_list_user_chats_returns_current_user_chats_only():
    db = FakeDB(chat_rows=[make_chat(1), make_chat(2)])
    current_user = make_user(user_id=7, company_id=4)

    result = await chat_routes.list_user_chats(current_user=current_user, db=db)

    assert [item.chat_id for item in result.chats] == [1, 2]
    assert db.queries[0].ordered is True


@pytest.mark.asyncio
async def test_get_chat_history_requires_owned_chat():
    db = FakeDB(chat_result=None)
    current_user = make_user(user_id=7, company_id=4)

    with pytest.raises(HTTPException):
        await chat_routes.get_chat_history(chat_id=99, current_user=current_user, db=db)


@pytest.mark.asyncio
async def test_get_chat_history_returns_messages_for_owned_chat():
    chat = make_chat(chat_id=10, user_id=7, company_id=4)
    messages = [make_message(1), make_message(2, role=ChatRole.assistant, content="answer")]
    db = FakeDB(chat_result=chat, message_rows=messages)
    current_user = make_user(user_id=7, company_id=4)

    result = await chat_routes.get_chat_history(chat_id=10, current_user=current_user, db=db)

    assert result.chat_id == 10
    assert result.name == "Chat"
    assert len(result.messages) == 2


@pytest.mark.asyncio
async def test_update_chat_name_requires_owned_chat():
    db = FakeDB(chat_result=None)
    current_user = make_user(user_id=7, company_id=4)

    with pytest.raises(HTTPException):
        await chat_routes.update_chat_name(
            chat_id=99,
            request=SimpleNamespace(name="New name"),
            current_user=current_user,
            db=db,
        )


@pytest.mark.asyncio
async def test_delete_chat_requires_owned_chat():
    db = FakeDB(chat_result=None)
    current_user = make_user(user_id=7, company_id=4)

    with pytest.raises(HTTPException):
        await chat_routes.delete_chat(chat_id=99, current_user=current_user, db=db)
