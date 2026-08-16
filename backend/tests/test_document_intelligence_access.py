import inspect
import os
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

os.environ.setdefault(
    "POSTGRES_DB",
    "test",
)
os.environ.setdefault(
    "POSTGRES_USER",
    "test",
)
os.environ.setdefault(
    "POSTGRES_PASSWORD",
    "test",
)
os.environ.setdefault(
    "POSTGRES_IP",
    "localhost",
)
os.environ.setdefault(
    "default_username",
    "admin",
)
os.environ.setdefault(
    "default_password",
    "admin123456",
)
os.environ.setdefault(
    "default_firstname",
    "Admin",
)
os.environ.setdefault(
    "jwt_secret",
    "test-secret",
)
os.environ.setdefault(
    "openai_api_key",
    "test",
)
os.environ.setdefault(
    "jina_api_key",
    "test",
)

from document_intelligence import routes as di_routes
from document_intelligence.models import (
    DIModelCreationSuggestion,
    DocumentIntelligenceJob,
    DocumentIntelligenceLabel,
    DocumentSegment,
    DocumentSegmentSuggestion,
)
from document_intelligence.schemas import (
    JobCreate,
    ModelCreationSuggestionPatch,
    SegmentPatch,
    SuggestionPatch,
)


class FakeQuery:
    def __init__(
        self,
        db,
        target,
    ):
        self.db = db
        self.target = target

    def join(
        self,
        *args,
        **kwargs,
    ):
        return self

    def filter(
        self,
        *args,
        **kwargs,
    ):
        return self

    def order_by(
        self,
        *args,
        **kwargs,
    ):
        return self

    def offset(
        self,
        *args,
        **kwargs,
    ):
        return self

    def limit(
        self,
        *args,
        **kwargs,
    ):
        return self

    def first(self):
        return self.db.first_results.get(
            self.target
        )

    def all(self):
        return list(
            self.db.all_results.get(
                self.target,
                [],
            )
        )


class FakeDB:
    def __init__(
        self,
        *,
        first_results=None,
        all_results=None,
    ):
        self.first_results = (
            first_results or {}
        )
        self.all_results = (
            all_results or {}
        )
        self.added = []
        self.commits = 0
        self.refreshed = []

    def query(
        self,
        target,
    ):
        return FakeQuery(
            self,
            target,
        )

    def add(
        self,
        value,
    ):
        self.added.append(
            value
        )

    def commit(self):
        self.commits += 1

    def refresh(
        self,
        value,
    ):
        self.refreshed.append(
            value
        )


def make_user(
    user_id=3,
    company_id=1,
):
    return SimpleNamespace(
        id=user_id,
        company_id=company_id,
    )


def deny_access(
    *args,
    **kwargs,
):
    raise HTTPException(
        status_code=404,
        detail="Document not found",
    )


@pytest.mark.parametrize(
    (
        "function_name",
        "permission",
    ),
    [
        (
            "create_job",
            "documents:update",
        ),
        (
            "list_jobs",
            "documents:read",
        ),
        (
            "get_job",
            "documents:read",
        ),
        (
            "list_jobs_for_document",
            "documents:read",
        ),
        (
            "get_page_artifacts",
            "documents:read",
        ),
        (
            "list_segments_for_document",
            "documents:read",
        ),
        (
            "get_segment",
            "documents:read",
        ),
        (
            "patch_segment",
            "documents:update",
        ),
        (
            "list_suggestions_for_segment",
            "documents:read",
        ),
        (
            "patch_suggestion",
            "documents:update",
        ),
        (
            "list_model_creation_suggestions",
            "documents:read",
        ),
        (
            "patch_model_creation_suggestion",
            "documents:update",
        ),
        (
            "export_gold_labels",
            "documents:update",
        ),
    ],
)
def test_di_routes_declare_document_permission(
    function_name,
    permission,
):
    function = getattr(
        di_routes,
        function_name,
    )

    source = "".join(
        inspect.getsource(
            function
        ).split()
    )

    assert (
        f'require_permission("{permission}")'
        in source
    )


def test_create_job_denied_before_mutation(
    monkeypatch,
):
    db = FakeDB()
    user = make_user()

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.create_job(
            payload=JobCreate(
                document_id=99,
                methods_requested=[
                    "llm_vlm"
                ],
            ),
            background_tasks=BackgroundTasks(),
            db=db,
            current_user=user,
        )

    assert exc.value.status_code == 404
    assert db.added == []
    assert db.commits == 0


def test_create_job_uses_update_access(
    monkeypatch,
):
    calls = []
    db = FakeDB()
    user = make_user()

    def allow(
        db_arg,
        document_id,
        user_arg,
        action,
    ):
        calls.append(
            (
                db_arg,
                document_id,
                user_arg,
                action,
            )
        )

        return SimpleNamespace(
            id=document_id
        )

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        allow,
    )

    background_tasks = (
        BackgroundTasks()
    )

    result = di_routes.create_job(
        payload=JobCreate(
            document_id=10,
            methods_requested=[
                "llm_vlm"
            ],
        ),
        background_tasks=background_tasks,
        db=db,
        current_user=user,
    )

    assert calls == [
        (
            db,
            10,
            user,
            "update",
        )
    ]
    assert result.document_id == 10
    assert result.triggered_by_user_id == 3
    assert db.added == [result]
    assert db.commits == 1
    assert len(
        background_tasks.tasks
    ) == 1


def test_list_jobs_uses_read_access_scope(
    monkeypatch,
):
    job = SimpleNamespace(
        id=1,
        document_id=10,
    )
    db = FakeDB(
        all_results={
            DocumentIntelligenceJob: [
                job
            ]
        }
    )
    user = make_user()
    calls = []

    def allowed_ids(
        db_arg,
        user_arg,
        action,
    ):
        calls.append(
            (
                db_arg,
                user_arg,
                action,
            )
        )

        return [10]

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document_ids",
        allowed_ids,
    )

    result = di_routes.list_jobs(
        document_id=None,
        limit=20,
        offset=0,
        db=db,
        current_user=user,
    )

    assert calls == [
        (
            db,
            user,
            "read",
        )
    ]
    assert result == [job]


def test_list_jobs_foreign_document_filter_is_hidden(
    monkeypatch,
):
    db = FakeDB()
    user = make_user()

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document_ids",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.list_jobs(
            document_id=99,
            limit=20,
            offset=0,
            db=db,
            current_user=user,
        )

    assert exc.value.status_code == 404


def test_get_job_uses_read_document_access(
    monkeypatch,
):
    job = SimpleNamespace(
        id=8,
        document_id=44,
    )
    db = FakeDB(
        first_results={
            DocumentIntelligenceJob: job
        }
    )
    user = make_user()
    calls = []

    def allow(
        db_arg,
        document_id,
        user_arg,
        action,
    ):
        calls.append(
            (
                document_id,
                action,
            )
        )

        return SimpleNamespace(
            id=document_id
        )

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        allow,
    )

    result = di_routes.get_job(
        job_id=8,
        db=db,
        current_user=user,
    )

    assert result is job
    assert calls == [
        (
            44,
            "read",
        )
    ]


def test_get_job_cross_tenant_is_hidden(
    monkeypatch,
):
    job = SimpleNamespace(
        id=8,
        document_id=44,
    )
    db = FakeDB(
        first_results={
            DocumentIntelligenceJob: job
        }
    )

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.get_job(
            job_id=8,
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404


def test_patch_segment_denied_before_mutation(
    monkeypatch,
):
    segment = SimpleNamespace(
        id=5,
        document_id=44,
        title="original",
        status="predicted",
        reviewed_by_user_id=None,
        reviewed_at=None,
    )
    db = FakeDB(
        first_results={
            DocumentSegment: segment
        }
    )

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.patch_segment(
            segment_id=5,
            payload=SegmentPatch(
                title="foreign mutation"
            ),
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404
    assert segment.title == "original"
    assert db.commits == 0


def test_patch_suggestion_denied_before_mutation(
    monkeypatch,
):
    suggestion = SimpleNamespace(
        id=7,
        segment_id=5,
        status="pending",
        reviewed_by_user_id=None,
        reviewed_at=None,
    )
    segment = SimpleNamespace(
        id=5,
        document_id=44,
    )
    db = FakeDB(
        first_results={
            DocumentSegmentSuggestion: (
                suggestion
            ),
            DocumentSegment: segment,
        }
    )

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.patch_suggestion(
            suggestion_id=7,
            payload=SuggestionPatch(
                status="accepted"
            ),
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404
    assert suggestion.status == "pending"
    assert db.commits == 0


def test_patch_model_suggestion_denied_before_mutation(
    monkeypatch,
):
    suggestion = SimpleNamespace(
        id=9,
        document_id=44,
        status="pending",
        manufacturer="original",
        model_name="original",
        description="original",
        reviewed_by_user_id=None,
        reviewed_at=None,
    )
    db = FakeDB(
        first_results={
            DIModelCreationSuggestion: (
                suggestion
            )
        }
    )

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.patch_model_creation_suggestion(
            suggestion_id=9,
            payload=(
                ModelCreationSuggestionPatch(
                    status="accepted",
                    manufacturer="foreign",
                )
            ),
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404
    assert suggestion.status == "pending"
    assert suggestion.manufacturer == "original"
    assert db.commits == 0


def test_export_labels_denied_before_mutation(
    monkeypatch,
):
    job = SimpleNamespace(
        id=8,
        document_id=44,
    )
    db = FakeDB(
        first_results={
            DocumentIntelligenceJob: job,
            DocumentIntelligenceLabel: None,
        }
    )

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.export_gold_labels(
            job_id=8,
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404
    assert db.added == []
    assert db.commits == 0


def test_list_jobs_for_document_cross_tenant_is_hidden(
    monkeypatch,
):
    db = FakeDB()

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.list_jobs_for_document(
            doc_id=99,
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404


def test_page_artifacts_cross_tenant_are_hidden(
    monkeypatch,
):
    db = FakeDB()

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.get_page_artifacts(
            doc_id=99,
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404


def test_document_segments_cross_tenant_are_hidden(
    monkeypatch,
):
    db = FakeDB()

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.list_segments_for_document(
            doc_id=99,
            job_id=None,
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404


def test_segment_suggestions_cross_tenant_are_hidden(
    monkeypatch,
):
    segment = SimpleNamespace(
        id=5,
        document_id=99,
    )

    db = FakeDB(
        first_results={
            DocumentSegment: segment,
        }
    )

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.list_suggestions_for_segment(
            segment_id=5,
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404


def test_model_suggestions_cross_tenant_are_hidden(
    monkeypatch,
):
    job = SimpleNamespace(
        id=8,
        document_id=99,
    )

    db = FakeDB(
        first_results={
            DocumentIntelligenceJob: job,
        }
    )

    monkeypatch.setattr(
        di_routes,
        "get_accessible_document",
        deny_access,
    )

    with pytest.raises(
        HTTPException
    ) as exc:
        di_routes.list_model_creation_suggestions(
            job_id=8,
            db=db,
            current_user=make_user(),
        )

    assert exc.value.status_code == 404
