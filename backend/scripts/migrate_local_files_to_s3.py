from __future__ import annotations

from pathlib import Path
import hashlib
import mimetypes
import os
import sys
from datetime import datetime

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from sqlalchemy import text
from botocore.exceptions import ClientError

from db.session import db_session
from settings import get_settings
from Models import Document, FileAsset, FileAssetStatus, User
from storage.manager import StorageManager

settings = get_settings()
base = Path(settings.files_dir)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def content_type_for(filename: str) -> str:
    ct, _ = mimetypes.guess_type(filename)
    return ct or "application/octet-stream"


def doc_local_path(doc: Document) -> Path | None:
    candidates = [base / str(doc.id) / "original.pdf"]
    if doc.file_path:
        candidates.append(base / str(doc.file_path) / "original.pdf")
    seen = set()
    for p in candidates:
        if str(p) in seen:
            continue
        seen.add(str(p))
        if p.exists() and p.is_file():
            return p
    return None


def resolve_local_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    p = Path(path_value)
    if not p.is_absolute():
        p = base / p
    if p.exists() and p.is_file():
        return p
    return None


def create_ready_asset_from_local_file(
    db,
    manager: StorageManager,
    *,
    owner: User,
    path: Path,
    filename: str,
    content_type: str,
    purpose: str,
    checksum: str,
) -> FileAsset:
    size_bytes = path.stat().st_size

    asset = FileAsset(
        owner_id=owner.id,
        company_id=owner.company_id,
        original_filename=Path(filename or path.name).name,
        content_type=content_type,
        size_bytes=size_bytes,
        checksum=checksum,
        bucket=manager.bucket,
        storage_key="pending",
        storage_backend="s3",
        status=FileAssetStatus.PENDING.value,
        purpose=purpose,
    )

    db.add(asset)
    db.flush()

    asset.storage_key = f"companies/{owner.company_id}/assets/{asset.id}/original"
    db.commit()
    db.refresh(asset)

    try:
        manager._ensure_bucket()
        manager.client.upload_file(
            str(path),
            asset.bucket,
            asset.storage_key,
            ExtraArgs={"ContentType": asset.content_type},
        )
        metadata = manager.client.head_object(Bucket=asset.bucket, Key=asset.storage_key)
    except ClientError as exc:
        asset.status = FileAssetStatus.FAILED.value
        asset.error_message = str(exc)
        db.commit()
        raise

    actual_size = int(metadata.get("ContentLength") or 0)
    if actual_size != size_bytes:
        asset.status = FileAssetStatus.FAILED.value
        asset.error_message = f"Size mismatch. expected={size_bytes}, actual={actual_size}"
        db.commit()
        raise RuntimeError(asset.error_message)

    asset.status = FileAssetStatus.READY.value
    asset.error_message = None
    asset.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(asset)

    return asset


def migrate_document(db, manager, doc: Document, dry_run: bool):
    owner = db.query(User).filter(User.id == doc.owner_id).first()
    path = doc_local_path(doc)

    if not owner or owner.company_id is None:
        print({"kind": "document", "doc_id": doc.id, "skip": "missing owner/company"})
        return

    if not path:
        print({"kind": "document", "doc_id": doc.id, "skip": "local file not found"})
        return

    checksum = sha256_file(path)

    info = {
        "kind": "document",
        "doc_id": doc.id,
        "filename": doc.filename,
        "owner_id": owner.id,
        "company_id": owner.company_id,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "content_type": "application/pdf",
        "checksum_sha256": checksum,
        "dry_run": dry_run,
    }
    print(info)

    if dry_run:
        return

    asset = create_ready_asset_from_local_file(
        db,
        manager,
        owner=owner,
        path=path,
        filename=doc.filename,
        content_type="application/pdf",
        purpose="document_original_pdf",
        checksum=checksum,
    )

    doc.original_asset_id = asset.id
    if not doc.file_path:
        doc.file_path = str(doc.id)
    db.commit()

    print({"kind": "document", "doc_id": doc.id, "asset_id": asset.id, "status": "migrated"})


def migrate_comment_file(db, manager, row, dry_run: bool):
    owner = db.query(User).filter(User.id == row["user_id"]).first()
    path = resolve_local_path(row["media_address"])

    if not owner or owner.company_id is None:
        print({"kind": "comment_file", "file_id": row["id"], "skip": "missing owner/company"})
        return

    if not path:
        print({"kind": "comment_file", "file_id": row["id"], "skip": "local file not found"})
        return

    checksum = sha256_file(path)
    content_type = content_type_for(row["file_name"])

    info = {
        "kind": "comment_file",
        "file_id": row["id"],
        "comment_id": row["comment_id"],
        "filename": row["file_name"],
        "owner_id": owner.id,
        "company_id": owner.company_id,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "content_type": content_type,
        "checksum_sha256": checksum,
        "dry_run": dry_run,
    }
    print(info)

    if dry_run:
        return

    asset = create_ready_asset_from_local_file(
        db,
        manager,
        owner=owner,
        path=path,
        filename=row["file_name"],
        content_type=content_type,
        purpose=f"comment:{row['comment_id']}",
        checksum=checksum,
    )

    db.execute(
        text("UPDATE comment_files SET asset_id = :asset_id, media_address = :media_address WHERE id = :file_id"),
        {
            "asset_id": asset.id,
            "media_address": asset.storage_key,
            "file_id": row["id"],
        },
    )
    db.commit()

    print({"kind": "comment_file", "file_id": row["id"], "asset_id": asset.id, "status": "migrated"})


def main():
    dry_run = os.getenv("DRY_RUN", "true").lower() != "false"
    migrate_kind = os.getenv("MIGRATE_KIND", "all").lower()
    migrate_id = os.getenv("MIGRATE_ID")

    if migrate_kind not in {"all", "document", "comment"}:
        raise SystemExit("MIGRATE_KIND must be all, document, or comment")

    print("DRY_RUN =", dry_run)
    print("MIGRATE_KIND =", migrate_kind)
    print("MIGRATE_ID =", migrate_id)

    with db_session() as db:
        manager = StorageManager(db)

        if migrate_kind in {"all", "document"}:
            q = db.query(Document).filter(Document.original_asset_id.is_(None)).order_by(Document.id.asc())
            if migrate_id:
                q = q.filter(Document.id == int(migrate_id))

            print("\nDOCUMENTS")
            for doc in q.all():
                migrate_document(db, manager, doc, dry_run)

        if migrate_kind in {"all", "comment"}:
            sql = """
                SELECT
                    cf.id,
                    cf.user_id,
                    cf.comment_id,
                    cf.file_name,
                    cf.media_address,
                    cf.asset_id
                FROM comment_files cf
                WHERE cf.asset_id IS NULL
                ORDER BY cf.id ASC
            """
            params = {}
            if migrate_id:
                sql = """
                    SELECT
                        cf.id,
                        cf.user_id,
                        cf.comment_id,
                        cf.file_name,
                        cf.media_address,
                        cf.asset_id
                    FROM comment_files cf
                    WHERE cf.asset_id IS NULL
                      AND cf.id = :file_id
                    ORDER BY cf.id ASC
                """
                params["file_id"] = int(migrate_id)

            print("\nCOMMENT FILES")
            rows = db.execute(text(sql), params).mappings().all()
            for row in rows:
                migrate_comment_file(db, manager, row, dry_run)


if __name__ == "__main__":
    main()
