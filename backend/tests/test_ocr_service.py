import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from app.ocr_service import parse_csv_document, parse_xlsx_document


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
