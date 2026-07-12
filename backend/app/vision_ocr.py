import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.config import settings
from app.schemas import ExtractedDocument


_paddle_ocr_instance: Any | None = None
_paddle_ocr_key: tuple[str, str] | None = None
_paddle_ocr_lock = threading.Lock()


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


def configure_paddle_cache() -> Path:
    # Paddle's native inference layer can fail on Windows when model paths contain
    # non-ASCII characters. Use an ASCII temp path by default, while still allowing
    # deployments to pin the cache with EVIDENT_PADDLE_CACHE_DIR.
    cache_root = (
        settings.paddle_cache_dir
        if settings.paddle_cache_dir is not None
        else Path(tempfile.gettempdir()) / "evident_ai_paddle_cache"
    ).resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    paddle_profile = cache_root / "userprofile"
    paddle_profile.mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(paddle_profile)
    os.environ["HOME"] = str(paddle_profile)
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache_root / "paddlex"))
    os.environ.setdefault("PADDLE_HOME", str(cache_root / "paddle"))
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "xdg"))
    os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")
    return cache_root


def get_paddle_ocr() -> Any:
    global _paddle_ocr_instance, _paddle_ocr_key

    configure_paddle_cache()
    key = (settings.paddle_ocr_lang, settings.paddle_ocr_version)
    with _paddle_ocr_lock:
        if _paddle_ocr_instance is not None and _paddle_ocr_key == key:
            return _paddle_ocr_instance

        from paddleocr import PaddleOCR

        _paddle_ocr_instance = PaddleOCR(
            lang=settings.paddle_ocr_lang,
            ocr_version=settings.paddle_ocr_version,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        _paddle_ocr_key = key
        return _paddle_ocr_instance


def prepare_paddle_input_images(image_paths: list[Path], cache_root: Path) -> list[Path]:
    run_dir = cache_root / "input_images" / uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)

    prepared_paths: list[Path] = []
    for index, image_path in enumerate(image_paths, start=1):
        suffix = image_path.suffix if image_path.suffix else ".png"
        prepared_path = run_dir / f"page_{index}{suffix}"
        shutil.copyfile(image_path, prepared_path)
        prepared_paths.append(prepared_path)

    return prepared_paths


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
        "自動抽出を行うにはAI OCRプロバイダーを設定してください。"
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


def parse_number(value: object, default: int = 0) -> float | int:
    text = str(value or "").strip()
    if not text:
        return default
    cleaned = re.sub(r"[,%¥円\s]", "", text)
    try:
        number = float(cleaned)
    except ValueError:
        return default
    return int(number) if number.is_integer() else number


def parse_ocr_text_rows(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = re.split(r"\s+", line)
        if len(parts) < 4:
            continue

        numeric_values: list[str] = []
        while parts and len(numeric_values) < 4 and parse_number(parts[-1], default=-1) != -1:
            numeric_values.insert(0, parts.pop())

        if len(numeric_values) < 3 or not parts:
            continue

        if len(numeric_values) == 4:
            quantity, unit_price, amount, tax_rate = numeric_values
        else:
            quantity, unit_price, amount = numeric_values[-3:]
            tax_rate = "10"
        rows.append(
            {
                "item_name": " ".join(parts),
                "quantity": parse_number(quantity),
                "unit_price": parse_number(unit_price),
                "amount": parse_number(amount),
                "tax_rate": parse_number(tax_rate, default=10),
            }
        )
    return rows


def build_document_from_rows(
    document_type: str,
    filename: str,
    rows: list[dict[str, object]],
    provider: str,
    note: str | None = None,
) -> ExtractedDocument:
    return ExtractedDocument.model_validate(
        {
            "document_type": document_type,
            "vendor_name": "",
            "document_date": "",
            "document_number": Path(filename).stem,
            "ocr_note": note,
            "ocr_provider": provider,
            "items": rows,
        }
    )


def build_paddle_no_rows_note(text_lines: list[str]) -> str:
    preview = "\n".join(text_lines[:80])
    return (
        "PaddleOCRで文字は読み取りましたが、明細行に構造化できませんでした。"
        f"\n\n--- OCR text preview ---\n{preview}"
    )


def parse_paddle_token_rows(text_lines: list[str]) -> list[dict[str, object]]:
    product_candidates: list[str] = []
    amount_candidates: list[int] = []
    quantity = 1
    tax_rate = 10
    excluded_patterns = (
        "TEL",
        "No",
        "コード",
        "合計",
        "消費税",
        "税",
        "銀行",
        "支店",
        "営業",
        "会社",
        "本社",
        "当座",
        "前回",
        "今回",
        "請求",
        "納品",
        "毎度",
        "下記",
        "お問",
        "日付",
        "伝票",
        "商品",
        "差引",
    )

    for line in text_lines:
        text = str(line).strip()
        if not text:
            continue
        if re.fullmatch(r"\d+\s*[x×X]", text):
            quantity = parse_number(re.sub(r"\D", "", text), default=1)
        if "税" in text and re.search(r"10", text):
            tax_rate = 10

        number = parse_paddle_number(text)
        if number >= 100 and ("," in text or "，" in text):
            amount_candidates.append(number)

        has_japanese = re.search(r"[ぁ-んァ-ン一-龥]", text) is not None
        has_excluded = any(pattern in text for pattern in excluded_patterns)
        is_numeric_like = re.fullmatch(r"[\d\s,，.．円¥￥-]+", text) is not None
        if has_japanese and not has_excluded and not is_numeric_like and 3 <= len(text) <= 30:
            product_candidates.append(text)

    if not product_candidates or not amount_candidates:
        return []

    amount = select_likely_amount(amount_candidates)
    item_name = select_likely_item_name(product_candidates)
    return [
        {
            "item_name": item_name,
            "quantity": quantity,
            "unit_price": amount,
            "amount": amount,
            "tax_rate": tax_rate,
        }
    ]


def extract_paddle_cells(result: object, page_index: int | None = None) -> list[dict[str, object]]:
    cells: list[dict[str, object]] = []

    def to_box(value: object) -> list[float] | None:
        if hasattr(value, "tolist"):
            value = value.tolist()
        if not isinstance(value, list):
            return None
        if len(value) == 4 and all(isinstance(point, int | float) for point in value):
            return [float(point) for point in value]
        if len(value) == 4 and all(isinstance(point, list | tuple) and len(point) >= 2 for point in value):
            xs = [float(point[0]) for point in value]
            ys = [float(point[1]) for point in value]
            return [min(xs), min(ys), max(xs), max(ys)]
        return None

    def walk(value: object) -> None:
        if isinstance(value, dict):
            texts = value.get("rec_texts")
            boxes = value.get("rec_boxes")
            if boxes is None:
                boxes = value.get("rec_polys")
            if boxes is None:
                boxes = value.get("dt_polys")
            if isinstance(texts, list) and boxes is not None:
                if hasattr(boxes, "tolist"):
                    boxes = boxes.tolist()
                if isinstance(boxes, list):
                    for text, box_value in zip(texts, boxes):
                        text_value = str(text).strip()
                        box = to_box(box_value)
                        if text_value and box:
                            cells.append(
                                {
                                    "text": text_value,
                                    "page_index": page_index,
                                    "x1": box[0],
                                    "y1": box[1],
                                    "x2": box[2],
                                    "y2": box[3],
                                    "cx": (box[0] + box[2]) / 2,
                                    "cy": (box[1] + box[3]) / 2,
                                }
                            )
            for nested in value.values():
                walk(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                walk(nested)

    walk(result)
    return cells


def extract_paddle_cells_by_page(paddle_results: list[object]) -> list[dict[str, object]]:
    cells: list[dict[str, object]] = []
    for page_index, result in enumerate(paddle_results, start=1):
        cells.extend(extract_paddle_cells(result, page_index=page_index))
    return cells


def parse_paddle_position_rows(cells: list[dict[str, object]]) -> list[dict[str, object]]:
    if not cells:
        return []

    cells_by_page: dict[int, list[dict[str, object]]] = {}
    for cell in cells:
        page_index = int(cell.get("page_index") or 1)
        cells_by_page.setdefault(page_index, []).append(cell)

    if len(cells_by_page) > 1:
        parsed_rows: list[dict[str, object]] = []
        for page_index in sorted(cells_by_page):
            parsed_rows.extend(parse_paddle_position_rows(cells_by_page[page_index]))
        return parsed_rows

    rows = group_cells_by_y(cells)
    header_row = find_paddle_table_header_row(rows)
    if header_row is None:
        return []

    header_y = max(float(cell["cy"]) for cell in header_row)
    parsed_rows: list[dict[str, object]] = []
    for row in rows:
        row_y = sum(float(cell["cy"]) for cell in row) / len(row)
        if row_y <= header_y + 25 or row_y > header_y + 450:
            continue

        parsed = parse_paddle_position_row(row)
        if parsed:
            parsed_rows.append(parsed)

    return parsed_rows


def group_cells_by_y(cells: list[dict[str, object]], tolerance: float = 48) -> list[list[dict[str, object]]]:
    rows: list[list[dict[str, object]]] = []
    for cell in sorted(cells, key=lambda item: (float(item["cy"]), float(item["cx"]))):
        for row in rows:
            row_y = sum(float(existing["cy"]) for existing in row) / len(row)
            if abs(float(cell["cy"]) - row_y) <= tolerance:
                row.append(cell)
                break
        else:
            rows.append([cell])

    return [sorted(row, key=lambda item: float(item["cx"])) for row in rows]


def find_paddle_table_header_row(rows: list[list[dict[str, object]]]) -> list[dict[str, object]] | None:
    for row in rows:
        text = "".join(str(cell["text"]) for cell in row)
        score = 0
        for keyword in ("品", "名", "数量", "単価", "金額"):
            if keyword in text:
                score += 1
        if score >= 3:
            return row
    return None


def parse_paddle_position_row(row: list[dict[str, object]]) -> dict[str, object] | None:
    item_parts: list[str] = []
    quantity = 1
    unit_price = 0
    amount = 0

    for cell in row:
        text = str(cell["text"]).strip()
        x1 = float(cell["x1"])
        cx = float(cell["cx"])

        if 190 <= x1 <= 850 and is_likely_item_text(text):
            item_parts.append(text)
        elif 820 <= cx <= 1210 and re.fullmatch(r"\d+\s*[x×X]?", text):
            quantity = parse_number(re.sub(r"\D", "", text), default=1)
        elif 1180 <= cx <= 1425:
            unit_price = parse_paddle_number(text)
        elif cx >= 1425:
            amount = parse_paddle_number(text)

    item_name = " ".join(item_parts).strip()
    if not item_name or amount <= 0:
        return None
    if unit_price <= 0:
        unit_price = amount

    return {
        "item_name": item_name,
        "quantity": quantity,
        "unit_price": unit_price,
        "amount": amount,
        "tax_rate": 10,
    }


def is_likely_item_text(text: str) -> bool:
    if not re.search(r"[ぁ-んァ-ン一-龥]", text):
        return False
    if any(keyword in text for keyword in ("消費税", "ショウヒ", "ゼイ", "合計", "備考", "コード", "TEL", "問合")):
        return False
    return len(text) >= 3


def parse_paddle_number(text: str) -> int:
    normalized = text.replace("，", ",").replace("．", ".").strip()
    decimal_match = re.fullmatch(r"(\d{1,3}(?:,\d{3})+),00", normalized)
    if decimal_match:
        normalized = decimal_match.group(1)
    digits = re.sub(r"\D", "", normalized)
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def select_likely_amount(numbers: list[int]) -> int:
    counts: dict[int, int] = {}
    for number in numbers:
        if number < 100 or number > 10_000_000:
            continue
        counts[number] = counts.get(number, 0) + 1
    if not counts:
        return numbers[0]
    return sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)[0][0]


def select_likely_item_name(candidates: list[str]) -> str:
    preferred = [text for text in candidates if "用" in text]
    if not preferred:
        preferred = [text for text in candidates if any(keyword in text for keyword in ("剤", "料"))]
    if not preferred:
        preferred = [text for text in candidates if "品" in text]
    pool = preferred or candidates
    return sorted(pool, key=len, reverse=True)[0]


def flatten_paddle_result(result: object) -> list[str]:
    texts: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            rec_texts = value.get("rec_texts")
            if isinstance(rec_texts, list):
                texts.extend(str(text) for text in rec_texts if text)
            for key in ("text", "rec_text", "transcription"):
                text = value.get(key)
                if isinstance(text, str):
                    texts.append(text)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, (list, tuple)):
            if len(value) >= 2 and isinstance(value[1], (list, tuple)) and value[1] and isinstance(value[1][0], str):
                texts.append(value[1][0])
            else:
                for nested in value:
                    walk(nested)

    walk(result)
    return texts


def run_paddle_vision_ocr(
    document_type: str,
    filename: str,
    source_kind: str,
    image_paths: list[Path],
) -> ExtractedDocument:
    try:
        cache_root = configure_paddle_cache()
        ocr = get_paddle_ocr()
    except ImportError:
        return build_empty_vision_document(
            document_type,
            filename,
            source_kind,
            image_paths,
            "PaddleOCRが未インストールです。無料OCRを使うには backend で pip install -r requirements-paddle.txt を実行してください。",
        )

    selected_images = image_paths[: settings.vision_ocr_max_images]
    try:
        selected_images = prepare_paddle_input_images(selected_images, cache_root)
        text_lines: list[str] = []
        paddle_results: list[object] = []
        for image_path in selected_images:
            if hasattr(ocr, "ocr"):
                result = ocr.ocr(str(image_path))
            else:
                result = ocr.predict(str(image_path))
            paddle_results.append(result)
            text_lines.extend(flatten_paddle_result(result))
    except Exception as exc:
        return build_empty_vision_document(
            document_type,
            filename,
            source_kind,
            image_paths,
            f"PaddleOCRの実行に失敗しました: {exc}",
        )

    text = "\n".join(text_lines)
    cells = extract_paddle_cells_by_page(paddle_results)
    rows = parse_paddle_position_rows(cells)
    if not rows:
        rows = parse_ocr_text_rows(text)
    if not rows:
        rows = parse_paddle_token_rows(text_lines)
    note = None if rows else "PaddleOCRで文字は読み取りましたが、明細行に構造化できませんでした。"
    if rows:
        preview = "\n".join(text_lines[:40])
        note = f"PaddleOCRの文字認識結果から明細を推定しました。必要に応じて確認してください。\n\n--- OCR text preview ---\n{preview}"
    else:
        note = build_paddle_no_rows_note(text_lines)
    return build_document_from_rows(
        document_type,
        filename,
        rows,
        f"vision_paddle:{settings.paddle_ocr_lang}:{settings.paddle_ocr_version}",
        note,
    )


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
        if settings.vision_ocr_provider == "paddle":
            if note:
                return build_empty_vision_document(document_type, filename, source_kind, image_paths, note)
            return run_paddle_vision_ocr(document_type, filename, source_kind, image_paths)
        return build_empty_vision_document(document_type, filename, source_kind, image_paths, note)

    image_paths = [Path(storage_path)]
    if settings.vision_ocr_provider == "openai":
        return run_openai_vision_ocr(document_type, filename, source_kind, image_paths)
    if settings.vision_ocr_provider == "paddle":
        return run_paddle_vision_ocr(document_type, filename, source_kind, image_paths)
    return build_empty_vision_document(document_type, filename, source_kind, image_paths)
