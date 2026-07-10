import shutil
import subprocess
from pathlib import Path

from app.config import settings
from app.schemas import ExtractedDocument


def find_pdftoppm_executable() -> str | None:
    executable = shutil.which("pdftoppm")
    if executable and not executable.lower().endswith(".cmd"):
        return executable

    if executable:
        wrapper_path = Path(executable)
        direct_executable = (wrapper_path.parent / "../native/poppler/Library/bin/pdftoppm.exe").resolve()
        if direct_executable.exists():
            return str(direct_executable)

    return executable


def build_empty_vision_document(
    document_type: str,
    filename: str,
    source_kind: str,
    image_paths: list[Path],
    extra_note: str | None = None,
) -> ExtractedDocument:
    provider = f"vision_{settings.vision_ocr_provider}:{source_kind}"
    image_count = len(image_paths)
    note = (
        f"画像OCR連携は {settings.vision_ocr_provider} です。"
        f"AI OCRへ渡す画像を {image_count} 件準備しました。"
        "現時点ではOCRレビューで手入力してください。"
    )
    if extra_note:
        note = f"{note} {extra_note}"

    return ExtractedDocument.model_validate(
        {
            "document_type": document_type,
            "vendor_name": "",
            "document_date": "",
            "document_number": Path(filename).stem,
            "ocr_note": note,
            "ocr_provider": provider,
            "items": [],
        }
    )


def render_pdf_pages_to_images(storage_path: str, filename: str) -> tuple[list[Path], str | None]:
    pdftoppm = find_pdftoppm_executable()
    if not pdftoppm:
        return [], "PDF画像化ツール pdftoppm が見つかりませんでした。"

    source = Path(storage_path).resolve()
    output_dir = settings.ocr_work_dir / source.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_prefix = (output_dir / Path(filename).stem).resolve()

    try:
        subprocess.run(
            [pdftoppm, "-png", "-r", "200", str(source), str(output_prefix)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return [], f"PDFを画像化できませんでした: {exc}"

    images = sorted(output_dir.glob(f"{output_prefix.name}-*.png"))
    if not images:
        return [], "PDF画像化は完了しましたが、画像ファイルが生成されませんでした。"
    return images, None


def run_vision_ocr(document_type: str, filename: str, storage_path: str, source_kind: str) -> ExtractedDocument:
    if source_kind == "scan_pdf":
        image_paths, note = render_pdf_pages_to_images(storage_path, filename)
        return build_empty_vision_document(document_type, filename, source_kind, image_paths, note)

    return build_empty_vision_document(document_type, filename, source_kind, [Path(storage_path)])
