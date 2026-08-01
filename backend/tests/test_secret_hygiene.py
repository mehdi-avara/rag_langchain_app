from __future__ import annotations

import ast
from pathlib import Path
import re


BACKEND_ROOT = Path(__file__).resolve().parents[1]
HF_TOKEN_PATTERN = re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names: list[str] = []

    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)

    return names


def test_legacy_core_security_module_is_removed() -> None:
    assert not (BACKEND_ROOT / "core" / "security.py").exists()


def test_backend_has_no_huggingface_token_literals() -> None:
    findings: list[str] = []

    for path in BACKEND_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue

        source = path.read_text(encoding="utf-8", errors="replace")

        if HF_TOKEN_PATTERN.search(source):
            findings.append(str(path.relative_to(BACKEND_ROOT)))

    assert findings == []


def test_backend_has_no_literal_secret_key_assignment() -> None:
    findings: list[str] = []

    for path in BACKEND_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue

        source = path.read_text(encoding="utf-8", errors="replace")

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue

            value = node.value

            if not isinstance(value, ast.Constant):
                continue

            if not isinstance(value.value, str):
                continue

            names = _assignment_names(node)

            if "SECRET_KEY" in names and value.value.strip():
                findings.append(
                    f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}"
                )

    assert findings == []
