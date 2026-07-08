#!/usr/bin/env python3
"""Run every pytest suite in the repository.

The project keeps tests in both the top-level ``tests/`` directory and module
local ``backend/**/tests/`` directories. This runner discovers those locations,
sets the import path expected by the existing tests, and forwards any extra
arguments to pytest.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = REPO_ROOT / "backend"
TEST_PATTERNS = ("test_*.py", "*_test.py")


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

    return sorted(test_dirs, key=lambda path: path.relative_to(REPO_ROOT).as_posix())


def test_dir_label(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT)
    if rel == Path("tests"):
        return "root"
    if rel == Path("backend/tests"):
        return "backend"
    if rel.parts[0] == "backend" and rel.parts[-1] == "tests":
        return "/".join(rel.parts[1:-1])
    return rel.as_posix()


def filter_test_dirs(test_dirs: list[Path], module_filters: list[str]) -> list[Path]:
    if not module_filters:
        return test_dirs

    normalized = [item.strip("/").strip() for item in module_filters if item.strip()]
    selected: list[Path] = []
    for path in test_dirs:
        label = test_dir_label(path)
        if any(
            label == module
            or label.startswith(f"{module}/")
            or path.relative_to(REPO_ROOT).as_posix().startswith(module)
            for module in normalized
        ):
            selected.append(path)
    return selected


def configure_environment() -> dict[str, str]:
    env = os.environ.copy()

    # Keep these defaults local to the test process. Real values from the shell
    # still win when a developer wants to run against a specific service.
    defaults = {
        "POSTGRES_DB": "test",
        "POSTGRES_USER": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_IP": "localhost",
        "default_username": "admin",
        "default_password": "admin",
        "default_firstname": "Admin",
        "jwt_secret": "secret",
        "openai_api_key": "test",
        "jina_api_key": "test",
    }
    for key, value in defaults.items():
        env.setdefault(key, value)

    pythonpath_entries = [str(REPO_ROOT), str(BACKEND_ROOT)]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_entries.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    return env


def run_command(command: list[str], env: dict[str, str], cwd: Path) -> int:
    print("Running:", " ".join(command), flush=True)
    return subprocess.run(command, cwd=cwd, env=env, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover and run all pytest suites for every project module."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print discovered test targets without running pytest.",
    )
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Run only a module label, such as 'financial_management', "
            "'assistant', 'shared', 'backend', or 'root'. May be repeated."
        ),
    )
    parser.add_argument(
        "--with-alembic-check",
        action="store_true",
        help="Run 'alembic check' after pytest succeeds.",
    )

    args, pytest_args = parser.parse_known_args(argv)

    test_dirs = filter_test_dirs(discover_test_dirs(), args.module)
    if not test_dirs:
        print("No test directories matched.", file=sys.stderr)
        return 2

    for path in test_dirs:
        print(f"{test_dir_label(path):<28} {path.relative_to(REPO_ROOT)}")

    if args.list:
        return 0

    env = configure_environment()
    pytest_targets = [path.relative_to(REPO_ROOT).as_posix() for path in test_dirs]
    pytest_command = [sys.executable, "-m", "pytest", *pytest_targets, *pytest_args]
    pytest_status = run_command(pytest_command, env, REPO_ROOT)
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
        return run_command(alembic_command, env, BACKEND_ROOT)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
