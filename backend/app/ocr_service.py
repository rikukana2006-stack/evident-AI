import csv
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.file_types import get_file_extension
from app.mock_ocr import run_mock_ocr
from app.schemas import ExtractedDocument


HEADER_ALIASES = {
    "item_name": {"item_name", "name", "product_name", "description", "品名", "商品名", "摘要"},
    "quantity": {"quantity", "qty", "数量"},
    "unit_price": {"unit_price", "price", "単価"},
    "amount": {"amount", "total", "金額", "合計"},
    "tax_rate": {"tax_rate", "tax", "税率"},
    "vendor_name": {"vendor_name", "vendor", "supplier", "取引先", "仕入先"},
    "document_date": {"document_date", "date", "issued_on", "日付", "発行日"},
    "document_number": {"document_number", "number", "no", "伝票番号", "書類番号"},
}


def normalize_header(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    for field, aliases in HEADER_ALIASES.items():
        if normalized in {alias.casefold() for alias in aliases}:
            return field
    return normalized


def parse_number(value: object, default: int = 0) -> float | int:
    text = str(value or "").strip()
    if not text:
        return default
    cleaned = re.sub(r"[,%円¥￥\s]", "", text)
    try:
        number = float(cleaned)
    except ValueError:
        return default
    return int(number) if number.is_integer() else number


def build_document(document_type: str, filename: str, rows: list[dict[str, object]]) -> ExtractedDocument:
    items = []
    first_row = rows[0] if rows else {}
    for row in rows:
        item_name = str(row.get("item_name") or "").strip()
        if not item_name:
            continue
        items.append(
            {
                "item_name": item_name,
                "quantity": parse_number(row.get("quantity")),
                "unit_price": parse_number(row.get("unit_price")),
                "amount": parse_number(row.get("amount")),
                "tax_rate": parse_number(row.get("tax_rate"), default=10),
            }
        )

    if not items:
        return run_mock_ocr(document_type)

    return ExtractedDocument.model_validate(
        {
            "document_type": document_type,
            "vendor_name": str(first_row.get("vendor_name") or "未設定"),
            "document_date": str(first_row.get("document_date") or "未設定"),
            "document_number": str(first_row.get("document_number") or Path(filename).stem),
            "items": items,
        }
    )


def build_empty_document(document_type: str, filename: str, ocr_note: str | None = None) -> ExtractedDocument:
    return ExtractedDocument.model_validate(
        {
            "document_type": document_type,
            "vendor_name": "",
            "document_date": "",
            "document_number": Path(filename).stem,
            "ocr_note": ocr_note,
            "items": [],
        }
    )


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def parse_csv_document(document_type: str, filename: str, storage_path: str) -> ExtractedDocument:
    text = read_text_file(Path(storage_path))
    reader = csv.DictReader(text.splitlines())
    rows = [{normalize_header(key): value for key, value in row.items()} for row in reader]
    return build_document(document_type, filename, rows)


def column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    index = 0
    for char in letters:
        index = index * 26 + (ord(char.upper()) - ord("A") + 1)
    return index - 1


def read_xlsx_shared_strings(package: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in package.namelist():
        return []
    root = ElementTree.fromstring(package.read("xl/sharedStrings.xml"))
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values = []
    for item in root.findall("x:si", namespace):
        values.append("".join(text.text or "" for text in item.findall(".//x:t", namespace)))
    return values


def read_xlsx_first_sheet_rows(storage_path: str) -> list[list[object]]:
    with zipfile.ZipFile(storage_path) as package:
        shared_strings = read_xlsx_shared_strings(package)
        sheet_name = "xl/worksheets/sheet1.xml"
        root = ElementTree.fromstring(package.read(sheet_name))
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows: list[list[object]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        values: list[object] = []
        for cell in row.findall("x:c", namespace):
            ref = cell.attrib.get("r", "")
            while len(values) <= column_index(ref):
                values.append("")
            raw_value = cell.find("x:v", namespace)
            inline_value = cell.find("x:is/x:t", namespace)
            if inline_value is not None:
                value: object = inline_value.text or ""
            elif raw_value is None:
                value = ""
            elif cell.attrib.get("t") == "s":
                value = shared_strings[int(raw_value.text or 0)]
            else:
                value = raw_value.text or ""
            values[column_index(ref)] = value
        rows.append(values)
    return rows


def parse_xlsx_document(document_type: str, filename: str, storage_path: str) -> ExtractedDocument:
    rows = read_xlsx_first_sheet_rows(storage_path)
    if not rows:
        return run_mock_ocr(document_type)
    headers = [normalize_header(value) for value in rows[0]]
    records = [dict(zip(headers, row, strict=False)) for row in rows[1:]]
    return build_document(document_type, filename, records)


def extract_pdf_text(storage_path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        reader = PdfReader(storage_path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def parse_pdf_text_rows(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = re.split(r"\s+", line)
        if len(parts) < 5:
            continue

        numeric_tail = parts[-4:]
        if any(parse_number(value, default=-1) == -1 for value in numeric_tail):
            continue

        rows.append(
            {
                "item_name": " ".join(parts[:-4]),
                "quantity": numeric_tail[0],
                "unit_price": numeric_tail[1],
                "amount": numeric_tail[2],
                "tax_rate": numeric_tail[3],
            }
        )
    return rows


def parse_pdf_document(document_type: str, filename: str, storage_path: str) -> ExtractedDocument:
    text = extract_pdf_text(storage_path)
    if not text.strip():
        return build_empty_document(
            document_type,
            filename,
            "\u0050\u0044\u0046\u304b\u3089\u30c6\u30ad\u30b9\u30c8\u3092\u62bd\u51fa\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u753b\u50cf\u0050\u0044\u0046\u306e\u5834\u5408\u306f\u3001\u73fe\u6642\u70b9\u3067\u306f\u624b\u5165\u529b\u307e\u305f\u306f\u0043\u0053\u0056\u002f\u0045\u0078\u0063\u0065\u006c\u3092\u3054\u5229\u7528\u304f\u3060\u3055\u3044\u3002",
        )

    rows = parse_pdf_text_rows(text)
    if not rows:
        return build_empty_document(
            document_type,
            filename,
            "\u0050\u0044\u0046\u304b\u3089\u6587\u5b57\u306f\u62bd\u51fa\u3067\u304d\u307e\u3057\u305f\u304c\u3001\u660e\u7d30\u884c\u3068\u3057\u3066\u89e3\u6790\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u004f\u0043\u0052\u30ec\u30d3\u30e5\u30fc\u3067\u5185\u5bb9\u3092\u624b\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
        )
    return build_document(document_type, filename, rows)


def run_ocr(document_type: str, filename: str, storage_path: str) -> ExtractedDocument:
    extension = get_file_extension(filename)
    if extension == ".pdf":
        return parse_pdf_document(document_type, filename, storage_path)
    if extension == ".csv":
        return parse_csv_document(document_type, filename, storage_path)
    if extension == ".xlsx":
        return parse_xlsx_document(document_type, filename, storage_path)
    return run_mock_ocr(document_type)
