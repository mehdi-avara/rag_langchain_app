#!/usr/bin/env python3
"""Run repository tests with production-database protections."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = REPO_ROOT / "backend"
TEST_PATTERNS = ("test_*.py", "*_test.py")

SAFE_DATABASE_EXACT_NAMES = {
    "test",
}

SAFE_DATABASE_PREFIXES = (
    "test_",
    "rag_test_",
    "rag_validation_",
    "rag_phase_",
)

PROTECTED_DATABASE_NAMES = {
    "rag",
    "porsa",
    "postgres",
    "production",
    "prod",
    "template0",
    "template1",
}

SAFE_DATABASE_HOSTS = {
    "127.0.0.1",
    "localhost",
    "::1",
    "postgres_pgvector",
}

SAFE_REDIS_HOSTS = {
    "127.0.0.1",
    "localhost",
    "::1",
    "porsa_test_redis",
}

REDIS_ENVIRONMENT_KEYS = {
    "REDIS_URL",
    "REDIS_HOST",
    "REDIS_IP",
    "REDIS_PORT",
}

DATABASE_ENVIRONMENT_KEYS = {
    "DATABASE_URL",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_IP",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "DATABASE_NAME",
}


def has_test_files(path: Path) -> bool:
    return path.is_dir() and any(
        candidate.is_file()
        for pattern in TEST_PATTERNS
        for candidate in path.rglob(pattern)
    )


def discover_test_dirs() -> list[Path]:
    test_dirs: set[Path] = set()

    root_tests = REPO_ROOT / "tests"

    if has_test_files(root_tests):
        test_dirs.add(root_tests)

    if BACKEND_ROOT.exists():
        for path in BACKEND_ROOT.rglob("tests"):
            if "__pycache__" in path.parts:
                continue

            if has_test_files(path):
                test_dirs.add(path)

    return sorted(
        test_dirs,
        key=lambda path: path.relative_to(
            REPO_ROOT
        ).as_posix(),
    )


def test_dir_label(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT)

    if relative == Path("tests"):
        return "root"

    if relative == Path("backend/tests"):
        return "backend"

    if (
        relative.parts
        and relative.parts[0] == "backend"
        and relative.parts[-1] == "tests"
    ):
        return "/".join(relative.parts[1:-1])

    return relative.as_posix()


def filter_test_dirs(
    test_dirs: list[Path],
    module_filters: list[str],
) -> list[Path]:
    if not module_filters:
        return test_dirs

    normalized = [
        item.strip().strip("/")
        for item in module_filters
        if item.strip()
    ]

    selected: list[Path] = []

    for path in test_dirs:
        label = test_dir_label(path)
        relative = path.relative_to(
            REPO_ROOT
        ).as_posix()

        if any(
            label == module
            or label.startswith(f"{module}/")
            or relative.startswith(module)
            for module in normalized
        ):
            selected.append(path)

    return selected


def validate_database_name(
    database_name: str,
    source: str,
) -> str:
    normalized = database_name.strip().lower()

    if not normalized:
        raise RuntimeError(
            f"{source} contains an empty database name"
        )

    if normalized in PROTECTED_DATABASE_NAMES:
        raise RuntimeError(
            f"{source} references protected database "
            f"{database_name!r}"
        )

    allowed = (
        normalized in SAFE_DATABASE_EXACT_NAMES
        or any(
            normalized.startswith(prefix)
            for prefix in SAFE_DATABASE_PREFIXES
        )
    )

    if not allowed:
        raise RuntimeError(
            f"{source} database name {database_name!r} "
            "does not use an approved test or validation prefix"
        )

    return database_name


def parse_test_database_url(
    database_url: str,
    source: str,
):
    parsed = urlparse(database_url)

    if parsed.scheme not in {
        "postgres",
        "postgresql",
        "postgresql+psycopg",
        "postgresql+psycopg2",
    }:
        raise RuntimeError(
            f"{source} must use a PostgreSQL URL"
        )

    hostname = parsed.hostname or ""

    if hostname not in SAFE_DATABASE_HOSTS:
        raise RuntimeError(
            f"{source} uses disallowed database host "
            f"{hostname!r}"
        )

    database_name = unquote(
        parsed.path.lstrip("/")
    ).strip()

    validate_database_name(
        database_name,
        source,
    )

    return parsed, database_name


def parse_test_redis_url(
    redis_url: str,
    source: str,
):
    parsed = urlparse(redis_url)

    if parsed.scheme not in {
        "redis",
        "rediss",
    }:
        raise RuntimeError(
            f"{source} must use a Redis URL"
        )

    hostname = parsed.hostname or ""

    if hostname not in SAFE_REDIS_HOSTS:
        raise RuntimeError(
            f"{source} uses disallowed Redis host "
            f"{hostname!r}"
        )

    if parsed.query or parsed.fragment:
        raise RuntimeError(
            f"{source} must not contain a query "
            "or fragment"
        )

    try:
        port = parsed.port or 6379
    except ValueError as exc:
        raise RuntimeError(
            f"{source} contains an invalid Redis port"
        ) from exc

    if port < 1 or port > 65535:
        raise RuntimeError(
            f"{source} contains an invalid Redis port"
        )

    database_value = unquote(
        parsed.path.lstrip("/")
    ).strip()

    if database_value:
        try:
            database_index = int(database_value)
        except ValueError as exc:
            raise RuntimeError(
                f"{source} contains an invalid Redis "
                "database index"
            ) from exc
    else:
        database_index = 0

    if database_index < 0:
        raise RuntimeError(
            f"{source} contains a negative Redis "
            "database index"
        )

    return parsed, database_index


def clear_inherited_database_environment(
    environment: dict[str, str],
) -> None:
    for key in list(environment):
        upper = key.upper()

        if (
            upper in DATABASE_ENVIRONMENT_KEYS
            or upper.endswith("DATABASE_URL")
        ):
            environment.pop(key, None)


def clear_inherited_redis_environment(
    environment: dict[str, str],
) -> None:
    for key, value in list(
        environment.items()
    ):
        upper = key.upper()
        normalized_value = (
            value.strip().lower()
            if isinstance(value, str)
            else ""
        )

        if (
            upper in REDIS_ENVIRONMENT_KEYS
            or upper.endswith("REDIS_URL")
            or normalized_value.startswith(
                (
                    "redis://",
                    "rediss://",
                )
            )
        ):
            environment.pop(key, None)


def configure_environment(
    *,
    use_test_database: bool,
    enable_populated_migration_tests: bool,
) -> tuple[dict[str, str], str]:
    environment = os.environ.copy()

    explicit_database_url = environment.pop(
        "PORSA_TEST_DATABASE_URL",
        "",
    ).strip()

    explicit_redis_url = environment.pop(
        "PORSA_TEST_REDIS_URL",
        "",
    ).strip()

    clear_inherited_database_environment(
        environment
    )

    clear_inherited_redis_environment(
        environment
    )

    environment.update(
        {
            "APP_ENV": "test",
            "ENVIRONMENT": "test",
            "POSTGRES_DB": "test",
            "POSTGRES_USER": "test",
            "POSTGRES_PASSWORD": "test",
            "POSTGRES_IP": "127.0.0.1",
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "1",
            "DB_NAME": "test",
            "DB_USER": "test",
            "DB_PASSWORD": "test",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "1",
            "DATABASE_NAME": "test",
            "default_username": "test_admin",
            "default_password": "test_password",
            "default_firstname": "Test",
            "jwt_secret": "test-only-secret",
            "openai_api_key": "test",
            "jina_api_key": "test",
            "OPENAI_API_KEY": "test",
            "JINA_API_KEY": "test",
            "REDIS_URL": (
                "redis://127.0.0.1:1/0"
            ),
            "redis_url": (
                "redis://127.0.0.1:1/0"
            ),
            "S3_ACCESS_KEY_ID": "test",
            "s3_access_key_id": "test",
            "S3_SECRET_ACCESS_KEY": "test",
            "s3_secret_access_key": "test",
            "SEC3C_ENV_EXAMPLE_PATH": str(
                REPO_ROOT / ".env.example"
            ),
            "SEC3D_ENV_EXAMPLE_PATH": str(
                REPO_ROOT / ".env.example"
            ),
            "SEC3D_PRIMARY_COMPOSE_PATH": str(
                REPO_ROOT / "docker-compose.yml"
            ),
            "SEC3D_LANGFUSE_COMPOSE_PATH": str(
                REPO_ROOT
                / "docker-compose-langfuse.yml"
            ),
            "CORS_ALLOW_ORIGINS": (
                '["https://porsa.mahta-tech.com"]'
            ),
            "cors_allow_origins": (
                '["https://porsa.mahta-tech.com"]'
            ),
            "CORS_ALLOW_CREDENTIALS": "true",
            "cors_allow_credentials": "true",
        }
    )

    database_mode = "isolated-placeholders"

    if use_test_database:
        if not explicit_database_url:
            raise RuntimeError(
                "--use-test-database requires "
                "PORSA_TEST_DATABASE_URL"
            )

        parsed, database_name = (
            parse_test_database_url(
                explicit_database_url,
                "PORSA_TEST_DATABASE_URL",
            )
        )

        port = parsed.port or 5432
        username = unquote(
            parsed.username or ""
        )
        password = unquote(
            parsed.password or ""
        )
        hostname = parsed.hostname or ""

        environment.update(
            {
                "DATABASE_URL": explicit_database_url,
                "POSTGRES_DB": database_name,
                "POSTGRES_USER": username,
                "POSTGRES_PASSWORD": password,
                "POSTGRES_IP": hostname,
                "POSTGRES_HOST": hostname,
                "POSTGRES_PORT": str(port),
                "DB_NAME": database_name,
                "DB_USER": username,
                "DB_PASSWORD": password,
                "DB_HOST": hostname,
                "DB_PORT": str(port),
                "DATABASE_NAME": database_name,
            }
        )

        if enable_populated_migration_tests:
            environment[
                "PHASE_1_2_POPULATED_TEST_DATABASE_URL"
            ] = explicit_database_url

        database_mode = (
            f"explicit-validation:{database_name}"
        )

    elif enable_populated_migration_tests:
        raise RuntimeError(
            "--enable-populated-migration-tests "
            "requires --use-test-database"
        )

    redis_mode = "isolated-placeholder"

    if explicit_redis_url:
        parsed_redis, redis_database_index = (
            parse_test_redis_url(
                explicit_redis_url,
                "PORSA_TEST_REDIS_URL",
            )
        )

        redis_port = parsed_redis.port or 6379

        environment.update(
            {
                "REDIS_URL": explicit_redis_url,
                "redis_url": explicit_redis_url,
            }
        )

        redis_mode = (
            "explicit-validation:"
            f"{parsed_redis.hostname}:"
            f"{redis_port}/"
            f"{redis_database_index}"
        )

    environment[
        "PORSA_TEST_REDIS_MODE"
    ] = redis_mode

    pythonpath_entries = [
        str(REPO_ROOT),
        str(BACKEND_ROOT),
    ]

    existing_pythonpath = environment.get(
        "PYTHONPATH"
    )

    if existing_pythonpath:
        pythonpath_entries.append(
            existing_pythonpath
        )

    environment["PYTHONPATH"] = os.pathsep.join(
        pythonpath_entries
    )

    validate_environment(environment)

    return environment, database_mode


def validate_environment(
    environment: dict[str, str],
) -> None:
    for key, value in environment.items():
        upper = key.upper()

        if upper in {
            "POSTGRES_DB",
            "DB_NAME",
            "DATABASE_NAME",
        }:
            validate_database_name(
                value,
                key,
            )

        if upper.endswith("DATABASE_URL"):
            parse_test_database_url(
                value,
                key,
            )

        if upper == "REDIS_URL":
            parse_test_redis_url(
                value,
                key,
            )


def run_command(
    command: list[str],
    environment: dict[str, str],
    cwd: Path,
) -> int:
    print(
        "Running:",
        " ".join(command),
        flush=True,
    )

    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
    ).returncode


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Discover and run repository tests with "
            "production-database protections."
        )
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List test targets without running pytest.",
    )

    parser.add_argument(
        "--module",
        action="append",
        default=[],
        metavar="NAME",
        help="Run only selected module labels.",
    )

    parser.add_argument(
        "--use-test-database",
        action="store_true",
        help=(
            "Use the validated database URL from "
            "PORSA_TEST_DATABASE_URL."
        ),
    )

    parser.add_argument(
        "--enable-populated-migration-tests",
        action="store_true",
        help=(
            "Enable populated migration tests using "
            "the approved validation database URL."
        ),
    )

    parser.add_argument(
        "--with-alembic-check",
        action="store_true",
        help=(
            "Run alembic check after pytest. "
            "Requires --use-test-database."
        ),
    )

    args, pytest_args = parser.parse_known_args(
        argv
    )

    if (
        args.with_alembic_check
        and not args.use_test_database
    ):
        parser.error(
            "--with-alembic-check requires "
            "--use-test-database"
        )

    try:
        environment, database_mode = (
            configure_environment(
                use_test_database=(
                    args.use_test_database
                ),
                enable_populated_migration_tests=(
                    args.enable_populated_migration_tests
                ),
            )
        )
    except RuntimeError as exc:
        parser.error(str(exc))

    test_dirs = filter_test_dirs(
        discover_test_dirs(),
        args.module,
    )

    if not test_dirs:
        print(
            "No test directories matched.",
            file=sys.stderr,
        )
        return 2

    print(f"Database mode: {database_mode}")
    print(
        "Redis mode: "
        + environment[
            "PORSA_TEST_REDIS_MODE"
        ]
    )

    for path in test_dirs:
        print(
            f"{test_dir_label(path):<28} "
            f"{path.relative_to(REPO_ROOT)}"
        )

    if args.list:
        return 0

    root_test_dirs: list[Path] = []
    backend_test_dirs: list[Path] = []

    for path in test_dirs:
        if path == REPO_ROOT / "tests":
            root_test_dirs.append(path)
            continue

        try:
            path.relative_to(BACKEND_ROOT)
        except ValueError:
            print(
                "Unsupported test directory outside "
                f"the root/backend phase model: {path}",
                file=sys.stderr,
            )
            return 2

        backend_test_dirs.append(path)

    phases = (
        (
            "root",
            root_test_dirs,
            REPO_ROOT,
        ),
        (
            "backend",
            backend_test_dirs,
            BACKEND_ROOT,
        ),
    )

    for phase_name, phase_dirs, phase_root in phases:
        if not phase_dirs:
            continue

        pytest_targets = [
            path.relative_to(
                phase_root
            ).as_posix()
            for path in phase_dirs
        ]

        print(
            f"Pytest phase: {phase_name}",
            flush=True,
        )

        pytest_command = [
            sys.executable,
            "-m",
            "pytest",
            *pytest_targets,
            *pytest_args,
        ]

        pytest_status = run_command(
            pytest_command,
            environment,
            phase_root,
        )

        if pytest_status != 0:
            return pytest_status

    if args.with_alembic_check:
        alembic_command = [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(BACKEND_ROOT / "alembic.ini"),
            "check",
        ]

        return run_command(
            alembic_command,
            environment,
            BACKEND_ROOT,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
