from uuid import uuid4

from fastapi import UploadFile

from app.config import settings
from app.file_types import ALLOWED_FILE_TYPES_LABEL, get_file_extension, is_allowed_upload


class UnsupportedFileTypeError(ValueError):
    pass


def save_upload(file: UploadFile) -> tuple[str, str]:
    if not is_allowed_upload(file.filename):
        raise UnsupportedFileTypeError(f"Unsupported file type. Please upload {ALLOWED_FILE_TYPES_LABEL}.")

    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    suffix = get_file_extension(file.filename)
    stored_name = f"{uuid4()}{suffix}"
    path = settings.storage_dir / stored_name
    with path.open("wb") as destination:
        destination.write(file.file.read())
    return file.filename or stored_name, str(path)
