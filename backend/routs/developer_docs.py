from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from Models import User
from deps import require_permission


router = APIRouter()

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs"


class DeveloperDocOut(BaseModel):
    path: str
    name: str
    size_bytes: int


def _resolve_doc_path(doc_path: str) -> Path:
    if any(part.startswith(".") for part in Path(doc_path).parts):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documentation file not found",
        )

    requested_path = (DOCS_ROOT / doc_path).resolve()

    if (
        not requested_path.is_relative_to(DOCS_ROOT.resolve())
        or not requested_path.is_file()
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documentation file not found",
        )

    return requested_path


@router.get("/developer-docs", response_model=list[DeveloperDocOut])
def list_developer_docs(
    current_user: User = Depends(require_permission("developer_docs:read")),
):
    if not DOCS_ROOT.exists():
        return []

    docs = []

    for path in sorted(DOCS_ROOT.rglob("*")):
        if path.is_file() and not any(
            part.startswith(".") for part in path.relative_to(DOCS_ROOT).parts
        ):
            docs.append(
                DeveloperDocOut(
                    path=path.relative_to(DOCS_ROOT).as_posix(),
                    name=path.name,
                    size_bytes=path.stat().st_size,
                )
            )

    return docs


@router.get("/developer-docs/{doc_path:path}")
def get_developer_doc(
    doc_path: str,
    current_user: User = Depends(require_permission("developer_docs:read")),
):
    path = _resolve_doc_path(doc_path)
    return FileResponse(path, filename=path.name)
