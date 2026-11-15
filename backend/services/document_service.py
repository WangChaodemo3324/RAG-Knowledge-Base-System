from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import UploadFile

from backend.core.config import DATA_DIR, SUPPORTED_DOCUMENT_EXTENSIONS

MAX_UPLOAD_SIZE = 50 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024


class DocumentUploadError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def safe_upload_filename(filename: str | None) -> str:
    raw_name = (filename or "").replace("\\", "/")
    name = Path(raw_name).name.strip()
    if not name:
        raise DocumentUploadError("文件名不能为空。")

    for char in '<>:"/\\|?*':
        name = name.replace(char, "_")

    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise DocumentUploadError(f"只支持上传这些格式：{allowed}")
    return name


async def save_uploaded_document_batch(
    files: list[UploadFile], data_dir: Path = DATA_DIR
) -> list[dict[str, Any]]:
    """Save each file independently; per-file failures do not abort the batch."""
    saved: list[dict[str, Any]] = []
    for file in files:
        try:
            saved.append(await save_uploaded_document(file, data_dir))
        except DocumentUploadError as exc:
            saved.append(
                {
                    "filename": file.filename or "unknown",
                    "error": exc.message,
                    "status_code": exc.status_code,
                }
            )
    return saved


async def save_uploaded_document(file: UploadFile, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    filename = safe_upload_filename(file.filename)
    data_dir.mkdir(parents=True, exist_ok=True)

    target_path = data_dir / filename
    overwritten = target_path.exists()
    tmp_path = data_dir / f".{filename}.uploading"
    size = 0

    try:
        with tmp_path.open("wb") as output:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    raise DocumentUploadError("单个文件不能超过 50MB。", status_code=413)
                output.write(chunk)
        tmp_path.replace(target_path)
    except DocumentUploadError:
        tmp_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise DocumentUploadError(f"保存文件失败：{exc}", status_code=500) from exc
    finally:
        await file.close()

    return {
        "filename": filename,
        "saved_to": str(target_path),
        "size": size,
        "overwritten": overwritten,
        "message": "上传成功，准备进入增量入库。",
    }
