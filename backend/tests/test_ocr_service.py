import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from app.config import settings
from app.file_types import is_allowed_upload
from app.ocr_service import parse_pdf_document, parse_pdf_text_rows, parse_csv_document, parse_xlsx_document, run_ocr
from app.vision_ocr import (
    parse_ocr_text_rows,
    extract_paddle_cells,
    parse_openai_ocr_response,
    parse_paddle_position_rows,
    parse_paddle_token_rows,
    prepare_paddle_input_images,
    run_paddle_prediction,
)


@pytest.fixture(autouse=True)
def use_stub_ocr_provider_for_unit_tests() -> None:
    original_provider = settings.vision_ocr_provider
    settings.vision_ocr_provider = "stub"
    yield
    settings.vision_ocr_provider = original_provider


def make_xlsx(rows: list[list[object]]) -> bytes:
    output = io.BytesIO()
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row):
            column = chr(ord("A") + column_index)
            ref = f"{column}{row_index}"
            if isinstance(value, int | float):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        "</worksheet>"
    )

    with zipfile.ZipFile(output, "w") as package:
        package.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        package.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        package.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        package.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        package.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def test_parse_csv_document_with_japanese_items(tmp_path: Path) -> None:
    csv_path = tmp_path / "delivery.csv"
    csv_path.write_text(
        "item_name,quantity,unit_price,amount,tax_rate\n"
        "\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73,20,100,2000,8\n"
        "\u30d1\u30f3,30,80,2400,8\n",
        encoding="utf-8-sig",
    )

    document = parse_csv_document("delivery_note", "delivery.csv", str(csv_path))

    assert document.document_type == "delivery_note"
    assert document.items[0].item_name == "\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73"
    assert str(document.items[0].quantity) == "20"
    assert str(document.items[1].unit_price) == "80"


def test_parse_xlsx_document_with_japanese_headers(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "delivery.xlsx"
    xlsx_path.write_bytes(
        make_xlsx(
            [
                ["\u54c1\u540d", "\u6570\u91cf", "\u5358\u4fa1", "\u91d1\u984d", "\u7a0e\u7387"],
                ["\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73", 20, 100, 2000, 8],
                ["\u30d1\u30f3", 30, 80, 2400, 8],
            ]
        )
    )

    document = parse_xlsx_document("delivery_note", "delivery.xlsx", str(xlsx_path))

    assert [item.item_name for item in document.items] == [
        "\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73",
        "\u30d1\u30f3",
    ]
    assert str(document.items[0].amount) == "2000"
    assert str(document.items[1].tax_rate) == "8"


def test_parse_xlsx_document_with_table_header_below_title(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "template.xlsx"
    xlsx_path.write_bytes(
        make_xlsx(
            [
                ["", "", "\u7d0d\u54c1\u66f8"],
                ["", "", ""],
                ["", "", "", "", "\u9805\u76ee", "", "\u6570\u91cf", "\u5358\u4fa1", "\u91d1\u984d", "\u6d88\u8cbb\u7a0e"],
                ["9", "\u7ba1\u7406\u8cbb\uff0f\u4eba\u30003\u5e74\u9593", "", "", "", "", 1, 40000, 40000, 4000],
                ["13", "\u76e3\u7406\u56e3\u4f53\u7acb\u66ff\u5206", "", "", "", "", 1, "", 10124, ""],
                ["", "\u5099\u8003", "", "", "", "", "", "", 54124, ""],
                ["", "\u632f\u8fbc\u53e3\u5ea7", "", "", "", "", "", "", "", ""],
            ]
        )
    )

    document = parse_xlsx_document("delivery_note", "template.xlsx", str(xlsx_path))

    assert [item.item_name for item in document.items] == [
        "\u7ba1\u7406\u8cbb\uff0f\u4eba\u30003\u5e74\u9593",
        "\u76e3\u7406\u56e3\u4f53\u7acb\u66ff\u5206",
    ]
    assert str(document.items[0].amount) == "40000"
    assert str(document.items[0].tax_rate) == "10"
    assert str(document.items[1].amount) == "10124"


def test_parse_pdf_text_rows_from_extracted_table_text() -> None:
    rows = parse_pdf_text_rows(
        "item quantity unit_price amount tax_rate\n"
        "\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73 20 100 2000 8\n"
        "\u30d1\u30f3 30 80 2400 8\n"
    )

    assert rows == [
        {
            "item_name": "\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73",
            "quantity": "20",
            "unit_price": "100",
            "amount": "2000",
            "tax_rate": "8",
        },
        {
            "item_name": "\u30d1\u30f3",
            "quantity": "30",
            "unit_price": "80",
            "amount": "2400",
            "tax_rate": "8",
        },
    ]


def test_parse_pdf_document_without_extractable_text_returns_empty_document(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% empty test placeholder\n")

    document = parse_pdf_document("delivery_note", "scan.pdf", str(pdf_path))

    assert document.document_type == "delivery_note"
    assert document.document_number == "scan"
    assert document.ocr_note is not None
    assert document.ocr_provider == "vision_stub:scan_pdf"
    assert document.items == []


def test_image_upload_uses_vision_stub_without_demo_fallback(tmp_path: Path) -> None:
    image_path = tmp_path / "phone-photo.jpg"
    image_path.write_bytes(b"fake image bytes")

    document = run_ocr("invoice", "phone-photo.jpg", str(image_path))

    assert document.document_type == "invoice"
    assert document.document_number == "phone-photo"
    assert document.ocr_provider == "vision_stub:image"
    assert document.ocr_note is not None
    assert document.items == []


def test_heic_upload_is_allowed_for_phone_photos() -> None:
    assert is_allowed_upload("receipt.heic")


def test_parse_openai_ocr_response_returns_structured_document() -> None:
    document = parse_openai_ocr_response(
        "invoice",
        "invoice.jpg",
        (
            '{"document_type":"invoice","vendor_name":"Supplier","document_date":"2026-07-10",'
            '"document_number":"INV-100","items":[{"item_name":"A","quantity":2,'
            '"unit_price":100,"amount":200,"tax_rate":10}]}'
        ),
    )

    assert document.document_type == "invoice"
    assert document.vendor_name == "Supplier"
    assert document.ocr_provider is not None
    assert document.items[0].item_name == "A"


def test_parse_openai_ocr_response_handles_invalid_json() -> None:
    document = parse_openai_ocr_response("delivery_note", "scan.jpg", "not-json")

    assert document.document_type == "delivery_note"
    assert document.ocr_provider == "vision_stub:openai_parse_error"
    assert document.ocr_note is not None
    assert document.items == []


def test_parse_ocr_text_rows_from_paddle_text_lines() -> None:
    rows = parse_ocr_text_rows(
        "\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73 20 100 2000 8\n"
        "\u30d1\u30f3 30 80 2400 8"
    )

    assert rows == [
        {
            "item_name": "\u660e\u6cbb\u304a\u3044\u3057\u3044\u725b\u4e73",
            "quantity": 20,
            "unit_price": 100,
            "amount": 2000,
            "tax_rate": 8,
        },
        {
            "item_name": "\u30d1\u30f3",
            "quantity": 30,
            "unit_price": 80,
            "amount": 2400,
            "tax_rate": 8,
        },
    ]


def test_parse_ocr_text_rows_filters_bank_transfer_lines() -> None:
    rows = parse_ocr_text_rows(
        "第四北越銀行神田中央当 下記銀行に御振込み下さい。 54900 5490 60390\n"
        "半透明 10×50袋 1 6400 6400"
    )

    assert [row["item_name"] for row in rows] == ["半透明 10×50袋"]


def test_parse_paddle_token_rows_estimates_line_from_ocr_cells() -> None:
    rows = parse_paddle_token_rows(
        [
            "\u5546\u54c1\u30b3\u30fc\u30c9",
            "\u54c1\u540d\u30fb\u898f\u683c",
            "\u75c5\u9662\u7528\u30cf\u30a4\u30bf\u30fc5k8",
            "1\u00d7",
            "3,360,00",
            "3,360",
            "\u6d88\u8cbb\u7a0e10\uff05",
            "336",
        ]
    )

    assert rows == [
        {
            "item_name": "\u75c5\u9662\u7528\u30cf\u30a4\u30bf\u30fc5k8",
            "quantity": 1,
            "unit_price": 3360,
            "amount": 3360,
            "tax_rate": 10,
        }
    ]


def test_parse_paddle_token_rows_ignores_bank_transfer_text() -> None:
    rows = parse_paddle_token_rows(
        [
            "第四北越銀行神田中央当 下記銀行に御振込み下さい。",
            "54,900",
            "5,490",
            "60,390",
        ]
    )

    assert rows == []


def test_parse_paddle_position_rows_uses_table_columns() -> None:
    cells = [
        {"text": "\u5546\u54c1\u30b3\u30fc\u30c9", "x1": 58, "y1": 535, "x2": 207, "y2": 563, "cx": 132.5, "cy": 549},
        {"text": "\u54c1", "x1": 270, "y1": 532, "x2": 307, "y2": 568, "cx": 288.5, "cy": 550},
        {"text": "\u540d\u30fb\u898f", "x1": 376, "y1": 534, "x2": 539, "y2": 565, "cx": 457.5, "cy": 549.5},
        {"text": "\u5165\u6570", "x1": 919, "y1": 534, "x2": 1016, "y2": 563, "cx": 967.5, "cy": 548.5},
        {"text": "\u7dcf\u6570\u91cf", "x1": 1041, "y1": 534, "x2": 1197, "y2": 562, "cx": 1119, "cy": 548},
        {"text": "\u5358\u4fa1", "x1": 1264, "y1": 532, "x2": 1356, "y2": 564, "cx": 1310, "cy": 548},
        {"text": "\u91d1\u984d", "x1": 1449, "y1": 530, "x2": 1544, "y2": 563, "cx": 1496.5, "cy": 546.5},
        {"text": "1\u00d7", "x1": 862, "y1": 583, "x2": 898, "y2": 612, "cx": 880, "cy": 597.5},
        {"text": "190812", "x1": 49, "y1": 618, "x2": 133, "y2": 646, "cx": 91, "cy": 632},
        {"text": "\u75c5\u9662\u7528\u30cf\u30a4\u30bf\u30fc5k8", "x1": 232, "y1": 618, "x2": 430, "y2": 647, "cx": 331, "cy": 632.5},
        {"text": "3,360,00", "x1": 1282, "y1": 616, "x2": 1396, "y2": 641, "cx": 1339, "cy": 628.5},
        {"text": "3,360", "x1": 1520, "y1": 615, "x2": 1593, "y2": 640, "cx": 1556.5, "cy": 627.5},
        {"text": "\u30b7\u30e7\u30a6\u30d2\u30bc\u30a410\uff05", "x1": 233, "y1": 683, "x2": 385, "y2": 710, "cx": 309, "cy": 696.5},
        {"text": "336", "x1": 1549, "y1": 679, "x2": 1594, "y2": 706, "cx": 1571.5, "cy": 692.5},
    ]

    assert parse_paddle_position_rows(cells) == [
        {
            "item_name": "\u75c5\u9662\u7528\u30cf\u30a4\u30bf\u30fc5k8",
            "quantity": 1,
            "unit_price": 3360,
            "amount": 3360,
            "tax_rate": 10,
        }
    ]


def test_parse_paddle_position_rows_keeps_pages_separate() -> None:
    def page_cells(page_index: int, item_name: str, amount: str) -> list[dict[str, object]]:
        return [
            {"page_index": page_index, "text": "\u5546\u54c1\u30b3\u30fc\u30c9", "x1": 58, "y1": 535, "x2": 207, "y2": 563, "cx": 132.5, "cy": 549},
            {"page_index": page_index, "text": "\u54c1", "x1": 270, "y1": 532, "x2": 307, "y2": 568, "cx": 288.5, "cy": 550},
            {"page_index": page_index, "text": "\u540d\u30fb\u898f", "x1": 376, "y1": 534, "x2": 539, "y2": 565, "cx": 457.5, "cy": 549.5},
            {"page_index": page_index, "text": "\u7dcf\u6570\u91cf", "x1": 1041, "y1": 534, "x2": 1197, "y2": 562, "cx": 1119, "cy": 548},
            {"page_index": page_index, "text": "\u5358\u4fa1", "x1": 1264, "y1": 532, "x2": 1356, "y2": 564, "cx": 1310, "cy": 548},
            {"page_index": page_index, "text": "\u91d1\u984d", "x1": 1449, "y1": 530, "x2": 1544, "y2": 563, "cx": 1496.5, "cy": 546.5},
            {"page_index": page_index, "text": "1\u00d7", "x1": 862, "y1": 583, "x2": 898, "y2": 612, "cx": 880, "cy": 597.5},
            {"page_index": page_index, "text": item_name, "x1": 232, "y1": 618, "x2": 500, "y2": 647, "cx": 366, "cy": 632.5},
            {"page_index": page_index, "text": amount, "x1": 1282, "y1": 616, "x2": 1396, "y2": 641, "cx": 1339, "cy": 628.5},
            {"page_index": page_index, "text": amount, "x1": 1520, "y1": 615, "x2": 1593, "y2": 640, "cx": 1556.5, "cy": 627.5},
        ]

    rows = parse_paddle_position_rows(
        page_cells(1, "\u75c5\u9662\u7528\u30cf\u30a4\u30bf\u30fc5k8", "3,360")
        + page_cells(2, "\u696d\u52d9\u7528\u6d17\u5264", "1,200")
    )

    assert [row["item_name"] for row in rows] == ["\u75c5\u9662\u7528\u30cf\u30a4\u30bf\u30fc5k8", "\u696d\u52d9\u7528\u6d17\u5264"]
    assert [row["amount"] for row in rows] == [3360, 1200]


def test_parse_paddle_position_rows_keeps_headerless_continuation_pages() -> None:
    header = [
        {"page_index": 1, "text": "\u5546\u54c1\u30b3\u30fc\u30c9", "x1": 58, "y1": 535, "x2": 207, "y2": 563, "cx": 132.5, "cy": 549},
        {"page_index": 1, "text": "\u54c1", "x1": 270, "y1": 532, "x2": 307, "y2": 568, "cx": 288.5, "cy": 550},
        {"page_index": 1, "text": "\u540d\u30fb\u898f", "x1": 376, "y1": 534, "x2": 539, "y2": 565, "cx": 457.5, "cy": 549.5},
        {"page_index": 1, "text": "\u7dcf\u6570\u91cf", "x1": 1041, "y1": 534, "x2": 1197, "y2": 562, "cx": 1119, "cy": 548},
        {"page_index": 1, "text": "\u5358\u4fa1", "x1": 1264, "y1": 532, "x2": 1356, "y2": 564, "cx": 1310, "cy": 548},
        {"page_index": 1, "text": "\u91d1\u984d", "x1": 1449, "y1": 530, "x2": 1544, "y2": 563, "cx": 1496.5, "cy": 546.5},
    ]
    first_page_item = [
        {"page_index": 1, "text": "1\u00d7", "x1": 862, "y1": 583, "x2": 898, "y2": 612, "cx": 880, "cy": 597.5},
        {"page_index": 1, "text": "\u75c5\u9662\u7528\u30cf\u30a4\u30bf\u30fc5k8", "x1": 232, "y1": 618, "x2": 500, "y2": 647, "cx": 366, "cy": 632.5},
        {"page_index": 1, "text": "3,360", "x1": 1282, "y1": 616, "x2": 1396, "y2": 641, "cx": 1339, "cy": 628.5},
        {"page_index": 1, "text": "3,360", "x1": 1520, "y1": 615, "x2": 1593, "y2": 640, "cx": 1556.5, "cy": 627.5},
    ]
    second_page_item_without_header = [
        {"page_index": 2, "text": "2\u00d7", "x1": 862, "y1": 180, "x2": 898, "y2": 210, "cx": 880, "cy": 195},
        {"page_index": 2, "text": "\u696d\u52d9\u7528\u6d17\u5264", "x1": 232, "y1": 215, "x2": 500, "y2": 245, "cx": 366, "cy": 230},
        {"page_index": 2, "text": "1,200", "x1": 1282, "y1": 214, "x2": 1396, "y2": 242, "cx": 1339, "cy": 228},
        {"page_index": 2, "text": "2,400", "x1": 1520, "y1": 214, "x2": 1593, "y2": 242, "cx": 1556.5, "cy": 228},
    ]

    rows = parse_paddle_position_rows(header + first_page_item + second_page_item_without_header)

    assert [row["item_name"] for row in rows] == ["\u75c5\u9662\u7528\u30cf\u30a4\u30bf\u30fc5k8", "\u696d\u52d9\u7528\u6d17\u5264"]
    assert [row["quantity"] for row in rows] == [1, 2]
    assert [row["amount"] for row in rows] == [3360, 2400]


def test_parse_paddle_position_rows_keeps_lower_page_items() -> None:
    cells = [
        {"page_index": 1, "text": "\u5546\u54c1\u30b3\u30fc\u30c9", "x1": 58, "y1": 535, "x2": 207, "y2": 563, "cx": 132.5, "cy": 549},
        {"page_index": 1, "text": "\u54c1", "x1": 270, "y1": 532, "x2": 307, "y2": 568, "cx": 288.5, "cy": 550},
        {"page_index": 1, "text": "\u540d\u30fb\u898f", "x1": 376, "y1": 534, "x2": 539, "y2": 565, "cx": 457.5, "cy": 549.5},
        {"page_index": 1, "text": "\u7dcf\u6570\u91cf", "x1": 1041, "y1": 534, "x2": 1197, "y2": 562, "cx": 1119, "cy": 548},
        {"page_index": 1, "text": "\u5358\u4fa1", "x1": 1264, "y1": 532, "x2": 1356, "y2": 564, "cx": 1310, "cy": 548},
        {"page_index": 1, "text": "\u91d1\u984d", "x1": 1449, "y1": 530, "x2": 1544, "y2": 563, "cx": 1496.5, "cy": 546.5},
        {"page_index": 1, "text": "1\u00d7", "x1": 862, "y1": 1080, "x2": 898, "y2": 1110, "cx": 880, "cy": 1095},
        {"page_index": 1, "text": "\u4e0b\u6bb5\u306e\u5546\u54c1", "x1": 232, "y1": 1115, "x2": 500, "y2": 1145, "cx": 366, "cy": 1130},
        {"page_index": 1, "text": "980", "x1": 1282, "y1": 1114, "x2": 1396, "y2": 1142, "cx": 1339, "cy": 1128},
        {"page_index": 1, "text": "980", "x1": 1520, "y1": 1114, "x2": 1593, "y2": 1142, "cx": 1556.5, "cy": 1128},
    ]

    assert parse_paddle_position_rows(cells)[0]["item_name"] == "\u4e0b\u6bb5\u306e\u5546\u54c1"


def test_extract_paddle_cells_handles_box_arrays_without_boolean_checks() -> None:
    class BoxArray:
        def __init__(self, values: list[list[int]]) -> None:
            self.values = values

        def tolist(self) -> list[list[int]]:
            return self.values

    cells = extract_paddle_cells({"rec_texts": ["A"], "rec_boxes": BoxArray([[1, 2, 3, 4]])})

    assert cells == [{"text": "A", "page_index": None, "x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0, "cx": 2.0, "cy": 3.0}]


def test_prepare_paddle_input_images_uses_ascii_paths(tmp_path: Path) -> None:
    source = tmp_path / "\u6c34\u91ce\u7d0d\u54c1\u66f8-1.png"
    source.write_bytes(b"png bytes")
    cache_root = tmp_path / "paddle-cache"

    prepared = prepare_paddle_input_images([source], cache_root)

    assert prepared[0].name == "page_1.png"
    assert prepared[0].read_bytes() == b"png bytes"
    assert str(prepared[0]).isascii()


def test_run_paddle_prediction_prefers_predict(tmp_path: Path) -> None:
    image_path = tmp_path / "page_1.png"
    image_path.write_bytes(b"png bytes")

    class PaddleStub:
        def predict(self, path: str) -> list[dict[str, str]]:
            return [{"called": "predict", "path": path}]

        def ocr(self, path: str) -> list[dict[str, str]]:
            raise AssertionError(f"legacy ocr() should not be called for {path}")

    assert run_paddle_prediction(PaddleStub(), image_path) == [{"called": "predict", "path": str(image_path)}]
