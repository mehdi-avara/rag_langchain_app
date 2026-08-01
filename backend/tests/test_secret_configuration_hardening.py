from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path


SENSITIVE_EXAMPLE_KEYS = {
    "POSTGRES_PASSWORD",
    "jwt_secret",
    "openai_api_key",
    "embedding_api_key",
    "jina_api_key",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    for raw_line in path.read_text(
        encoding="utf-8",
    ).splitlines():
        line = raw_line.strip()

        if (
            not line
            or line.startswith("#")
            or "=" not in line
        ):
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    return values


def test_sensitive_settings_have_no_insecure_defaults() -> None:
    settings_path = (
        Path(__file__).resolve().parents[1]
        / "settings.py"
    )

    tree = ast.parse(
        settings_path.read_text(
            encoding="utf-8",
        ),
        filename=str(settings_path),
    )

    assignments: dict[str, ast.AnnAssign] = {}

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        if node.name != "Settings":
            continue

        for item in node.body:
            if (
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
            ):
                assignments[item.target.id] = item

    embedding = assignments["embedding_api_key"]

    assert isinstance(
        embedding.value,
        ast.Constant,
    )
    assert embedding.value.value == ""

    assert (
        assignments["S3_ACCESS_KEY_ID"].value
        is None
    )
    assert (
        assignments["S3_SECRET_ACCESS_KEY"].value
        is None
    )


def test_env_example_contains_no_secret_values() -> None:
    path = Path(
        os.environ[
            "SEC3D_ENV_EXAMPLE_PATH"
        ]
    )

    values = parse_env(path)

    for key in SENSITIVE_EXAMPLE_KEYS:
        assert key in values
        assert values[key] == ""


def test_primary_compose_requires_runtime_credentials() -> None:
    path = Path(
        os.environ[
            "SEC3D_PRIMARY_COMPOSE_PATH"
        ]
    )

    source = path.read_text(
        encoding="utf-8",
    )

    assert (
        "${POSTGRES_PASSWORD}"
        not in source
    )
    assert (
        "${MINIO_ROOT_PASSWORD}"
        not in source
    )

    assert (
        "${POSTGRES_PASSWORD:?"
        in source
    )
    assert (
        "${MINIO_ROOT_PASSWORD:?"
        in source
    )


def test_langfuse_compose_has_no_secret_fallbacks() -> None:
    path = Path(
        os.environ[
            "SEC3D_LANGFUSE_COMPOSE_PATH"
        ]
    )

    source = path.read_text(
        encoding="utf-8",
    )

    sensitive_fallback = re.compile(
        r"\$\{"
        r"[A-Za-z_][A-Za-z0-9_]*"
        r"(?:PASSWORD|SECRET|ACCESS_KEY|DATABASE_URL)"
        r"[A-Za-z0-9_]*"
        r":-[^}]*"
        r"\}",
        re.IGNORECASE,
    )

    assert not sensitive_fallback.search(source)

    required_variables = {
        "LANGFUSE_DATABASE_URL",
        "CLICKHOUSE_PASSWORD",
        "LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID",
        "LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY",
        "LANGFUSE_S3_MEDIA_UPLOAD_ACCESS_KEY_ID",
        "LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY",
        "LANGFUSE_S3_BATCH_EXPORT_ACCESS_KEY_ID",
        "LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY",
        "NEXTAUTH_SECRET",
        "LANGFUSE_INIT_PROJECT_SECRET_KEY",
        "LANGFUSE_INIT_USER_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "POSTGRES_PASSWORD",
    }

    for variable in required_variables:
        assert f"${{{variable}:?" in source


def test_notebook_contains_no_saved_outputs() -> None:
    notebook_path = (
        Path(__file__).resolve().parents[1]
        / "test.ipynb"
    )

    notebook = json.loads(
        notebook_path.read_text(
            encoding="utf-8",
        )
    )

    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue

        assert cell.get("outputs", []) == []
        assert cell.get("execution_count") is None


def test_notebook_contains_no_credential_url() -> None:
    notebook_path = (
        Path(__file__).resolve().parents[1]
        / "test.ipynb"
    )

    source = notebook_path.read_text(
        encoding="utf-8",
    )

    credential_url = re.compile(
        r"(?i)"
        r"(?:postgres(?:ql)?|mysql|mariadb|redis|"
        r"mongodb|amqp)://"
        r"[^/\s:@]+:[^@\s/]+@"
    )

    assert not credential_url.search(source)
