# OCR Roadmap

## Current MVP behavior

- CSV: parsed as structured line item data.
- XLSX: parsed as structured line item data, including invoice-like templates where the table starts below a title area.
- Text PDF: text is extracted first, then simple table-like lines are parsed.
- Scanned PDF: rendered to PNG pages under `storage/ocr_work`, then routed to the configured vision provider.
- Phone photo / image upload: routed to the configured vision provider.
- XLS: accepted for upload, but returns `spreadsheet:xls_unsupported` until a legacy Excel parser is added.
- Manual line entry is an exception path only. The target workflow is automatic AI OCR extraction followed by review and correction.

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
- `vision_paddle:japan:PP-OCRv3`
- `spreadsheet:xls_unsupported`
- `unsupported`

The next implementation should replace `vision_stub:*` with a real provider while keeping the response shape stable.

The active provider is controlled by:

```env
EVIDENT_VISION_OCR_PROVIDER=stub
EVIDENT_OCR_WORK_DIR=storage/ocr_work
```

To enable OpenAI Vision OCR:

```env
EVIDENT_VISION_OCR_PROVIDER=openai
EVIDENT_OPENAI_API_KEY=sk-...
EVIDENT_OPENAI_VISION_MODEL=gpt-4.1-mini
EVIDENT_VISION_OCR_MAX_IMAGES=3
```

When `EVIDENT_VISION_OCR_PROVIDER=openai`, scanned PDFs are rendered to images first, then the selected images are sent to the OpenAI Responses API. If no API key is configured, the app keeps returning an OCR review note instead of failing the upload flow.

To enable free local PaddleOCR:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-paddle.txt
```

```env
EVIDENT_VISION_OCR_PROVIDER=paddle
EVIDENT_PADDLE_OCR_LANG=japan
EVIDENT_PADDLE_OCR_VERSION=PP-OCRv3
EVIDENT_VISION_OCR_MAX_IMAGES=3
```

PaddleOCR avoids per-page API charges, but it runs on the server and may require more CPU/RAM than the stub or OpenAI provider. It performs text recognition locally, then Evident AI attempts to structure recognized lines into item name, quantity, unit price, amount, and tax rate.

On Windows, Paddle's native inference layer can fail when model cache paths contain Japanese or other non-ASCII characters. By default, Evident AI stores PaddleOCR models under the Windows temp folder. If you need a fixed cache location, set an ASCII-only path:

```env
EVIDENT_PADDLE_CACHE_DIR=C:\Users\YOUR_NAME\AppData\Local\Temp\evident_ai_paddle_cache
```

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

- Validate PaddleOCR with real scanned PDF / phone photo samples.
- Configure OpenAI API key as a higher-accuracy provider option.
- Add confidence fields per document and per line item.
- Add OCR review UI that is easier than editing raw JSON.
- Add tests with sample scanned PDF and phone photo fixtures.
