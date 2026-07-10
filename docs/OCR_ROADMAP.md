# OCR Roadmap

## Current MVP behavior

- CSV: parsed as structured line item data.
- XLSX: parsed as structured line item data, including invoice-like templates where the table starts below a title area.
- Text PDF: text is extracted first, then simple table-like lines are parsed.
- Scanned PDF: routed to `vision_stub:scan_pdf`.
- Phone photo / image upload: routed to `vision_stub:image`.
- XLS: accepted for upload, but returns `spreadsheet:xls_unsupported` until a legacy Excel parser is added.

## Why vision OCR is the main path

In expected operations, both delivery notes and invoices are often paper documents. They may arrive as scanned PDFs or phone photos. These files usually do not contain embedded text, so text extraction libraries such as `pypdf` cannot read line items.

The production path should therefore be:

1. Accept PDF, JPG, PNG, HEIC, TIFF, and similar files.
2. Convert PDF pages to images when needed.
3. Send images to an AI OCR provider.
4. Ask the provider to return structured JSON matching `ExtractedDocument`.
5. Show the JSON in OCR Review for human correction.
6. Run matching only after review is saved.

## Provider boundary

The current placeholder providers are:

- `spreadsheet:csv`
- `spreadsheet:xlsx`
- `text_pdf`
- `vision_stub:scan_pdf`
- `vision_stub:image`
- `spreadsheet:xls_unsupported`
- `unsupported`

The next implementation should replace `vision_stub:*` with a real provider while keeping the response shape stable.

## Target JSON shape

```json
{
  "document_type": "delivery_note",
  "vendor_name": "",
  "document_date": "",
  "document_number": "",
  "ocr_note": null,
  "ocr_provider": "vision_ai",
  "items": [
    {
      "item_name": "",
      "quantity": 0,
      "unit_price": 0,
      "amount": 0,
      "tax_rate": 10
    }
  ]
}
```

## Next tasks

- Add a real vision OCR provider behind the `vision_stub` boundary.
- Render scanned PDF pages to images before calling vision OCR.
- Add confidence fields per document and per line item.
- Add OCR review UI that is easier than editing raw JSON.
- Add tests with sample scanned PDF and phone photo fixtures.
