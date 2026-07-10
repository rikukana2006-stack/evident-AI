from pathlib import Path


PDF_FILE_EXTENSIONS = {".pdf"}

IMAGE_FILE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}

SPREADSHEET_FILE_EXTENSIONS = {
    ".xlsx",
    ".xls",
    ".csv",
}

ALLOWED_FILE_EXTENSIONS = PDF_FILE_EXTENSIONS | IMAGE_FILE_EXTENSIONS | SPREADSHEET_FILE_EXTENSIONS

ALLOWED_FILE_TYPES_LABEL = "PDF, image, Excel, CSV"


def get_file_extension(filename: str | None) -> str:
    return Path(filename or "").suffix.casefold()


def is_allowed_upload(filename: str | None) -> bool:
    return get_file_extension(filename) in ALLOWED_FILE_EXTENSIONS


def is_image_upload(filename: str | None) -> bool:
    return get_file_extension(filename) in IMAGE_FILE_EXTENSIONS
