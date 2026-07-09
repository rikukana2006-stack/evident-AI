from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import settings


def save_upload(file: UploadFile) -> tuple[str, str]:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "upload.bin").suffix
    stored_name = f"{uuid4()}{suffix}"
    path = settings.storage_dir / stored_name
    with path.open("wb") as destination:
        destination.write(file.file.read())
    return file.filename or stored_name, str(path)
