import base64
import json
import mimetypes
import shutil
import subprocess
from pathlib import Path

import httpx

from app.config import settings
from app.schemas import ExtractedDocument


VISION_OCR_PROMPT = """
You are an OCR engine for Japanese delivery notes and invoices.
Extract structured data from the provided document images.

Return only valid JSON matching this schema:
{
  "document_type": "delivery_note" | "invoice",
  "vendor_name": string,
  "document_date": string,
  "document_number": string,
  "items": [
    {
      "item_name": string,
      "quantity": number,
      "unit_price": number,
      "amount": number,
      "tax_rate": number
    }
  ]
}

Rules:
- Use the requested document_type.
- If a field is unknown, use an empty string for text fields and 0 for numbers.
- Use tax_rate 10 when the tax rate is not printed.
- Do not include markdown fences.
""".strip()


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


def image_to_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def extract_response_text(payload: dict) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    for output in payload.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    return ""


def parse_openai_ocr_response(document_type: str, filename: str, response_text: str) -> ExtractedDocument:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        return build_empty_vision_document(
            document_type,
            filename,
            "openai_parse_error",
            [],
            f"AI OCRのJSON解析に失敗しました: {exc}",
        )

    data["document_type"] = document_type
    data["ocr_provider"] = f"vision_openai:{settings.openai_vision_model}"
    data.setdefault("ocr_note", None)
    data.setdefault("items", [])
    return ExtractedDocument.model_validate(data)


def run_openai_vision_ocr(
    document_type: str,
    filename: str,
    source_kind: str,
    image_paths: list[Path],
) -> ExtractedDocument:
    if not settings.openai_api_key:
        return build_empty_vision_document(
            document_type,
            filename,
            source_kind,
            image_paths,
            "OpenAI APIキーが未設定のため、AI OCRは実行していません。",
        )

    selected_images = image_paths[: settings.vision_ocr_max_images]
    content = [{"type": "input_text", "text": f"{VISION_OCR_PROMPT}\nrequested_document_type: {document_type}"}]
    content.extend({"type": "input_image", "image_url": image_to_data_url(path)} for path in selected_images)

    try:
        with httpx.Client(timeout=90) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_vision_model,
                    "input": [{"role": "user", "content": content}],
                },
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        return build_empty_vision_document(
            document_type,
            filename,
            source_kind,
            image_paths,
            f"AI OCR API呼び出しに失敗しました: {exc}",
        )

    return parse_openai_ocr_response(document_type, filename, extract_response_text(response.json()))


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
        if settings.vision_ocr_provider == "openai":
            if note:
                return build_empty_vision_document(document_type, filename, source_kind, image_paths, note)
            return run_openai_vision_ocr(document_type, filename, source_kind, image_paths)
        return build_empty_vision_document(document_type, filename, source_kind, image_paths, note)

    image_paths = [Path(storage_path)]
    if settings.vision_ocr_provider == "openai":
        return run_openai_vision_ocr(document_type, filename, source_kind, image_paths)
    return build_empty_vision_document(document_type, filename, source_kind, image_paths)
