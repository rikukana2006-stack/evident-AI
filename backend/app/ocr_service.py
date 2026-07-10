import csv
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.file_types import get_file_extension, is_image_upload
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


def compact_text(value: object) -> str:
    return re.sub(r"[\s\u3000:：]+", "", str(value or "")).casefold()


def normalize_header(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    for field, aliases in HEADER_ALIASES.items():
        if normalized in {alias.casefold() for alias in aliases}:
            return field
    compacted = compact_text(value)
    if any(keyword in compacted for keyword in ("\u54c1\u540d", "\u5546\u54c1\u540d", "\u9805\u76ee", "\u660e\u7d30")):
        return "item_name"
    if "\u6570\u91cf" in compacted:
        return "quantity"
    if "\u5358\u4fa1" in compacted:
        return "unit_price"
    if "\u91d1\u984d" in compacted or "\u5408\u8a08" in compacted:
        return "amount"
    if "\u7a0e\u7387" in compacted:
        return "tax_rate"
    if any(keyword in compacted for keyword in ("\u53d6\u5f15\u5148", "\u4ed5\u5165\u5148", "\u5fa1\u4e2d")):
        return "vendor_name"
    if "\u767a\u884c\u65e5" in compacted or "\u65e5\u4ed8" in compacted:
        return "document_date"
    if "\u756a\u53f7" in compacted or compacted == "no":
        return "document_number"
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


def build_document(
    document_type: str,
    filename: str,
    rows: list[dict[str, object]],
    ocr_provider: str | None = None,
) -> ExtractedDocument:
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
        return build_empty_document(
            document_type,
            filename,
            "\u660e\u7d30\u884c\u3092\u89e3\u6790\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u004f\u0043\u0052\u30ec\u30d3\u30e5\u30fc\u3067\u624b\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
        )

    for item in items:
        if item["tax_rate"] > 100:
            item["tax_rate"] = 10

    return ExtractedDocument.model_validate(
        {
            "document_type": document_type,
            "vendor_name": str(first_row.get("vendor_name") or "未設定"),
            "document_date": str(first_row.get("document_date") or "未設定"),
            "document_number": str(first_row.get("document_number") or Path(filename).stem),
            "ocr_provider": ocr_provider,
            "items": items,
        }
    )


def build_empty_document(
    document_type: str,
    filename: str,
    ocr_note: str | None = None,
    ocr_provider: str | None = None,
) -> ExtractedDocument:
    return ExtractedDocument.model_validate(
        {
            "document_type": document_type,
            "vendor_name": "",
            "document_date": "",
            "document_number": Path(filename).stem,
            "ocr_note": ocr_note,
            "ocr_provider": ocr_provider,
            "items": [],
        }
    )


def run_vision_stub_ocr(document_type: str, filename: str, source_kind: str) -> ExtractedDocument:
    return build_empty_document(
        document_type,
        filename,
        (
            "\u753b\u50cf\u004f\u0043\u0052\u9023\u643a\u306f\u672a\u63a5\u7d9a\u3067\u3059\u3002"
            "\u30b9\u30ad\u30e3\u30f3\u0050\u0044\u0046\u3084\u30b9\u30de\u30db\u5199\u771f\u306f\u3001"
            "\u73fe\u6642\u70b9\u3067\u306f\u004f\u0043\u0052\u30ec\u30d3\u30e5\u30fc\u3067\u624b\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
            "\u5f8c\u7d9a\u3067\u0041\u0049\u0020\u004f\u0043\u0052\u3092\u63a5\u7d9a\u3059\u308b\u60f3\u5b9a\u306e\u5165\u53e3\u3067\u3059\u3002"
        ),
        f"vision_stub:{source_kind}",
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
    return build_document(document_type, filename, rows, "spreadsheet:csv")


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


def score_header_row(headers: list[str]) -> int:
    required_fields = {"item_name", "quantity", "unit_price", "amount"}
    return len(required_fields.intersection(headers))


def find_xlsx_header_row(rows: list[list[object]]) -> tuple[int, list[str]] | None:
    best: tuple[int, list[str], int] | None = None
    for index, row in enumerate(rows):
        headers = [normalize_header(value) for value in row]
        score = score_header_row(headers)
        if best is None or score > best[2]:
            best = (index, headers, score)
    if best and best[2] >= 2 and "item_name" in best[1]:
        return best[0], best[1]
    return None


def rows_after_header(rows: list[list[object]], header_index: int, headers: list[str]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    quantity_index = headers.index("quantity") if "quantity" in headers else len(headers)
    for row in rows[header_index + 1 :]:
        record: dict[str, object] = {}
        for column_index, header in enumerate(headers):
            if not header or header in record:
                continue
            value = row[column_index] if column_index < len(row) else ""
            record[header] = value

        item_name = str(record.get("item_name") or "").strip()
        if not item_name:
            candidates = [
                str(value or "").strip()
                for value in row[:quantity_index]
                if str(value or "").strip() and parse_number(value, default=-1) == -1
            ]
            if candidates:
                record["item_name"] = max(candidates, key=len)

        item_text = compact_text(record.get("item_name"))
        if any(keyword in item_text for keyword in ("\u5099\u8003", "\u5408\u8a08", "\u8ab2\u7a0e\u5bfe\u8c61", "\u9810\u308a\u91d1", "\u632f\u8fbc")):
            continue
        numeric_values = [
            parse_number(record.get("quantity")),
            parse_number(record.get("unit_price")),
            parse_number(record.get("amount")),
        ]
        if not any(value > 0 for value in numeric_values):
            continue
        if any(str(value or "").strip() for value in record.values()):
            records.append(record)
    return records


def parse_xlsx_document(document_type: str, filename: str, storage_path: str) -> ExtractedDocument:
    try:
        rows = read_xlsx_first_sheet_rows(storage_path)
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return build_empty_document(
            document_type,
            filename,
            "\u0045\u0078\u0063\u0065\u006c\u30d5\u30a1\u30a4\u30eb\u3092\u89e3\u6790\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u0058\u004c\u0053\u0058\u5f62\u5f0f\u304b\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
        )
    if not rows:
        return build_empty_document(document_type, filename, "\u0045\u0078\u0063\u0065\u006c\u306b\u8aad\u307f\u53d6\u308c\u308b\u884c\u304c\u3042\u308a\u307e\u305b\u3093\u3067\u3057\u305f\u3002")

    header = find_xlsx_header_row(rows)
    if header is None:
        return build_empty_document(
            document_type,
            filename,
            "\u0045\u0078\u0063\u0065\u006c\u5185\u3067\u660e\u7d30\u8868\u306e\u30d8\u30c3\u30c0\u30fc\u3092\u898b\u3064\u3051\u3089\u308c\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u9805\u76ee\u30fb\u6570\u91cf\u30fb\u5358\u4fa1\u30fb\u91d1\u984d\u306e\u5217\u3092\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
        )

    header_index, headers = header
    return build_document(document_type, filename, rows_after_header(rows, header_index, headers), "spreadsheet:xlsx")


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
        return run_vision_stub_ocr(document_type, filename, "scan_pdf")

    rows = parse_pdf_text_rows(text)
    if not rows:
        return build_empty_document(
            document_type,
            filename,
            "\u0050\u0044\u0046\u304b\u3089\u6587\u5b57\u306f\u62bd\u51fa\u3067\u304d\u307e\u3057\u305f\u304c\u3001\u660e\u7d30\u884c\u3068\u3057\u3066\u89e3\u6790\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u004f\u0043\u0052\u30ec\u30d3\u30e5\u30fc\u3067\u5185\u5bb9\u3092\u624b\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
        )
    return build_document(document_type, filename, rows, "text_pdf")


def run_ocr(document_type: str, filename: str, storage_path: str) -> ExtractedDocument:
    extension = get_file_extension(filename)
    if is_image_upload(filename):
        return run_vision_stub_ocr(document_type, filename, "image")
    if extension == ".pdf":
        return parse_pdf_document(document_type, filename, storage_path)
    if extension == ".csv":
        return parse_csv_document(document_type, filename, storage_path)
    if extension == ".xlsx":
        return parse_xlsx_document(document_type, filename, storage_path)
    if extension == ".xls":
        return build_empty_document(
            document_type,
            filename,
            "\u53e4\u3044\u0045\u0078\u0063\u0065\u006c\u5f62\u5f0f\u0028\u002e\u0078\u006c\u0073\u0029\u306f\u73fe\u6642\u70b9\u3067\u306f\u81ea\u52d5\u89e3\u6790\u306b\u672a\u5bfe\u5fdc\u3067\u3059\u3002\u002e\u0078\u006c\u0073\u0078\u307e\u305f\u306f\u0043\u0053\u0056\u306b\u5909\u63db\u3059\u308b\u304b\u3001\u004f\u0043\u0052\u30ec\u30d3\u30e5\u30fc\u3067\u624b\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
            "spreadsheet:xls_unsupported",
        )
    return build_empty_document(
        document_type,
        filename,
        "\u3053\u306e\u30d5\u30a1\u30a4\u30eb\u5f62\u5f0f\u306f\u004f\u0043\u0052\u306e\u81ea\u52d5\u89e3\u6790\u306b\u672a\u5bfe\u5fdc\u3067\u3059\u3002",
        "unsupported",
    )
