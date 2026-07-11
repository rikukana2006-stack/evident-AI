import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from app.config import settings
from app.file_types import is_allowed_upload
from app.ocr_service import parse_pdf_document, parse_pdf_text_rows, parse_csv_document, parse_xlsx_document, run_ocr
from app.vision_ocr import parse_ocr_text_rows, parse_openai_ocr_response, parse_paddle_token_rows


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
