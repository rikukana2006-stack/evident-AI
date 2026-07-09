from pathlib import Path


ALLOWED_FILE_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
    ".xlsx",
    ".xls",
    ".csv",
}

ALLOWED_FILE_TYPES_LABEL = "PDF, image, Excel, CSV"


def get_file_extension(filename: str | None) -> str:
    return Path(filename or "").suffix.casefold()


def is_allowed_upload(filename: str | None) -> bool:
    return get_file_extension(filename) in ALLOWED_FILE_EXTENSIONS
