from components.embedding import JinaAPIEmbeddings
from components.embedding_service import regenerate_missing_embeddings


class DummyComment:
    def __init__(self, content):
        self.content = content
        self.embedding = None


class DummyReceipt:
    def __init__(self, description):
        self.description = description
        self.description_embedding = None


class DummyQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class DummyDB:
    def __init__(self):
        self.comments = [DummyComment("a")]
        self.receipts = [DummyReceipt("b")]
        self.committed = False

    def query(self, model):
        name = model.__name__
        if name == "Comment":
            return DummyQuery(self.comments)
        return DummyQuery(self.receipts)

    def commit(self):
        self.committed = True


def test_embed_documents_returns_empty_when_request_fails(monkeypatch):
    emb = JinaAPIEmbeddings()
    monkeypatch.setattr("components.embedding.requests.post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert emb.embed_documents(["hello"]) == []


def test_regenerate_missing_embeddings_updates_when_available():
    db = DummyDB()
    updated = regenerate_missing_embeddings(db, lambda text: [0.1, 0.2] if text else None)
    assert updated == 2
    assert db.committed is True
